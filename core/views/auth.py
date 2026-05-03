"""Authentication views for BabyBase."""

import logging

from django.contrib.auth import authenticate, get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.serializers.auth import LoginSerializer, RegisterSerializer, UserSerializer
from core.services.couples import connect_pending_invite
from core.throttles import LoginRateThrottle

User = get_user_model()
logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request: Request) -> Response:
    """Register a new user and return auth token."""
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        logger.info("Registration failed: validation errors for email=%s", request.data.get("email"))
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = serializer.save()
    token, _ = Token.objects.get_or_create(user=user)

    # Auto-connect: check for pending invites matching this email
    connect_pending_invite(user)

    logger.info("User registered: %s (id=%s)", user.email, user.id)
    return Response(
        {
            "status": "success",
            "data": {
                "user": UserSerializer(user).data,
                "token": token.key,
            },
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login_view(request: Request) -> Response:
    """Authenticate user and return auth token."""
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        logger.info("Login failed: invalid payload from IP=%s", request.META.get("REMOTE_ADDR"))
        return Response(
            {"status": "error", "message": "Validation failed.", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = serializer.validated_data["email"]
    user = authenticate(
        request=request,
        username=email,
        password=serializer.validated_data["password"],
    )

    if user is None:
        logger.warning(
            "Login failed: invalid credentials for email=%s from IP=%s",
            email,
            request.META.get("REMOTE_ADDR"),
        )
        return Response(
            {"status": "error", "message": "Invalid email or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token, _ = Token.objects.get_or_create(user=user)

    logger.info("Login successful: %s (id=%s)", user.email, user.id)
    return Response(
        {
            "status": "success",
            "data": {
                "user": UserSerializer(user).data,
                "token": token.key,
            },
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check_view(request: Request) -> Response:
    """Unauthenticated health check endpoint."""
    return Response(
        {"status": "success", "data": {"healthy": True}},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    """Invalidate the current user's auth token."""
    try:
        request.user.auth_token.delete()
        logger.info("Logout: user=%s", request.user.email)
    except Exception:
        logger.warning("Logout failed (no token): user=%s", request.user.email)

    return Response(
        {"status": "success", "message": "Logged out."},
        status=status.HTTP_200_OK,
    )
