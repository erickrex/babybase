"""Swipe and match views for BabyBase."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.models import MatchStatus, MutualMatch, Name
from core.pagination import StandardPagination
from core.serializers.swipes import (
    MatchDetailSerializer,
    MatchSerializer,
    ShortlistSerializer,
    SwipeSerializer,
)
from core.services.couples import get_couple_for_user
from core.services.swipes import (
    SwipeValidationError,
    check_mutual_match,
    create_match,
    get_similar_names,
    record_swipe,
    validate_swipe,
)
from core.throttles import SwipeRateThrottle

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([SwipeRateThrottle])
def swipe_view(request: Request) -> Response:
    """
    Record a swipe action on a name.

    POST /api/v1/swipes/

    Accepts:
        name_id: UUID of the name
        action: 'like', 'dislike', or 'maybe'
        deck_id: (optional) UUID of the source deck

    Returns:
        {is_match: bool, match: {...} | null, swipe: {...}}

    Handles duplicate swipes gracefully (returns existing, no error).
    """
    serializer = SwipeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get user's couple
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to swipe."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    name_id = str(serializer.validated_data["name_id"])
    action = serializer.validated_data["action"]
    deck_id = serializer.validated_data.get("deck_id")
    deck_id_str = str(deck_id) if deck_id else None

    # Validate the swipe
    try:
        validate_swipe(request.user, couple, name_id)
    except SwipeValidationError as e:
        logger.warning("Swipe validation failed: user=%s name=%s reason=%s", request.user.email, name_id, str(e))
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Record the swipe (handles duplicates gracefully)
    swipe, created = record_swipe(
        user=request.user,
        couple=couple,
        name_id=name_id,
        action=action,
        deck_id=deck_id_str,
    )

    # Check for mutual match (only if action is 'like')
    is_match = False
    match_data = None

    if action == "like":
        if check_mutual_match(couple, name_id):
            match = create_match(couple, name_id)
            # Fetch with select_related to access display_name efficiently
            match = MutualMatch.objects.select_related("name").get(id=match.id)
            is_match = True
            match_data = {
                "id": str(match.id),
                "name_id": str(match.name_id),
                "display_name": match.name.display_name,
                "matched_at": match.matched_at.isoformat(),
                "match_strength_score": match.match_strength_score,
                "status": match.status,
            }
            logger.info("Mutual match! couple=%s name=%s (%s)", couple.id, name_id, match.name.display_name)

    if created:
        logger.debug("Swipe recorded: user=%s name=%s action=%s", request.user.email, name_id, action)

    return Response(
        {
            "status": "success",
            "data": {
                "is_match": is_match,
                "match": match_data,
                "swipe": {
                    "id": str(swipe.id),
                    "name_id": str(swipe.name_id),
                    "action": swipe.action,
                    "created_at": swipe.created_at.isoformat(),
                    "was_duplicate": not created,
                },
            },
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def matches_list_view(request: Request) -> Response:
    """
    List all mutual matches for the user's couple.

    GET /api/v1/matches/

    Returns paginated MutualMatch records with name details.
    Supports ?page=N and ?page_size=N query params.
    """
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to view matches."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    matches = (
        MutualMatch.objects.filter(couple=couple)
        .select_related("name")
        .order_by("-matched_at")
    )

    paginator = StandardPagination()
    page = paginator.paginate_queryset(matches, request)
    serialized = MatchSerializer(page, many=True).data
    return paginator.get_paginated_response({"status": "success", "data": serialized})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def match_detail_view(request: Request, name_id: str) -> Response:
    """
    Get match detail with semantic fit breakdown.

    GET /api/v1/matches/{name_id}/

    Returns name metadata + semantic fit breakdown percentages.
    """
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to view match details."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        match = MutualMatch.objects.select_related("name").get(
            couple=couple, name_id=name_id
        )
    except MutualMatch.DoesNotExist:
        return Response(
            {"status": "error", "message": "Match not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Compute semantic fit breakdown percentages
    name = match.name
    breakdown = _compute_semantic_breakdown(name)

    # Attach breakdown to match for serializer access
    match.semantic_fit_breakdown = breakdown
    data = MatchDetailSerializer(match).data

    return Response(
        {"status": "success", "data": data},
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def similar_names_view(request: Request, name_id: str) -> Response:
    """
    Get names similar to a matched name ("More Like This").

    GET /api/v1/matches/{name_id}/similar/

    Fetches the name's vector from Qdrant, searches nearest neighbors
    excluding already-swiped names. Returns top 10 similar names.
    """
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to find similar names."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify the name exists
    if not Name.objects.filter(id=name_id).exists():
        return Response(
            {"status": "error", "message": "Name not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get similar names from Qdrant
    similar = get_similar_names(name_id, couple)

    # Format response
    results = []
    for item in similar:
        results.append({
            "name_id": item.get("name_id"),
            "canonical_name": item.get("canonical_name"),
            "score": item.get("score", 0.0),
            "origin_backgrounds": item.get("payload", {}).get("origin_backgrounds", []),
            "gender_usage": item.get("payload", {}).get("gender_usage", []),
            "length_category": item.get("payload", {}).get("length_category", ""),
            "age_style_category": item.get("payload", {}).get("age_style_category", ""),
        })

    return Response(
        {"status": "success", "data": results},
        status=status.HTTP_200_OK,
    )


def _compute_semantic_breakdown(name: Name) -> dict:
    """
    Compute semantic fit breakdown percentages for a name.

    Returns a dict with percentage scores for style, heritage, local fit, and historical.
    Each value is 0-100.
    """
    # Style score: based on age_style_category
    style_map = {"classic": 80, "modern": 70, "timeless": 90}
    style_pct = style_map.get(name.age_style_category, 50)

    # Heritage score: based on origin diversity
    origin_count = len(name.origin_backgrounds) if name.origin_backgrounds else 0
    heritage_pct = min(int((origin_count / 5.0) * 100), 100)

    # Local fit: based on language diversity (proxy for international usability)
    lang_count = len(name.languages) if name.languages else 0
    local_pct = min(int((lang_count / 4.0) * 100), 100)

    # Historical: direct from significance score
    historical_pct = int(name.historical_significance_score * 100)

    return {
        "style": style_pct,
        "heritage": heritage_pct,
        "local_fit": local_pct,
        "historical": historical_pct,
    }



@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def shortlist_view(request: Request) -> Response:
    """
    Combined shortlist endpoint.

    GET /api/v1/shortlist/ — return shortlisted matches ordered by rank
    POST /api/v1/shortlist/ — promote match to shortlisted status

    GET returns paginated shortlisted matches with name details, ordered by
    match_strength_score desc. Supports ?page=N and ?page_size=N query params.

    POST accepts:
        name_id: UUID of the matched name to shortlist
    """
    if request.method == "GET":
        couple = get_couple_for_user(request.user)
        if not couple:
            return Response(
                {"status": "error", "message": "You must be in a couple to view shortlist."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        matches = (
            MutualMatch.objects.filter(couple=couple, status=MatchStatus.SHORTLISTED)
            .select_related("name")
            .order_by("-match_strength_score")
        )

        paginator = StandardPagination()
        page = paginator.paginate_queryset(matches, request)
        serialized = MatchSerializer(page, many=True).data
        return paginator.get_paginated_response({"status": "success", "data": serialized})

    # POST — promote match to shortlisted status
    serializer = ShortlistSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to manage shortlist."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    name_id = str(serializer.validated_data["name_id"])

    # Find the match
    try:
        match = MutualMatch.objects.select_related("name").get(
            couple=couple, name_id=name_id
        )
    except MutualMatch.DoesNotExist:
        return Response(
            {"status": "error", "message": "Match not found. Only mutual matches can be shortlisted."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Promote to shortlisted
    match.status = MatchStatus.SHORTLISTED
    match.save(update_fields=["status", "updated_at"])

    return Response(
        {
            "status": "success",
            "data": {
                "id": str(match.id),
                "name_id": str(match.name_id),
                "status": match.status,
                "match_strength_score": match.match_strength_score,
            },
            "message": "Match added to shortlist.",
        },
        status=status.HTTP_200_OK,
    )
