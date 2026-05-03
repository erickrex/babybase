"""Integration tests for pagination on matches and shortlist endpoints."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import (
    Couple,
    CoupleStatus,
    MatchStatus,
    MutualMatch,
    Name,
    Swipe,
    SwipeAction,
)

User = get_user_model()


@pytest.fixture
def couple_with_users(db):
    """Create a couple with two users."""
    user_a = User.objects.create_user(email="pag_a@test.com", password="testpass123")
    user_b = User.objects.create_user(email="pag_b@test.com", password="testpass123")
    couple = Couple.objects.create(
        user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
    )
    return couple, user_a, user_b


@pytest.fixture
def authenticated_client(couple_with_users):
    """Create an authenticated API client for user_a."""
    couple, user_a, user_b = couple_with_users
    token, _ = Token.objects.get_or_create(user=user_a)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client, couple, user_a, user_b


@pytest.fixture
def many_matches(couple_with_users):
    """Create 25 matches for the couple to test pagination."""
    couple, user_a, user_b = couple_with_users
    matches = []
    for i in range(25):
        name = Name.objects.create(
            canonical_name=f"PagName{i:03d}",
            display_name=f"Pag Name {i}",
            gender_usage=["boy"],
            origin_backgrounds=["Spanish"],
            languages=["es", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary=f"Test name {i} for pagination.",
            active=True,
        )
        Swipe.objects.create(couple=couple, user=user_a, name=name, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=name, action=SwipeAction.LIKE)
        match = MutualMatch.objects.create(
            couple=couple,
            name=name,
            match_strength_score=0.7 + (i * 0.01),
            status=MatchStatus.ACTIVE,
        )
        matches.append(match)
    return matches


@pytest.fixture
def many_shortlisted(couple_with_users):
    """Create 25 shortlisted matches for the couple."""
    couple, user_a, user_b = couple_with_users
    matches = []
    for i in range(25):
        name = Name.objects.create(
            canonical_name=f"ShortName{i:03d}",
            display_name=f"Short Name {i}",
            gender_usage=["girl"],
            origin_backgrounds=["German"],
            languages=["de", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="medium",
            age_style_category="modern",
            historical_significance_score=0.6,
            semantic_summary=f"Test shortlisted name {i}.",
            active=True,
        )
        Swipe.objects.create(couple=couple, user=user_a, name=name, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=name, action=SwipeAction.LIKE)
        match = MutualMatch.objects.create(
            couple=couple,
            name=name,
            match_strength_score=0.8 + (i * 0.005),
            status=MatchStatus.SHORTLISTED,
        )
        matches.append(match)
    return matches


class TestMatchesPagination:
    """Integration tests for pagination on GET /api/v1/matches/."""

    def test_first_page_returns_pagination_metadata(self, authenticated_client, many_matches):
        """First page includes count, next, and previous fields."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/matches/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "count" in data
        assert "next" in data
        assert "previous" in data
        assert data["count"] == 25
        assert data["next"] is not None
        assert data["previous"] is None

    def test_default_page_size_is_20(self, authenticated_client, many_matches):
        """Default page returns 20 items."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/matches/")

        data = response.json()
        assert len(data["data"]) == 20

    def test_second_page_returns_remaining(self, authenticated_client, many_matches):
        """Second page returns remaining items with previous link."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/matches/?page=2")

        data = response.json()
        assert data["status"] == "success"
        assert len(data["data"]) == 5
        assert data["count"] == 25
        assert data["next"] is None
        assert data["previous"] is not None

    def test_custom_page_size(self, authenticated_client, many_matches):
        """Custom page_size query param controls items per page."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/matches/?page_size=10")

        data = response.json()
        assert len(data["data"]) == 10
        assert data["count"] == 25
        assert data["next"] is not None

    def test_no_matches_returns_empty_with_metadata(self, authenticated_client):
        """Empty result set still includes pagination metadata."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/matches/")

        data = response.json()
        assert data["status"] == "success"
        assert data["data"] == []
        assert data["count"] == 0
        assert data["next"] is None
        assert data["previous"] is None


class TestShortlistPagination:
    """Integration tests for pagination on GET /api/v1/shortlist/."""

    def test_first_page_returns_pagination_metadata(self, authenticated_client, many_shortlisted):
        """First page includes count, next, and previous fields."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/shortlist/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "count" in data
        assert "next" in data
        assert "previous" in data
        assert data["count"] == 25
        assert data["next"] is not None
        assert data["previous"] is None

    def test_default_page_size_is_20(self, authenticated_client, many_shortlisted):
        """Default page returns 20 items."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/shortlist/")

        data = response.json()
        assert len(data["data"]) == 20

    def test_second_page_returns_remaining(self, authenticated_client, many_shortlisted):
        """Second page returns remaining items with previous link."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/shortlist/?page=2")

        data = response.json()
        assert data["status"] == "success"
        assert len(data["data"]) == 5
        assert data["count"] == 25
        assert data["next"] is None
        assert data["previous"] is not None

    def test_custom_page_size(self, authenticated_client, many_shortlisted):
        """Custom page_size query param controls items per page."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/shortlist/?page_size=5")

        data = response.json()
        assert len(data["data"]) == 5
        assert data["count"] == 25
        assert data["next"] is not None

    def test_no_shortlisted_returns_empty_with_metadata(self, authenticated_client):
        """Empty shortlist still includes pagination metadata."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/shortlist/")

        data = response.json()
        assert data["status"] == "success"
        assert data["data"] == []
        assert data["count"] == 0
        assert data["next"] is None
        assert data["previous"] is None
