"""Onboarding views for BabyBase."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.models import Couple, OnboardingResponse
from core.serializers.onboarding import OnboardingPreferencesSerializer
from core.services.couples import get_couple_for_user
from core.services.onboarding import save_preferences

logger = logging.getLogger(__name__)


def _check_gender_conflict(couple: Couple, user, incoming_gender: str) -> str | None:
    """
    Check if the incoming gender preference conflicts with the partner's choice.

    Returns an error message if boy vs girl conflict detected, None otherwise.
    """
    partner = couple.user_b if couple.user_a == user else couple.user_a
    if not partner:
        return None

    partner_onboarding = (
        OnboardingResponse.objects.filter(user=partner, couple=couple)
        .order_by("-created_at")
        .first()
    )
    if not partner_onboarding:
        return None

    partner_gender = partner_onboarding.baby_gender_preference
    if {incoming_gender, partner_gender} == {"boy", "girl"}:
        logger.warning(
            "Gender conflict: user=%s chose %s but partner=%s chose %s",
            user.email,
            incoming_gender,
            partner.email,
            partner_gender,
        )
        return (
            "Your partner selected a different baby gender. "
            "One of you chose boy and the other chose girl. "
            "Please confirm with your partner and try again."
        )

    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def onboarding_preferences_view(request: Request) -> Response:
    """Save onboarding preferences for the current user."""
    serializer = OnboardingPreferencesSerializer(data=request.data)
    if not serializer.is_valid():
        logger.info("Onboarding validation failed: user=%s errors=%s", request.user.email, serializer.errors)
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    couple = get_couple_for_user(request.user)

    # Validate gender compatibility with partner (if in a couple)
    if couple:
        incoming_gender = serializer.validated_data.get("baby_gender_preference")
        conflict_message = _check_gender_conflict(couple, request.user, incoming_gender)
        if conflict_message:
            return Response(
                {
                    "status": "error",
                    "message": conflict_message,
                    "errors": {"baby_gender_preference": ["Conflicts with partner's selection."]},
                },
                status=status.HTTP_409_CONFLICT,
            )

    response = save_preferences(request.user, couple, serializer.validated_data)

    logger.info("Onboarding completed: user=%s couple=%s", request.user.email, couple.id if couple else None)
    return Response(
        {
            "status": "success",
            "data": {
                "id": str(response.id),
                "preferred_name_backgrounds": response.preferred_name_backgrounds,
                "preferred_name_age": response.preferred_name_age,
                "baby_gender_preference": response.baby_gender_preference,
                "preferred_name_length": response.preferred_name_length,
                "historical_importance": response.historical_importance,
                "residence_country": couple.residence_country if couple else None,
            },
        },
        status=status.HTTP_201_CREATED,
    )
