"""Custom middleware for BabyBase."""

import logging
import time

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("core.middleware")


class RequestLoggingMiddleware:
    """Log every API request with method, path, status, and duration."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start = time.monotonic()

        response = self.get_response(request)

        duration_ms = (time.monotonic() - start) * 1000
        user = getattr(request, "user", None)
        user_id = str(user.id) if user and user.is_authenticated else "anon"

        # Only log API requests (skip static/admin for noise reduction)
        if request.path.startswith("/api/"):
            log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
            logger.log(
                log_level,
                "%s %s %d %.0fms user=%s",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                user_id,
            )

        return response
