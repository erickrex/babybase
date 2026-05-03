"""Couple views for BabyBase."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.serializers.couples import CoupleInviteSerializer
from core.services.couples import CoupleExistsError, create_couple, get_couple_status

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def couple_invite_view(request: Request) -> Response:
    """Invite a partner to form a couple."""
    serializer = CoupleInviteSerializer(data=request.data, context={"request": request})
    if not serializer.is_valid():
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        couple = create_couple(request.user, serializer.validated_data["partner_email"])
    except CoupleExistsError as e:
        logger.info("Couple invite rejected: user=%s reason=%s", request.user.email, str(e))
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_409_CONFLICT,
        )

    logger.info(
        "Couple created: id=%s user=%s partner=%s status=%s",
        couple.id, request.user.email, couple.invite_email, couple.status,
    )
    return Response(
        {
            "status": "success",
            "data": {
                "couple_id": str(couple.id),
                "status": couple.status,
                "partner_email": couple.invite_email,
            },
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def couple_me_view(request: Request) -> Response:
    """Get the current user's couple status, partner info, and onboarding completeness."""
    data = get_couple_status(request.user)
    return Response(
        {"status": "success", "data": data},
        status=status.HTTP_200_OK,
    )
