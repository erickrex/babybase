"""API view regression tests for auth, couple state, and deck generation."""

import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import (
    Couple,
    CoupleStatus,
    MatchStatus,
    MutualMatch,
    Name,
    OnboardingResponse,
    RecommendationDeck,
    Swipe,
    SwipeAction,
)
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


class TestGenderConflictValidation:
    """Regression tests for boy/girl gender conflict detection during onboarding."""

    def test_boy_girl_conflict_returns_409(self, db):
        """Second parent choosing boy when first chose girl gets a 409 conflict."""
        user_a = User.objects.create_user(email="gender-a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="gender-b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE, residence_country="US"
        )
        # First parent onboards with "girl"
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["English"],
            preferred_name_age="balanced",
            baby_gender_preference="girl",
            preferred_name_length="any",
            historical_importance="medium",
        )

        # Second parent tries to onboard with "boy" — conflict
        client_b = api_client_for(user_b)
        payload = {
            "preferred_name_backgrounds": ["Spanish"],
            "preferred_name_age": "new",
            "baby_gender_preference": "boy",
            "preferred_name_length": "short",
            "historical_importance": "low",
            "residence_country": "US",
        }
        response = client_b.post("/api/v1/onboarding/preferences/", payload, format="json")

        assert response.status_code == 409
        assert "different baby gender" in response.data["message"]
        assert "baby_gender_preference" in response.data["errors"]

    def test_boy_nonbinary_no_conflict(self, db):
        """One parent choosing boy and the other non_binary is allowed (mixed deck)."""
        user_a = User.objects.create_user(email="mix-a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="mix-b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE, residence_country="DE"
        )
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["German"],
            preferred_name_age="old",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="high",
        )

        client_b = api_client_for(user_b)
        payload = {
            "preferred_name_backgrounds": ["Italian"],
            "preferred_name_age": "balanced",
            "baby_gender_preference": "non_binary",
            "preferred_name_length": "long",
            "historical_importance": "medium",
            "residence_country": "DE",
        }
        response = client_b.post("/api/v1/onboarding/preferences/", payload, format="json")

        assert response.status_code == 201

    def test_same_gender_no_conflict(self, db):
        """Both parents choosing the same gender is fine."""
        user_a = User.objects.create_user(email="same-a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="same-b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE, residence_country="MX"
        )
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["Spanish"],
            preferred_name_age="balanced",
            baby_gender_preference="girl",
            preferred_name_length="any",
            historical_importance="medium",
        )

        client_b = api_client_for(user_b)
        payload = {
            "preferred_name_backgrounds": ["Spanish"],
            "preferred_name_age": "new",
            "baby_gender_preference": "girl",
            "preferred_name_length": "short",
            "historical_importance": "low",
            "residence_country": "MX",
        }
        response = client_b.post("/api/v1/onboarding/preferences/", payload, format="json")

        assert response.status_code == 201


class TestAuthViews:
    """Regression tests for auth input normalization and password validation."""

    def test_login_normalizes_email_case(self, db):
        User.objects.create_user(email="mixed@test.com", password="StrongerPass123")
        client = APIClient()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "MIXED@Test.com", "password": "StrongerPass123"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["data"]["user"]["email"] == "mixed@test.com"

    def test_register_captures_first_and_last_name(self, db):
        """Registration stores first/last name and returns them in the user payload."""
        client = APIClient()

        response = client.post(
            "/api/v1/auth/register/",
            {
                "email": "named@test.com",
                "password": "StrongerPass123",
                "password_confirm": "StrongerPass123",
                "first_name": "Alex",
                "last_name": "Rivera",
            },
            format="json",
        )

        assert response.status_code == 201
        user_data = response.data["data"]["user"]
        assert user_data["first_name"] == "Alex"
        assert user_data["last_name"] == "Rivera"

        user = User.objects.get(email="named@test.com")
        assert user.first_name == "Alex"
        assert user.last_name == "Rivera"

    def test_register_without_names_still_succeeds(self, db):
        """First/last name are optional at the API level; registration still works."""
        client = APIClient()

        response = client.post(
            "/api/v1/auth/register/",
            {
                "email": "noname@test.com",
                "password": "StrongerPass123",
                "password_confirm": "StrongerPass123",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.data["data"]["user"]["first_name"] == ""

    @pytest.mark.skip(reason="AUTH_PASSWORD_VALIDATORS disabled in dev; re-enable when validators are restored")
    def test_register_rejects_common_password(self, db):
        client = APIClient()

        response = client.post(
            "/api/v1/auth/register/",
            {"email": "common-password@test.com", "password": "password", "password_confirm": "password"},
            format="json",
        )

        assert response.status_code == 400
        assert "password" in response.data["errors"]

    @pytest.mark.skip(reason="AUTH_PASSWORD_VALIDATORS disabled in dev; re-enable when validators are restored")
    def test_register_rejects_numeric_password(self, db):
        client = APIClient()

        response = client.post(
            "/api/v1/auth/register/",
            {"email": "numeric-password@test.com", "password": "12345678", "password_confirm": "12345678"},
            format="json",
        )

        assert response.status_code == 400
        assert "password" in response.data["errors"]

    @pytest.mark.skip(reason="AUTH_PASSWORD_VALIDATORS disabled in dev; re-enable when validators are restored")
    def test_register_rejects_email_similar_password(self, db):
        client = APIClient()

        response = client.post(
            "/api/v1/auth/register/",
            {
                "email": "similarpassword@test.com",
                "password": "similarpassword",
                "password_confirm": "similarpassword",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "password" in response.data["errors"]


class TestGenerateDeckView:
    """Regression tests for deck generation view semantics."""

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_repeated_post_reuses_unexpired_deck(
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
        assert second.status_code == 200
        assert first.data["data"]["cached"] is False
        assert second.data["data"]["cached"] is True
        assert first.data["data"]["id"] == second.data["data"]["id"]
        assert mock_search.call_count == 1
        assert couple.decks.count() == 1

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_force_refresh_generates_fresh_deck(
        self,
        mock_embedding,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        mock_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiRefreshDeckName",
            display_name="Api Refresh Deck Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Deck refresh regression test name.",
            active=True,
        )
        mock_search.return_value = [_make_candidate(name, 0.9)]

        first = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")
        second = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "best_match", "force_refresh": True},
            format="json",
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.data["data"]["cached"] is False
        assert second.data["data"]["cached"] is False
        assert first.data["data"]["id"] != second.data["data"]["id"]
        assert mock_search.call_count == 2
        assert couple.decks.count() == 2

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_expired_deck_generates_fresh_deck(
        self,
        mock_embedding,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        expired_deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        mock_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiExpiredDeckName",
            display_name="Api Expired Deck Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Expired deck regression test name.",
            active=True,
        )
        mock_search.return_value = [_make_candidate(name, 0.9)]

        response = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")

        assert response.status_code == 201
        assert response.data["data"]["cached"] is False
        assert response.data["data"]["id"] != str(expired_deck.id)
        assert mock_search.call_count == 1

    def test_cached_deck_response_excludes_swiped_items(self, api_couple):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        swiped_name = Name.objects.create(
            canonical_name="ApiCachedSwipedName",
            display_name="Api Cached Swiped Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Already swiped cached deck test name.",
            active=True,
        )
        remaining_name = Name.objects.create(
            canonical_name="ApiCachedRemainingName",
            display_name="Api Cached Remaining Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Remaining cached deck test name.",
            active=True,
        )
        deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
        deck.items.create(name=swiped_name, rank=1)
        deck.items.create(name=remaining_name, rank=2)
        Swipe.objects.create(couple=couple, user=user_a, name=swiped_name, action=SwipeAction.LIKE)

        response = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")

        assert response.status_code == 200
        assert response.data["data"]["cached"] is True
        assert [item["name"]["display_name"] for item in response.data["data"]["items"]] == [
            "Api Cached Remaining Name"
        ]

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

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_solo_user_can_generate_deck(self, mock_embedding, mock_search, db):
        """A solo user who completed onboarding can generate a deck without a partner."""
        user = User.objects.create_user(email="solo-deck@test.com", password="testpass123")
        client = api_client_for(user)

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

        mock_embedding.return_value = [0.1] * 1024
        name = Name.objects.create(
            canonical_name="SoloDeckName",
            display_name="Solo Deck Name",
            gender_usage=["girl"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Solo deck test name.",
            active=True,
        )
        mock_search.return_value = [_make_candidate(name, 0.85)]

        response = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")

        assert response.status_code == 201
        assert response.data["data"]["items"][0]["name"]["display_name"] == "Solo Deck Name"
        # Verify a solo couple was created
        assert Couple.objects.filter(user_a=user, user_b=None, status=CoupleStatus.ACTIVE).exists()

    def test_solo_user_without_onboarding_cannot_generate_deck(self, db):
        """A solo user who has NOT completed onboarding gets a 400."""
        user = User.objects.create_user(email="solo-no-onboard@test.com", password="testpass123")
        client = api_client_for(user)

        response = client.post("/api/v1/recommendations/deck/", {"mode": "best_match"}, format="json")

        assert response.status_code == 400
        assert "complete onboarding" in response.data["message"]


class TestCrossCulturalDeckView:
    """Regression tests for cross-cultural deck mode caching and contract semantics."""

    @patch("core.services.recommendations.search_names")
    @patch("core.services.onboarding._get_liked_cross_cultural_vectors")
    @patch("core.services.embeddings.generate_embedding")
    def test_cross_cultural_first_call_201_then_cached_200(
        self,
        mock_generate_embedding,
        mock_liked_vectors,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        # Force the fallback embedding path (no mutual cross_cultural likes) and
        # keep the embedding fully mocked so no Bedrock/Qdrant calls are made.
        mock_liked_vectors.return_value = []
        mock_generate_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiCrossCulturalName",
            display_name="Api Cross Cultural Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en", "es", "fr", "it"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Cross-cultural deck regression test name.",
            active=True,
        )
        candidate = _make_candidate(name, 0.9)
        candidate["payload"]["international_score"] = 1.0
        mock_search.return_value = [candidate]

        first = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "cross_cultural"},
            format="json",
        )
        second = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "cross_cultural"},
            format="json",
        )

        assert first.status_code == 201
        assert first.data["status"] == "success"
        assert first.data["data"]["cached"] is False
        assert second.status_code == 200
        assert second.data["status"] == "success"
        assert second.data["data"]["cached"] is True
        assert first.data["data"]["id"] == second.data["data"]["id"]
        assert mock_search.call_count == 1
        assert couple.decks.count() == 1

    @patch("core.services.recommendations.search_names")
    @patch("core.services.onboarding._get_liked_cross_cultural_vectors")
    @patch("core.services.embeddings.generate_embedding")
    def test_cross_cultural_force_refresh_regenerates(
        self,
        mock_generate_embedding,
        mock_liked_vectors,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        mock_liked_vectors.return_value = []
        mock_generate_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiCrossCulturalRefreshName",
            display_name="Api Cross Cultural Refresh Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en", "es", "fr", "it"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Cross-cultural force-refresh regression test name.",
            active=True,
        )
        candidate = _make_candidate(name, 0.9)
        candidate["payload"]["international_score"] = 1.0
        mock_search.return_value = [candidate]

        first = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "cross_cultural"},
            format="json",
        )
        second = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "cross_cultural", "force_refresh": True},
            format="json",
        )

        assert first.status_code == 201
        assert first.data["data"]["cached"] is False
        assert second.status_code == 201
        assert second.data["status"] == "success"
        assert second.data["data"]["cached"] is False
        assert first.data["data"]["id"] != second.data["data"]["id"]
        assert mock_search.call_count == 2
        assert couple.decks.count() == 2


class TestSimilarNamesView:
    """Regression tests for match-scoped semantic similar-name lookups."""

    def _make_name(self, canonical_name: str = "Aiden") -> Name:
        return Name.objects.create(
            canonical_name=canonical_name,
            display_name=canonical_name,
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Similar-name anchor.",
            active=True,
        )

    def _make_match(self, couple, user_a, user_b, name: Name) -> None:
        Swipe.objects.create(couple=couple, user=user_a, name=name, action=SwipeAction.LIKE)
        if user_b is not None:
            Swipe.objects.create(couple=couple, user=user_b, name=name, action=SwipeAction.LIKE)
        MutualMatch.objects.create(
            couple=couple,
            name=name,
            match_strength_score=0.75,
            status=MatchStatus.ACTIVE,
        )

    @patch("core.views.swipes.get_similar_names")
    def test_existing_unmatched_name_returns_404(self, mock_similar, api_couple):
        """A known name cannot anchor similar results until it is a mutual match."""
        _, user_a, _ = api_couple
        client = api_client_for(user_a)
        unmatched = self._make_name()

        response = client.get(f"/api/v1/matches/{unmatched.id}/similar/")

        assert response.status_code == 404
        assert response.data["status"] == "error"
        assert response.data["message"] == "Match not found."
        mock_similar.assert_not_called()

    @patch("core.views.swipes.get_similar_names")
    def test_matched_name_calls_service(self, mock_similar, api_couple):
        """A current couple match can anchor similar-name search."""
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)
        anchor = self._make_name()
        similar = self._make_name("Braden")
        self._make_match(couple, user_a, user_b, anchor)
        mock_similar.return_value = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(similar.id),
                "canonical_name": similar.canonical_name,
                "score": 0.91,
                "payload": {
                    "origin_backgrounds": similar.origin_backgrounds,
                    "gender_usage": similar.gender_usage,
                    "length_category": similar.length_category,
                    "age_style_category": similar.age_style_category,
                },
            }
        ]

        response = client.get(f"/api/v1/matches/{anchor.id}/similar/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"][0]["name_id"] == str(similar.id)
        mock_similar.assert_called_once_with(str(anchor.id), couple)


class TestSoundsLikeView:
    """Regression tests for the GET /matches/<name_id>/sounds-like/ endpoint.

    The Qdrant-backed service is mocked at the view boundary
    (``core.views.swipes.get_sounds_like_names``) so these tests verify the
    HTTP contract — the success envelope and its serialized shape, the
    not-in-a-couple 400, and the missing-name 404 — without touching Qdrant.
    """

    def _make_name(self) -> Name:
        """Persist an active anchor name for sounds-like lookups."""
        return Name.objects.create(
            canonical_name="Aiden",
            display_name="Aiden",
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Sounds-like anchor name.",
            active=True,
        )

    def _sounds_like_result(self, name: Name, score: float = 0.92) -> dict:
        """A result dict shaped like a Qdrant hit consumed by SoundsLikeNameSerializer."""
        return {
            "point_id": str(uuid.uuid4()),
            "name_id": str(name.id),
            "canonical_name": name.canonical_name,
            "score": score,
            "payload": {
                "name_id": str(name.id),
                "canonical_name": name.canonical_name,
                "origin_backgrounds": name.origin_backgrounds,
                "gender_usage": name.gender_usage,
                "length_category": name.length_category,
                "age_style_category": name.age_style_category,
                "active": True,
            },
        }

    def _make_match(self, couple, user_a, user_b, name: Name) -> MutualMatch:
        """Persist a mutual match so match-scoped recommendation endpoints can use it."""
        Swipe.objects.create(couple=couple, user=user_a, name=name, action=SwipeAction.LIKE)
        if user_b is not None:
            Swipe.objects.create(couple=couple, user=user_b, name=name, action=SwipeAction.LIKE)
        return MutualMatch.objects.create(
            couple=couple,
            name=name,
            match_strength_score=0.75,
            status=MatchStatus.ACTIVE,
        )

    @patch("core.views.swipes.get_sounds_like_names")
    def test_returns_success_envelope_with_serialized_data(self, mock_sounds_like, api_couple):
        """A valid request returns 200 with {"status":"success","data":[...]}."""
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)

        anchor = self._make_name()
        self._make_match(couple, user_a, user_b, anchor)
        similar = Name.objects.create(
            canonical_name="Braden",
            display_name="Braden",
            gender_usage=["boy"],
            origin_backgrounds=["English", "Irish"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="modern",
            historical_significance_score=0.4,
            semantic_summary="A similar-sounding name.",
            active=True,
        )
        mock_sounds_like.return_value = [self._sounds_like_result(similar, 0.91)]

        response = client.get(f"/api/v1/matches/{anchor.id}/sounds-like/")

        assert response.status_code == 200
        assert response.data["status"] == "success"

        data = response.data["data"]
        assert len(data) == 1
        result = data[0]
        assert result["name_id"] == str(similar.id)
        assert result["canonical_name"] == "Braden"
        assert result["score"] == 0.91
        assert result["origin_backgrounds"] == ["English", "Irish"]
        assert result["gender_usage"] == ["boy"]
        assert result["length_category"] == "short"
        assert result["age_style_category"] == "modern"

        # The service was anchored on the requested name.
        mock_sounds_like.assert_called_once()
        assert mock_sounds_like.call_args.args[0] == str(anchor.id)
        assert mock_sounds_like.call_args.args[1] == couple

    @patch("core.views.swipes.get_sounds_like_names")
    def test_empty_results_still_success_envelope(self, mock_sounds_like, api_couple):
        """An empty service result (e.g. Qdrant down) still returns a 200 success envelope."""
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)
        anchor = self._make_name()
        self._make_match(couple, user_a, user_b, anchor)
        mock_sounds_like.return_value = []

        response = client.get(f"/api/v1/matches/{anchor.id}/sounds-like/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"] == []

    @patch("core.views.swipes.get_sounds_like_names")
    def test_not_in_couple_returns_400(self, mock_sounds_like, db):
        """A user with no couple gets a 400 error envelope and the service is not called."""
        user = User.objects.create_user(email="no-couple@test.com", password="testpass123")
        client = api_client_for(user)
        anchor = self._make_name()

        response = client.get(f"/api/v1/matches/{anchor.id}/sounds-like/")

        assert response.status_code == 400
        assert response.data["status"] == "error"
        assert "message" in response.data
        mock_sounds_like.assert_not_called()

    @patch("core.views.swipes.get_sounds_like_names")
    def test_missing_name_returns_404(self, mock_sounds_like, api_couple):
        """A request for a non-existent match gets a 404 error envelope; service not called."""
        _, user_a, _ = api_couple
        client = api_client_for(user_a)

        missing_name_id = uuid.uuid4()
        response = client.get(f"/api/v1/matches/{missing_name_id}/sounds-like/")

        assert response.status_code == 404
        assert response.data["status"] == "error"
        assert "message" in response.data
        mock_sounds_like.assert_not_called()

    @patch("core.views.swipes.get_sounds_like_names")
    def test_existing_unmatched_name_returns_404(self, mock_sounds_like, api_couple):
        """A known name cannot anchor sounds-like results until it is a mutual match."""
        _, user_a, _ = api_couple
        client = api_client_for(user_a)
        unmatched = self._make_name()

        response = client.get(f"/api/v1/matches/{unmatched.id}/sounds-like/")

        assert response.status_code == 404
        assert response.data["status"] == "error"
        assert response.data["message"] == "Match not found."
        mock_sounds_like.assert_not_called()

    @patch("core.serializers.swipes.presign_audio_url")
    @patch("core.views.swipes.get_sounds_like_names")
    def test_audio_url_present_when_audio_stored(self, mock_sounds_like, mock_presign, api_couple):
        """A result name with stored audio serializes ``audio_url`` to the presigned URL.

        The serializer resolves the result's ``name_id`` to a persisted ``Name``
        and presigns its stored audio; the presign is mocked to a sentinel so no
        S3 call is made and the response stays in the success envelope (Req 7.1, 7.3).
        """
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)
        anchor = self._make_name()
        self._make_match(couple, user_a, user_b, anchor)

        with_audio = Name.objects.create(
            canonical_name="Caden",
            display_name="Caden",
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="modern",
            historical_significance_score=0.4,
            semantic_summary="A similar-sounding name with audio.",
            active=True,
            pronunciation_audio={
                "bucket": "babybase-audio-test",
                "key": f"pronunciations/{uuid.uuid4()}.mp3",
                "voice": "Joanna",
                "content_type": "audio/mpeg",
            },
        )
        sentinel_url = "https://signed.example.com/pronunciations/caden.mp3?sig=abc"
        mock_presign.return_value = sentinel_url
        mock_sounds_like.return_value = [self._sounds_like_result(with_audio, 0.9)]

        response = client.get(f"/api/v1/matches/{anchor.id}/sounds-like/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        result = response.data["data"][0]
        assert result["audio_url"] == sentinel_url
        # The presigned URL was resolved from the persisted result Name.
        mock_presign.assert_called_once()
        presigned_name = mock_presign.call_args.args[0]
        assert str(presigned_name.id) == str(with_audio.id)

    @patch("core.views.swipes.get_sounds_like_names")
    def test_audio_url_null_when_no_audio(self, mock_sounds_like, api_couple):
        """A result name with empty ``pronunciation_audio`` serializes ``audio_url`` as null.

        The real ``presign_audio_url`` returns ``None`` for an empty reference
        without touching S3, and the response stays in the success envelope
        (Req 7.2, 7.3).
        """
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)
        anchor = self._make_name()
        self._make_match(couple, user_a, user_b, anchor)

        no_audio = Name.objects.create(
            canonical_name="Daxton",
            display_name="Daxton",
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="modern",
            historical_significance_score=0.4,
            semantic_summary="A similar-sounding name without audio.",
            active=True,
        )
        mock_sounds_like.return_value = [self._sounds_like_result(no_audio, 0.88)]

        response = client.get(f"/api/v1/matches/{anchor.id}/sounds-like/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        result = response.data["data"][0]
        assert result["audio_url"] is None


class TestMatchDetailAudioField:
    """Regression tests for ``audio_url`` on GET /matches/<name_id>/ (match detail).

    ``MatchDetailSerializer`` presigns the audio of the match's underlying
    ``Name``. The presign is mocked to a sentinel for the "audio present" case so
    no S3 call is made; the "no audio" case lets the real presign return ``None``
    for an empty reference without touching S3 (Req 7.1, 7.2, 7.3).
    """

    def _matched_name(self, *, pronunciation_audio: dict | None = None) -> Name:
        """Persist an active name for use as a mutual-match anchor."""
        return Name.objects.create(
            canonical_name="Aiden",
            display_name="Aiden",
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Matched name for audio detail.",
            active=True,
            pronunciation_audio=pronunciation_audio if pronunciation_audio is not None else {},
        )

    def _make_match(self, couple, user_a, user_b, name: Name) -> MutualMatch:
        """Create a mutual match for ``name`` mirroring existing match fixtures."""
        Swipe.objects.create(couple=couple, user=user_a, name=name, action=SwipeAction.LIKE)
        if user_b is not None:
            Swipe.objects.create(couple=couple, user=user_b, name=name, action=SwipeAction.LIKE)
        return MutualMatch.objects.create(
            couple=couple,
            name=name,
            match_strength_score=0.75,
            status=MatchStatus.ACTIVE,
        )

    @patch("core.serializers.swipes.presign_audio_url")
    def test_audio_url_present_when_audio_stored(self, mock_presign, api_couple):
        """A matched name with stored audio returns the presigned ``audio_url``."""
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)

        name = self._matched_name(
            pronunciation_audio={
                "bucket": "babybase-audio-test",
                "key": f"pronunciations/{uuid.uuid4()}.mp3",
                "voice": "Joanna",
                "content_type": "audio/mpeg",
            }
        )
        self._make_match(couple, user_a, user_b, name)

        sentinel_url = "https://signed.example.com/pronunciations/aiden.mp3?sig=xyz"
        mock_presign.return_value = sentinel_url

        response = client.get(f"/api/v1/matches/{name.id}/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"]["audio_url"] == sentinel_url
        mock_presign.assert_called_once()
        presigned_name = mock_presign.call_args.args[0]
        assert str(presigned_name.id) == str(name.id)

    def test_audio_url_null_when_no_audio(self, api_couple):
        """A matched name with empty ``pronunciation_audio`` returns ``audio_url`` null."""
        couple, user_a, user_b = api_couple
        client = api_client_for(user_a)

        name = self._matched_name()
        self._make_match(couple, user_a, user_b, name)

        response = client.get(f"/api/v1/matches/{name.id}/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["data"]["audio_url"] is None


class TestSoundsLikeDeckView:
    """Regression tests for the optional sounds_like deck mode caching/contract semantics.

    Mirrors ``TestCrossCulturalDeckView`` but routes through the phonetic_style
    vector. The mutual-likes path is forced into its fallback by returning ``[]``
    from ``_get_liked_phonetic_vectors``, and ``generate_embedding`` is mocked so
    no Bedrock/Qdrant calls are made.
    """

    @patch("core.services.recommendations.search_names")
    @patch("core.services.onboarding._get_liked_phonetic_vectors")
    @patch("core.services.embeddings.generate_embedding")
    def test_sounds_like_first_call_201_then_cached_200(
        self,
        mock_generate_embedding,
        mock_liked_vectors,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        # Force the fallback embedding path (no mutual phonetic likes) and keep the
        # embedding fully mocked so no Bedrock/Qdrant calls are made.
        mock_liked_vectors.return_value = []
        mock_generate_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiSoundsLikeName",
            display_name="Api Sounds Like Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Sounds-like deck regression test name.",
            active=True,
        )
        mock_search.return_value = [_make_candidate(name, 0.9)]

        first = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "sounds_like"},
            format="json",
        )
        second = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "sounds_like"},
            format="json",
        )

        assert first.status_code == 201
        assert first.data["status"] == "success"
        assert first.data["data"]["cached"] is False
        assert second.status_code == 200
        assert second.data["status"] == "success"
        assert second.data["data"]["cached"] is True
        assert first.data["data"]["id"] == second.data["data"]["id"]
        assert mock_search.call_count == 1
        assert couple.decks.count() == 1

    @patch("core.services.recommendations.search_names")
    @patch("core.services.onboarding._get_liked_phonetic_vectors")
    @patch("core.services.embeddings.generate_embedding")
    def test_sounds_like_force_refresh_regenerates(
        self,
        mock_generate_embedding,
        mock_liked_vectors,
        mock_search,
        api_couple,
    ):
        couple, user_a, _ = api_couple
        client = api_client_for(user_a)
        mock_liked_vectors.return_value = []
        mock_generate_embedding.return_value = [0.1] * 1024

        name = Name.objects.create(
            canonical_name="ApiSoundsLikeRefreshName",
            display_name="Api Sounds Like Refresh Name",
            gender_usage=["boy"],
            origin_backgrounds=["German"],
            languages=["de", "en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Sounds-like force-refresh regression test name.",
            active=True,
        )
        mock_search.return_value = [_make_candidate(name, 0.9)]

        first = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "sounds_like"},
            format="json",
        )
        second = client.post(
            "/api/v1/recommendations/deck/",
            {"mode": "sounds_like", "force_refresh": True},
            format="json",
        )

        assert first.status_code == 201
        assert first.data["data"]["cached"] is False
        assert second.status_code == 201
        assert second.data["status"] == "success"
        assert second.data["data"]["cached"] is False
        assert first.data["data"]["id"] != second.data["data"]["id"]
        assert mock_search.call_count == 2
        assert couple.decks.count() == 2
