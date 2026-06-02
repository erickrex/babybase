"""Recommendation views for BabyBase."""

import logging

from django.core.exceptions import ImproperlyConfigured
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.models import RecommendationDeck
from core.serializers.recommendations import (
    DeckItemSerializer,
    GenerateDeckSerializer,
)
from core.services.couples import get_couple_for_user
from core.services.recommendations import DeckEligibilityError, generate_deck, get_cached_deck, prepare_couple_for_deck
from core.services.taste_drift import compute_taste_drift

logger = logging.getLogger(__name__)


def _serialize_deck(
    deck: RecommendationDeck,
    *,
    cached: bool,
    include_drift: bool = False,
    exclude_swiped: bool = False,
) -> dict:
    """Serialize a recommendation deck response payload."""
    deck_items = deck.items.select_related("name").order_by("rank")
    if exclude_swiped:
        swiped_name_ids = deck.couple.swipes.values_list("name_id", flat=True).distinct()
        deck_items = deck_items.exclude(name_id__in=swiped_name_ids)

    response_data = {
        "id": str(deck.id),
        "mode": deck.mode,
        "created_at": deck.created_at.isoformat(),
        "expires_at": deck.expires_at.isoformat() if deck.expires_at else None,
        "cached": cached,
        "items": DeckItemSerializer(deck_items, many=True).data,
    }

    if include_drift:
        drift = compute_taste_drift(deck.couple)
        if drift.get("summary"):
            response_data["taste_drift"] = {
                "summary": drift["summary"],
                "converging_traits": drift["converging_traits"],
            }

    return response_data


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_deck_view(request: Request) -> Response:
    """
    Generate a new recommendation deck for the user's couple.

    POST /api/v1/recommendations/deck/

    Accepts:
        mode: str (default: 'best_match') — one of best_match, bridge_names,
              more_like_this, wildcard

    Validates:
        - User must be in an active couple
        - Both partners must have completed onboarding

    Returns:
        deck_id + ordered items
    """
    serializer = GenerateDeckSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    mode = serializer.validated_data.get("mode", "best_match")
    force_refresh = serializer.validated_data.get("force_refresh", False)

    try:
        couple = prepare_couple_for_deck(request.user)
    except DeckEligibilityError as exc:
        return Response(
            {"status": "error", "message": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not force_refresh:
        cached_deck = get_cached_deck(couple, mode)
        if cached_deck:
            logger.info(
                "🎴 [deck] Cache hit for couple=%s mode=%s — reusing deck id=%s (no Qdrant/Bedrock work)",
                couple.id, mode, cached_deck.id,
            )
            return Response(
                {"status": "success", "data": _serialize_deck(cached_deck, cached=True, exclude_swiped=True)},
                status=status.HTTP_200_OK,
            )

    # Generate the deck
    logger.info(
        "🎴 [deck] Deck requested: couple=%s mode=%s force_refresh=%s — generating fresh deck",
        couple.id, mode, force_refresh,
    )
    try:
        deck = generate_deck(couple, mode=mode)
    except ImproperlyConfigured as exc:
        logger.error("Deck generation misconfigured: %s", exc)
        return Response(
            {"status": "error", "message": "Recommendation service is not configured. Please contact support."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception:
        logger.exception("Deck generation failed: couple=%s mode=%s", couple.id, mode)
        return Response(
            {"status": "error", "message": "Failed to generate recommendations. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(
        {
            "status": "success",
            "data": _serialize_deck(deck, cached=False, include_drift=True),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_deck_view(request: Request, deck_id: str) -> Response:
    """
    Retrieve an existing recommendation deck.

    GET /api/v1/recommendations/deck/{deck_id}/

    Returns:
        Deck metadata + ordered items with name details and scores.
    """
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "No deck available. Complete onboarding first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        deck = RecommendationDeck.objects.get(id=deck_id, couple=couple)
    except RecommendationDeck.DoesNotExist:
        logger.info("Deck not found: deck_id=%s user=%s", deck_id, request.user.email)
        return Response(
            {"status": "error", "message": "Deck not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        {
            "status": "success",
            "data": _serialize_deck(deck, cached=True),
        },
        status=status.HTTP_200_OK,
    )
