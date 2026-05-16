"""API view regression tests for auth, couple state, and deck generation."""

import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import Couple, CoupleStatus, Name, OnboardingResponse
from core.services.couples import connect_pending_invite, create_couple

User = get_user_model()


def api_client_for(user) -> APIClient:
    """Create an authenticated API client for a user."""
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.fixture
def api_couple(db):
    """Create an active couple with complete onboarding."""
    user_a = User.objects.create_user(email="api_a@test.com", password="testpass123")
    user_b = User.objects.create_user(email="api_b@test.com", password="testpass123")
    couple = Couple.objects.create(
        user_a=user_a,
        user_b=user_b,
        status=CoupleStatus.ACTIVE,
        residence_country="DE",
    )
    OnboardingResponse.objects.create(
        user=user_a,
        couple=couple,
        preferred_name_backgrounds=["German"],
        preferred_name_age="balanced",
        baby_gender_preference="boy",
        preferred_name_length="any",
        historical_importance="medium",
    )
    OnboardingResponse.objects.create(
        user=user_b,
        couple=couple,
        preferred_name_backgrounds=["Spanish"],
        preferred_name_age="balanced",
        baby_gender_preference="boy",
        preferred_name_length="any",
        historical_importance="medium",
    )
    return couple, user_a, user_b


def _make_candidate(name: Name, score: float = 0.8) -> dict:
    """Create a mock Qdrant candidate."""
    return {
        "point_id": str(uuid.uuid4()),
        "name_id": str(name.id),
        "score": score,
        "payload": {
            "name_id": str(name.id),
            "canonical_name": name.canonical_name,
            "origin_backgrounds": name.origin_backgrounds,
            "languages": name.languages,
            "length_category": name.length_category,
            "age_style_category": name.age_style_category,
            "historical_significance_score": name.historical_significance_score,
            "gender_usage": name.gender_usage,
            "active": True,
        },
    }


class TestLogoutView:
    """Regression tests for logout token invalidation."""

    def test_logout_invalidates_current_token(self, db):
        user = User.objects.create_user(email="logout@test.com", password="testpass123")
        client = api_client_for(user)
        token = Token.objects.get(user=user)

        response = client.post("/api/v1/auth/logout/")

        assert response.status_code == 200
        assert not Token.objects.filter(key=token.key).exists()

    def test_second_logout_is_safe(self, db):
        user = User.objects.create_user(email="logout-safe@test.com", password="testpass123")
        client = api_client_for(user)

        first = client.post("/api/v1/auth/logout/")
        second = client.post("/api/v1/auth/logout/")

        assert first.status_code == 200
        assert second.status_code == 401


class TestCoupleMeView:
    """Regression tests for couple state transitions returned by /couples/me/."""

    def test_returns_pending_then_active_transition(self, db):
        user_a = User.objects.create_user(email="pending-a@test.com", password="testpass123")
        client_a = api_client_for(user_a)

        create_couple(user_a, "pending-b@test.com")

        pending_response = client_a.get("/api/v1/couples/me/")
        assert pending_response.status_code == 200
        assert pending_response.data["data"]["couple"]["status"] == CoupleStatus.PENDING
        assert pending_response.data["data"]["onboarding_complete"]["partner"] is False

        user_b = User.objects.create_user(email="pending-b@test.com", password="testpass123")
        connect_pending_invite(user_b)

        active_response = client_a.get("/api/v1/couples/me/")
        assert active_response.status_code == 200
        assert active_response.data["data"]["couple"]["status"] == CoupleStatus.ACTIVE
        assert active_response.data["data"]["partner"]["email"] == user_b.email


class TestSoloOnboardingFlow:
    """Regression tests for solo user onboarding (skipped partner invite)."""

    def test_solo_user_onboarding_complete_reported_correctly(self, db):
        """After completing onboarding without a couple, /couples/me/ reports user onboarded."""
        user = User.objects.create_user(email="solo@test.com", password="testpass123")
        client = api_client_for(user)

        # Before onboarding: user not onboarded
        response = client.get("/api/v1/couples/me/")
        assert response.status_code == 200
        assert response.data["data"]["has_couple"] is False
        assert response.data["data"]["onboarding_complete"]["user"] is False

        # Complete onboarding solo (no couple)
        OnboardingResponse.objects.create(
            user=user,
            couple=None,
            preferred_name_backgrounds=["English"],
            preferred_name_age="balanced",
            baby_gender_preference="girl",
            preferred_name_length="any",
            historical_importance="low",
        )

        # After onboarding: user IS onboarded
        response = client.get("/api/v1/couples/me/")
        assert response.status_code == 200
        assert response.data["data"]["has_couple"] is False
        assert response.data["data"]["onboarding_complete"]["user"] is True
        assert response.data["data"]["onboarding_complete"]["partner"] is False

    def test_solo_onboarding_via_preferences_endpoint(self, db):
        """POST /onboarding/preferences/ succeeds for a solo user and marks them onboarded."""
        user = User.objects.create_user(email="solo-prefs@test.com", password="testpass123")
        client = api_client_for(user)

        payload = {
            "preferred_name_backgrounds": ["Spanish", "Italian"],
            "preferred_name_age": "new",
            "baby_gender_preference": "boy",
            "preferred_name_length": "short",
            "historical_importance": "medium",
            "residence_country": "US",
        }
        response = client.post("/api/v1/onboarding/preferences/", payload, format="json")
        assert response.status_code == 201

        # Verify couple status now shows user onboarded
        status_response = client.get("/api/v1/couples/me/")
        assert status_response.data["data"]["onboarding_complete"]["user"] is True

    def test_solo_user_not_onboarded_without_response(self, db):
        """A solo user with no onboarding response is correctly reported as not onboarded."""
        user = User.objects.create_user(email="solo-new@test.com", password="testpass123")
        client = api_client_for(user)

        response = client.get("/api/v1/couples/me/")
        assert response.status_code == 200
        assert response.data["data"]["has_couple"] is False
        assert response.data["data"]["onboarding_complete"]["user"] is False


class TestGenerateDeckView:
    """Regression tests for deck generation view semantics."""

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_repeated_post_generates_fresh_deck(
        self,
        mock_embedding,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        mock_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiDeckName",
            display_name="Api Deck Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Deck regression test name.",
            active=True,
        )
        mock_search.return_value = [_make_candidate(name, 0.9)]

        first = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")
        second = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.data["data"]["id"] != second.data["data"]["id"]
        assert mock_search.call_count == 2
        assert couple.decks.count() == 2

    def test_requires_specific_partner_onboarding(self, db):
        user_a = User.objects.create_user(email="ready-a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="ready-b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a,
            user_b=user_b,
            status=CoupleStatus.ACTIVE,
            residence_country="DE",
        )
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["German"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )
        client = api_client_for(user_a)

        response = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")

        assert response.status_code == 400
        assert "Both partners must complete onboarding" in response.data["message"]
