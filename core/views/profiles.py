"""Profile views for BabyBase."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.serializers.profiles import ProfileSerializer

logger = logging.getLogger(__name__)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def profile_me_view(request: Request) -> Response:
    """Get or update the current user's profile."""
    user = request.user

    if request.method == "GET":
        serializer = ProfileSerializer(user)
        return Response(
            {"status": "success", "data": serializer.data},
            status=status.HTTP_200_OK,
        )

    # PATCH
    serializer = ProfileSerializer(user, data=request.data, partial=True)
    if not serializer.is_valid():
        logger.info("Profile update failed: user=%s errors=%s", user.email, serializer.errors)
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer.save()
    logger.info("Profile updated: user=%s fields=%s", user.email, list(request.data.keys()))
    return Response(
        {"status": "success", "data": serializer.data},
        status=status.HTTP_200_OK,
    )
