"""Recommendation views for BabyBase."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.models import OnboardingResponse, RecommendationDeck
from core.serializers.recommendations import (
    DeckItemSerializer,
    GenerateDeckSerializer,
)
from core.services.couples import get_couple_for_user
from core.services.recommendations import generate_deck
from core.services.taste_drift import compute_taste_drift

logger = logging.getLogger(__name__)


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

    # Validate couple is active
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to generate a deck."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if couple.status != "active":
        return Response(
            {"status": "error", "message": "Your couple must be active to generate a deck."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate both partners have completed onboarding
    onboarding_count = OnboardingResponse.objects.filter(couple=couple).count()
    if onboarding_count < 2:
        return Response(
            {
                "status": "error",
                "message": "Both partners must complete onboarding before generating a deck.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    mode = serializer.validated_data.get("mode", "best_match")

    # Generate the deck
    logger.info("Generating deck: couple=%s mode=%s", couple.id, mode)
    try:
        deck = generate_deck(couple, mode=mode)
    except Exception:
        logger.exception("Deck generation failed: couple=%s mode=%s", couple.id, mode)
        return Response(
            {"status": "error", "message": "Failed to generate recommendations. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Compute taste drift insight
    drift = compute_taste_drift(couple)

    # Serialize response
    deck_items = deck.items.select_related("name").order_by("rank")
    items_data = DeckItemSerializer(deck_items, many=True).data

    response_data = {
        "id": str(deck.id),
        "mode": deck.mode,
        "created_at": deck.created_at.isoformat(),
        "expires_at": deck.expires_at.isoformat() if deck.expires_at else None,
        "items": items_data,
    }

    # Include drift insight if available
    if drift.get("summary"):
        response_data["taste_drift"] = {
            "summary": drift["summary"],
            "converging_traits": drift["converging_traits"],
        }

    return Response(
        {
            "status": "success",
            "data": response_data,
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
            {"status": "error", "message": "You must be in a couple to view decks."},
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

    deck_items = deck.items.select_related("name").order_by("rank")
    items_data = DeckItemSerializer(deck_items, many=True).data

    return Response(
        {
            "status": "success",
            "data": {
                "id": str(deck.id),
                "mode": deck.mode,
                "created_at": deck.created_at.isoformat(),
                "expires_at": deck.expires_at.isoformat() if deck.expires_at else None,
                "items": items_data,
            },
        },
        status=status.HTTP_200_OK,
    )
