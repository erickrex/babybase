"""Constellation (Name Map) views for BabyBase."""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.services.name_map import NameMapContextError, build_name_map


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def constellation_view(request: Request) -> Response:
    """
    Return constellation data for the 2D name map.

    GET /api/v1/constellation/

    Returns insights-first map data plus legacy dot-map fields for optional
    exploration.
    """
    try:
        data = build_name_map(request.user)
    except NameMapContextError as exc:
        return Response(
            {"status": "error", "message": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {"status": "success", "data": data},
        status=status.HTTP_200_OK,
    )
