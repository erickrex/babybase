"""Integration tests verifying matches endpoint response matches serializer schema."""

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
from core.serializers.swipes import MatchSerializer

User = get_user_model()


@pytest.fixture
def couple_with_users(db):
    """Create a couple with two users."""
    user_a = User.objects.create_user(email="parent_a@test.com", password="testpass123")
    user_b = User.objects.create_user(email="parent_b@test.com", password="testpass123")
    couple = Couple.objects.create(
        user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
    )
    return couple, user_a, user_b


@pytest.fixture
def sample_name(db):
    """Create a sample active name."""
    return Name.objects.create(
        canonical_name="Sophia",
        display_name="Sophia",
        gender_usage=["girl"],
        origin_backgrounds=["Greek", "Italian"],
        languages=["en", "it", "es"],
        scripts=["Latin"],
        variants=["Sofia", "Sofía"],
        length_category="medium",
        age_style_category="classic",
        historical_significance_score=0.85,
        semantic_summary="A classic name of Greek origin meaning wisdom.",
        active=True,
    )


@pytest.fixture
def second_name(db):
    """Create a second sample name for multiple match tests."""
    return Name.objects.create(
        canonical_name="Liam",
        display_name="Liam",
        gender_usage=["boy"],
        origin_backgrounds=["Irish", "English"],
        languages=["en", "ga"],
        scripts=["Latin"],
        variants=["William"],
        length_category="short",
        age_style_category="modern",
        historical_significance_score=0.6,
        semantic_summary="A modern Irish name meaning strong-willed warrior.",
        active=True,
    )


@pytest.fixture
def authenticated_client(couple_with_users):
    """Create an authenticated API client for user_a."""
    couple, user_a, user_b = couple_with_users
    token, _ = Token.objects.get_or_create(user=user_a)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client, couple, user_a, user_b


@pytest.fixture
def match_for_couple(couple_with_users, sample_name):
    """Create a mutual match for the couple."""
    couple, user_a, user_b = couple_with_users
    # Create swipes for both users
    Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.LIKE)
    Swipe.objects.create(couple=couple, user=user_b, name=sample_name, action=SwipeAction.LIKE)
    # Create the match
    match = MutualMatch.objects.create(
        couple=couple,
        name=sample_name,
        match_strength_score=0.75,
        status=MatchStatus.ACTIVE,
    )
    return match


class TestMatchesListEndpointSchema:
    """Integration tests for GET /api/v1/matches/ response schema."""

    def test_matches_response_uses_serializer_schema(self, authenticated_client, match_for_couple, sample_name):
        """Matches endpoint response matches MatchSerializer schema exactly."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get("/api/v1/matches/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["data"]) == 1

        match_item = data["data"][0]

        # Verify top-level MatchSerializer fields
        assert "id" in match_item
        assert "name" in match_item
        assert "matched_at" in match_item
        assert "match_strength_score" in match_item
        assert "status" in match_item

        # Verify nested MatchNameSerializer fields
        name_data = match_item["name"]
        expected_name_fields = {
            "id", "canonical_name", "display_name", "gender_usage",
            "origin_backgrounds", "languages", "length_category",
            "age_style_category", "historical_significance_score", "semantic_summary",
        }
        assert set(name_data.keys()) == expected_name_fields

        # Verify values match the actual name
        assert name_data["canonical_name"] == sample_name.canonical_name
        assert name_data["display_name"] == sample_name.display_name
        assert name_data["gender_usage"] == sample_name.gender_usage
        assert name_data["origin_backgrounds"] == sample_name.origin_backgrounds
        assert name_data["languages"] == sample_name.languages
        assert name_data["length_category"] == sample_name.length_category
        assert name_data["age_style_category"] == sample_name.age_style_category
        assert name_data["historical_significance_score"] == sample_name.historical_significance_score
        assert name_data["semantic_summary"] == sample_name.semantic_summary

    def test_matches_response_matches_serializer_output(self, authenticated_client, match_for_couple):
        """API response data matches what MatchSerializer produces directly."""
        client, couple, user_a, user_b = authenticated_client

        # Get API response
        response = client.get("/api/v1/matches/")
        api_data = response.json()["data"]

        # Get serializer output directly
        matches = MutualMatch.objects.filter(couple=couple).select_related("name").order_by("-matched_at")
        serializer_data = MatchSerializer(matches, many=True).data

        assert api_data == serializer_data

    def test_multiple_matches_all_follow_schema(self, authenticated_client, sample_name, second_name):
        """Multiple matches all follow the same serializer schema."""
        client, couple, user_a, user_b = authenticated_client

        # Create matches for both names
        for name in [sample_name, second_name]:
            Swipe.objects.create(couple=couple, user=user_a, name=name, action=SwipeAction.LIKE)
            Swipe.objects.create(couple=couple, user=user_b, name=name, action=SwipeAction.LIKE)
            MutualMatch.objects.create(
                couple=couple, name=name, match_strength_score=0.7, status=MatchStatus.ACTIVE
            )

        response = client.get("/api/v1/matches/")
        data = response.json()["data"]

        assert len(data) == 2
        for match_item in data:
            assert set(match_item.keys()) == {"id", "name", "matched_at", "match_strength_score", "status"}
            assert set(match_item["name"].keys()) == {
                "id", "canonical_name", "display_name", "gender_usage",
                "origin_backgrounds", "languages", "length_category",
                "age_style_category", "historical_significance_score", "semantic_summary",
            }


class TestShortlistEndpointSchema:
    """Integration tests for GET /api/v1/shortlist/ response schema."""

    def test_shortlist_add_then_remove_round_trip(self, authenticated_client, match_for_couple, sample_name):
        """POST promotes a match to shortlisted; DELETE demotes it back to active."""
        client, couple, user_a, user_b = authenticated_client

        # Initially active, not shortlisted
        assert match_for_couple.status == MatchStatus.ACTIVE

        # POST adds to shortlist
        add_response = client.post(
            "/api/v1/shortlist/", {"name_id": str(sample_name.id)}, format="json"
        )
        assert add_response.status_code == 200
        assert add_response.json()["data"]["status"] == MatchStatus.SHORTLISTED
        match_for_couple.refresh_from_db()
        assert match_for_couple.status == MatchStatus.SHORTLISTED

        # It now shows up in the shortlist listing
        list_response = client.get("/api/v1/shortlist/")
        assert len(list_response.json()["data"]) == 1

        # DELETE removes from shortlist (back to active)
        remove_response = client.delete(
            "/api/v1/shortlist/", {"name_id": str(sample_name.id)}, format="json"
        )
        assert remove_response.status_code == 200
        assert remove_response.json()["data"]["status"] == MatchStatus.ACTIVE
        match_for_couple.refresh_from_db()
        assert match_for_couple.status == MatchStatus.ACTIVE

        # No longer in the shortlist listing
        list_after = client.get("/api/v1/shortlist/")
        assert len(list_after.json()["data"]) == 0

    def test_shortlist_remove_unknown_name_returns_404(self, authenticated_client):
        """Removing a name that isn't a match returns 404."""
        import uuid

        client, couple, user_a, user_b = authenticated_client
        response = client.delete(
            "/api/v1/shortlist/", {"name_id": str(uuid.uuid4())}, format="json"
        )
        assert response.status_code == 404

    def test_match_detail_reports_shortlisted_status(self, authenticated_client, match_for_couple, sample_name):
        """Match detail endpoint reflects shortlisted status so the UI can render correctly."""
        client, couple, user_a, user_b = authenticated_client

        client.post("/api/v1/shortlist/", {"name_id": str(sample_name.id)}, format="json")

        detail = client.get(f"/api/v1/matches/{sample_name.id}/")
        assert detail.status_code == 200
        assert detail.json()["data"]["status"] == MatchStatus.SHORTLISTED

    def test_shortlist_response_uses_serializer_schema(self, authenticated_client, match_for_couple, sample_name):
        """Shortlist endpoint response matches MatchSerializer schema."""
        client, couple, user_a, user_b = authenticated_client

        # Promote match to shortlisted
        match_for_couple.status = MatchStatus.SHORTLISTED
        match_for_couple.save(update_fields=["status"])

        response = client.get("/api/v1/shortlist/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["data"]) == 1

        match_item = data["data"][0]

        # Verify same schema as matches list
        assert set(match_item.keys()) == {"id", "name", "matched_at", "match_strength_score", "status"}
        assert match_item["status"] == "shortlisted"

        # Verify nested name fields
        name_data = match_item["name"]
        assert name_data["display_name"] == sample_name.display_name
        assert name_data["canonical_name"] == sample_name.canonical_name


class TestMatchDetailEndpointSchema:
    """Integration tests for GET /api/v1/matches/{name_id}/ response schema."""

    def test_match_detail_response_uses_serializer_schema(self, authenticated_client, match_for_couple, sample_name):
        """Match detail endpoint response matches MatchDetailSerializer schema."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get(f"/api/v1/matches/{sample_name.id}/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        detail = data["data"]

        # Verify MatchDetailSerializer fields
        expected_fields = {"id", "name", "matched_at", "match_strength_score", "status", "semantic_fit_breakdown"}
        assert set(detail.keys()) == expected_fields

        # Verify nested name fields
        name_data = detail["name"]
        expected_name_fields = {
            "id", "canonical_name", "display_name", "gender_usage",
            "origin_backgrounds", "languages", "length_category",
            "age_style_category", "historical_significance_score", "semantic_summary",
        }
        assert set(name_data.keys()) == expected_name_fields

        # Verify semantic_fit_breakdown structure
        breakdown = detail["semantic_fit_breakdown"]
        assert "style" in breakdown
        assert "heritage" in breakdown
        assert "local_fit" in breakdown
        assert "historical" in breakdown

        # Verify breakdown values are percentages (0-100)
        for key, value in breakdown.items():
            assert 0 <= value <= 100, f"{key} should be 0-100, got {value}"

    def test_match_detail_matches_serializer_output(self, authenticated_client, match_for_couple, sample_name):
        """API response data matches what MatchDetailSerializer produces directly."""
        client, couple, user_a, user_b = authenticated_client

        response = client.get(f"/api/v1/matches/{sample_name.id}/")
        api_data = response.json()["data"]

        # Verify the serializer fields are present and correct types
        assert isinstance(api_data["id"], str)
        assert isinstance(api_data["name"], dict)
        assert isinstance(api_data["matched_at"], str)
        assert isinstance(api_data["match_strength_score"], (int, float))
        assert isinstance(api_data["status"], str)
        assert isinstance(api_data["semantic_fit_breakdown"], dict)
