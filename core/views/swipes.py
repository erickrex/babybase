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
    ShortlistRemovalSerializer,
    ShortlistSerializer,
    SimilarNameSerializer,
    SoundsLikeNameSerializer,
    SwipeSerializer,
)
from core.services.couples import get_couple_for_user
from core.services.swipes import (
    SwipeValidationError,
    check_mutual_match,
    create_match,
    get_similar_names,
    get_sounds_like_names,
    record_swipe,
    validate_source_deck,
    validate_swipe,
)
from core.services.taste_vectors import maybe_recompute_taste_vector
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
        source_deck = validate_source_deck(couple, name_id, deck_id_str)
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
        source_deck=source_deck,
    )

    # Check for mutual match only if the stored swipe is actually a 'like'.
    # When a duplicate is returned, the stored action may differ from the request action.
    is_match = False
    match_data = None

    if swipe.action == "like":
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
        # Refresh the swiper's taste vector on batch boundaries (Phase D signal).
        # Safe by contract: never raises into the swipe path.
        maybe_recompute_taste_vector(request.user)

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

    similar = get_similar_names(name_id, couple)
    results = SimilarNameSerializer(similar, many=True).data

    return Response(
        {"status": "success", "data": results},
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sounds_like_view(request: Request, name_id: str) -> Response:
    """
    Get names that sound similar to a matched name ("Sounds Like").

    GET /api/v1/matches/{name_id}/sounds-like/

    Anchors on the name's stored phonetic_style vector in Qdrant (no
    query-time embedding) and searches nearest neighbors in sound space,
    excluding already-swiped names. Returns top 10 similar-sounding names.
    """
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to find similar-sounding names."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify the name exists
    if not Name.objects.filter(id=name_id).exists():
        return Response(
            {"status": "error", "message": "Name not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    sounds_like = get_sounds_like_names(name_id, couple)
    results = SoundsLikeNameSerializer(sounds_like, many=True).data

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



@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def shortlist_view(request: Request) -> Response:
    """
    Combined shortlist endpoint.

    GET /api/v1/shortlist/ — return shortlisted matches ordered by rank
    POST /api/v1/shortlist/ — promote match to shortlisted status
    DELETE /api/v1/shortlist/ — demote match back to active (remove from shortlist)

    GET returns paginated shortlisted matches with name details, ordered by
    match_strength_score desc. Supports ?page=N and ?page_size=N query params.

    POST and DELETE accept:
        name_id: UUID of the matched name to (un)shortlist
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

    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to manage shortlist."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if request.method == "DELETE":
        return _handle_shortlist_removal(request, couple)

    # POST — promote to shortlisted
    serializer = ShortlistSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    name_id = str(serializer.validated_data["name_id"])
    try:
        match = MutualMatch.objects.select_related("name").get(couple=couple, name_id=name_id)
    except MutualMatch.DoesNotExist:
        return Response(
            {"status": "error", "message": "Match not found. Only mutual matches can be shortlisted."},
            status=status.HTTP_404_NOT_FOUND,
        )

    match.status = MatchStatus.SHORTLISTED
    match.save(update_fields=["status", "updated_at"])
    logger.info("Match added to shortlist: couple=%s name=%s", couple.id, name_id)

    return Response(
        {
            "status": "success",
            "data": _shortlist_match_payload(match),
            "message": "Match added to shortlist.",
        },
        status=status.HTTP_200_OK,
    )


def _shortlist_match_payload(match: MutualMatch) -> dict:
    """Build the consistent response payload for a shortlist mutation."""
    return {
        "id": str(match.id),
        "name_id": str(match.name_id),
        "status": match.status,
        "match_strength_score": match.match_strength_score,
        "removal_requested_by": (
            str(match.removal_requested_by_id) if match.removal_requested_by_id else None
        ),
        "removal_pending": match.removal_requested_by_id is not None,
    }


def _handle_shortlist_removal(request: Request, couple) -> Response:
    """Two-step shortlist removal requiring partner approval.

    - Solo couple (no partner): removal is immediate.
    - decision="cancel": requester withdraws their own pending request.
    - decision="reject": the other partner declines a pending request.
    - no decision: request removal, or approve if the partner already requested.
    """
    serializer = ShortlistRemovalSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    name_id = str(serializer.validated_data["name_id"])
    decision = serializer.validated_data.get("decision")

    try:
        match = MutualMatch.objects.select_related("name").get(couple=couple, name_id=name_id)
    except MutualMatch.DoesNotExist:
        return Response(
            {"status": "error", "message": "Match not found. Only mutual matches can be shortlisted."},
            status=status.HTTP_404_NOT_FOUND,
        )

    partner = couple.user_b if couple.user_a_id == request.user.id else couple.user_a

    def _remove() -> None:
        match.status = MatchStatus.ACTIVE
        match.removal_requested_by = None
        match.save(update_fields=["status", "removal_requested_by", "updated_at"])

    def _respond(message: str) -> Response:
        return Response(
            {"status": "success", "data": _shortlist_match_payload(match), "message": message},
            status=status.HTTP_200_OK,
        )

    # Solo couple — no partner to consult, remove immediately.
    if partner is None:
        _remove()
        logger.info("Match removed from shortlist (solo couple): couple=%s name=%s", couple.id, name_id)
        return _respond("Match removed from shortlist.")

    # Explicit cancel: requester withdraws their own pending request.
    if decision == "cancel":
        if match.removal_requested_by_id == request.user.id:
            match.removal_requested_by = None
            match.save(update_fields=["removal_requested_by", "updated_at"])
            logger.info("Removal request cancelled: couple=%s name=%s", couple.id, name_id)
        return _respond("Removal request cancelled.")

    # Explicit reject: the other partner declines a pending request.
    if decision == "reject":
        if match.removal_requested_by_id and match.removal_requested_by_id != request.user.id:
            match.removal_requested_by = None
            match.save(update_fields=["removal_requested_by", "updated_at"])
            logger.info("Removal request rejected: couple=%s name=%s", couple.id, name_id)
        return _respond("Removal request declined.")

    # No decision: either approve the partner's pending request, or open one.
    if match.removal_requested_by_id and match.removal_requested_by_id != request.user.id:
        # The other partner already requested — this DELETE approves it.
        _remove()
        logger.info("Removal request approved: couple=%s name=%s", couple.id, name_id)
        return _respond("Match removed from shortlist.")

    if match.removal_requested_by_id == request.user.id:
        # Already requested by me — idempotent, still waiting on partner.
        return _respond("Removal already requested. Waiting for your partner to approve.")

    # No pending request — open one.
    match.removal_requested_by = request.user
    match.save(update_fields=["removal_requested_by", "updated_at"])
    logger.info("Removal requested: couple=%s name=%s by=%s", couple.id, name_id, request.user.email)
    return _respond("Removal requested. Waiting for your partner to approve.")
