"""Shared test fixtures and configuration for BabyBase tests."""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def create_user(db):
    """Factory fixture for creating users."""

    def _create_user(email="test@example.com", password="testpass123", **kwargs):
        return User.objects.create_user(email=email, password=password, **kwargs)

    return _create_user
