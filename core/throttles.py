"""Custom throttle classes for BabyBase."""

import re

from rest_framework.throttling import UserRateThrottle


class FlexibleUserRateThrottle(UserRateThrottle):
    """User throttle that accepts interval strings like ``15min``."""

    _DURATION_MULTIPLIERS = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
    }

    def parse_rate(self, rate):
        """Parse DRF rates plus intervals such as ``5/15min``."""
        if rate is None:
            return (None, None)

        num_requests, period = rate.split("/")
        match = re.fullmatch(r"(?:(\d+)\s*)?([A-Za-z]+)", period.strip())
        if not match:
            raise ValueError(f"Invalid throttle rate period: {period!r}")

        quantity = int(match.group(1) or "1")
        unit = match.group(2).lower()

        try:
            duration = quantity * self._DURATION_MULTIPLIERS[unit]
        except KeyError as exc:
            raise ValueError(f"Unsupported throttle unit: {unit!r}") from exc

        return (int(num_requests), duration)


class LoginRateThrottle(FlexibleUserRateThrottle):
    """Rate limit login attempts: 5 per 15 minutes."""

    scope = "login"
    rate = "5/15min"

    def get_cache_key(self, request, view):
        """Use IP address as the cache key for unauthenticated login attempts."""
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class GeneralAPIRateThrottle(FlexibleUserRateThrottle):
    """General API rate limit: 1000 per hour."""

    scope = "general"
    rate = "1000/hour"
