"""Unit tests for swipe and match service."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import (
    Couple,
    CoupleStatus,
    MatchStatus,
    Name,
    RecommendationDeck,
    RecommendationDeckItem,
    Swipe,
    SwipeAction,
)
from core.services.swipes import (
    SwipeValidationError,
    check_mutual_match,
    create_match,
    record_swipe,
    validate_source_deck,
    validate_swipe,
)

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
        canonical_name="TestName",
        display_name="Test Name",
        gender_usage=["boy"],
        origin_backgrounds=["Spanish", "Greek"],
        languages=["es", "en"],
        scripts=["Latin"],
        variants=["TestName"],
        length_category="short",
        age_style_category="classic",
        historical_significance_score=0.7,
        semantic_summary="A classic test name.",
        active=True,
    )


@pytest.fixture
def inactive_name(db):
    """Create an inactive name."""
    return Name.objects.create(
        canonical_name="InactiveName",
        display_name="Inactive Name",
        gender_usage=["girl"],
        origin_backgrounds=["Russian"],
        languages=["ru"],
        scripts=["Cyrillic"],
        variants=[],
        length_category="medium",
        age_style_category="timeless",
        historical_significance_score=0.3,
        semantic_summary="An inactive name.",
        active=False,
    )


class TestValidateSwipe:
    """Tests for validate_swipe function."""

    def test_valid_swipe(self, couple_with_users, sample_name):
        """Valid swipe passes validation and returns the name."""
        couple, user_a, _ = couple_with_users
        result = validate_swipe(user_a, couple, str(sample_name.id))
        assert result == sample_name

    def test_user_not_in_couple(self, couple_with_users, sample_name, db):
        """User not in the couple is rejected."""
        couple, _, _ = couple_with_users
        outsider = User.objects.create_user(email="outsider@test.com", password="testpass123")

        with pytest.raises(SwipeValidationError, match="not a member"):
            validate_swipe(outsider, couple, str(sample_name.id))

    def test_name_not_found(self, couple_with_users):
        """Non-existent name ID is rejected."""
        couple, user_a, _ = couple_with_users
        import uuid

        fake_id = str(uuid.uuid4())
        with pytest.raises(SwipeValidationError, match="not found"):
            validate_swipe(user_a, couple, fake_id)

    def test_inactive_name_rejected(self, couple_with_users, inactive_name):
        """Inactive name is rejected."""
        couple, user_a, _ = couple_with_users

        with pytest.raises(SwipeValidationError, match="no longer active"):
            validate_swipe(user_a, couple, str(inactive_name.id))


class TestRecordSwipe:
    """Tests for record_swipe function."""

    def test_normal_swipe_created(self, couple_with_users, sample_name):
        """Normal swipe creates a new record."""
        couple, user_a, _ = couple_with_users
        swipe, created = record_swipe(user_a, couple, str(sample_name.id), "like")

        assert created is True
        assert swipe.user == user_a
        assert swipe.couple == couple
        assert swipe.name == sample_name
        assert swipe.action == SwipeAction.LIKE

    def test_duplicate_swipe_returns_existing(self, couple_with_users, sample_name):
        """Duplicate swipe returns existing record without error."""
        couple, user_a, _ = couple_with_users

        swipe1, created1 = record_swipe(user_a, couple, str(sample_name.id), "like")
        swipe2, created2 = record_swipe(user_a, couple, str(sample_name.id), "dislike")

        assert created1 is True
        assert created2 is False
        assert swipe1.id == swipe2.id
        # Original action is preserved
        assert swipe2.action == SwipeAction.LIKE

    def test_different_users_can_swipe_same_name(self, couple_with_users, sample_name):
        """Both parents can swipe on the same name independently."""
        couple, user_a, user_b = couple_with_users

        swipe_a, created_a = record_swipe(user_a, couple, str(sample_name.id), "like")
        swipe_b, created_b = record_swipe(user_b, couple, str(sample_name.id), "like")

        assert created_a is True
        assert created_b is True
        assert swipe_a.id != swipe_b.id

    def test_swipe_with_source_deck(self, couple_with_users, sample_name):
        """Swipe can store a source deck after provenance validation."""
        couple, user_a, _ = couple_with_users
        deck = RecommendationDeck.objects.create(couple=couple, mode="best_match")
        RecommendationDeckItem.objects.create(deck=deck, name=sample_name, rank=1)

        source_deck = validate_source_deck(couple, str(sample_name.id), str(deck.id))
        swipe, created = record_swipe(user_a, couple, str(sample_name.id), "maybe", source_deck=source_deck)

        assert created is True
        assert swipe.source_deck == deck

    def test_invalid_deck_id_rejected(self, couple_with_users, sample_name):
        """A provided deck_id must resolve to the couple and name."""
        couple, _, _ = couple_with_users
        import uuid

        with pytest.raises(SwipeValidationError, match="Deck not found"):
            validate_source_deck(couple, str(sample_name.id), str(uuid.uuid4()))

    def test_deck_from_other_couple_rejected(self, couple_with_users, sample_name, db):
        """A deck from another couple cannot be used as swipe provenance."""
        couple, _, _ = couple_with_users
        other_a = User.objects.create_user(email="other-a@test.com", password="testpass123")
        other_b = User.objects.create_user(email="other-b@test.com", password="testpass123")
        other_couple = Couple.objects.create(user_a=other_a, user_b=other_b, status=CoupleStatus.ACTIVE)
        other_deck = RecommendationDeck.objects.create(couple=other_couple, mode="best_match")
        RecommendationDeckItem.objects.create(deck=other_deck, name=sample_name, rank=1)

        with pytest.raises(SwipeValidationError, match="Deck not found"):
            validate_source_deck(couple, str(sample_name.id), str(other_deck.id))

    def test_name_not_in_deck_rejected(self, couple_with_users, sample_name, db):
        """A valid couple deck must contain the submitted name."""
        couple, _, _ = couple_with_users
        other_name = Name.objects.create(
            canonical_name="OtherDeckName",
            display_name="Other Deck Name",
            gender_usage=["girl"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="modern",
            historical_significance_score=0.2,
            semantic_summary="Another deck name.",
            active=True,
        )
        deck = RecommendationDeck.objects.create(couple=couple, mode="best_match")
        RecommendationDeckItem.objects.create(deck=deck, name=other_name, rank=1)

        with pytest.raises(SwipeValidationError, match="Deck not found"):
            validate_source_deck(couple, str(sample_name.id), str(deck.id))


class TestCheckMutualMatch:
    """Tests for check_mutual_match function."""

    def test_both_like_is_match(self, couple_with_users, sample_name):
        """Both parents liking = mutual match."""
        couple, user_a, user_b = couple_with_users

        Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=sample_name, action=SwipeAction.LIKE)

        assert check_mutual_match(couple, str(sample_name.id)) is True

    def test_one_like_one_dislike_no_match(self, couple_with_users, sample_name):
        """One like + one dislike = no match."""
        couple, user_a, user_b = couple_with_users

        Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=sample_name, action=SwipeAction.DISLIKE)

        assert check_mutual_match(couple, str(sample_name.id)) is False

    def test_single_like_no_match(self, couple_with_users, sample_name):
        """Only one parent swiped = no match."""
        couple, user_a, _ = couple_with_users

        Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.LIKE)

        assert check_mutual_match(couple, str(sample_name.id)) is False

    def test_both_dislike_no_match(self, couple_with_users, sample_name):
        """Both disliking = no match."""
        couple, user_a, user_b = couple_with_users

        Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.DISLIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=sample_name, action=SwipeAction.DISLIKE)

        assert check_mutual_match(couple, str(sample_name.id)) is False

    def test_like_and_maybe_no_match(self, couple_with_users, sample_name):
        """Like + maybe = no match (only like+like counts)."""
        couple, user_a, user_b = couple_with_users

        Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=sample_name, action=SwipeAction.MAYBE)

        assert check_mutual_match(couple, str(sample_name.id)) is False

    def test_no_partner_no_match(self, db, sample_name):
        """Couple without user_b cannot have a match."""
        user_a = User.objects.create_user(email="solo@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=None, status=CoupleStatus.PENDING
        )
        Swipe.objects.create(couple=couple, user=user_a, name=sample_name, action=SwipeAction.LIKE)

        assert check_mutual_match(couple, str(sample_name.id)) is False


class TestCreateMatch:
    """Tests for create_match function."""

    def test_creates_match_record(self, couple_with_users, sample_name):
        """Creates a MutualMatch with computed strength score."""
        couple, _, _ = couple_with_users
        match = create_match(couple, str(sample_name.id))

        assert match.couple == couple
        assert match.name == sample_name
        assert match.status == MatchStatus.ACTIVE
        assert match.match_strength_score >= 0.0
        assert match.match_strength_score <= 1.0

    def test_idempotent_returns_existing(self, couple_with_users, sample_name):
        """Creating match for same couple+name returns existing."""
        couple, _, _ = couple_with_users

        match1 = create_match(couple, str(sample_name.id))
        match2 = create_match(couple, str(sample_name.id))

        assert match1.id == match2.id

    def test_strength_score_uses_name_metadata(self, couple_with_users):
        """Match strength score incorporates name metadata."""
        couple, _, _ = couple_with_users

        # Name with high historical significance and multiple origins
        rich_name = Name.objects.create(
            canonical_name="RichName",
            display_name="Rich Name",
            gender_usage=["boy", "girl"],
            origin_backgrounds=["Spanish", "Greek", "Russian", "German", "English"],
            languages=["es", "en", "ru", "de"],
            scripts=["Latin", "Cyrillic"],
            variants=["RichName", "RichNombre"],
            length_category="medium",
            age_style_category="timeless",
            historical_significance_score=0.9,
            semantic_summary="A rich multicultural name.",
            active=True,
        )

        match = create_match(couple, str(rich_name.id))
        # High historical + many origins + many languages = high score
        assert match.match_strength_score > 0.5


class TestSwipeViewMatchResponse:
    """Tests for swipe API endpoint match response payload."""

    @pytest.fixture
    def api_client_for_user(self, couple_with_users):
        """Create an authenticated API client for user_a."""
        couple, user_a, user_b = couple_with_users
        token, _ = Token.objects.get_or_create(user=user_a)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client, couple, user_a, user_b

    def test_swipe_match_response_includes_display_name(self, api_client_for_user, sample_name):
        """When a mutual match occurs, the response includes display_name."""
        client, couple, user_a, user_b = api_client_for_user

        # User B likes the name first (directly in DB)
        Swipe.objects.create(
            couple=couple, user=user_b, name=sample_name, action=SwipeAction.LIKE
        )

        # User A swipes like via the API — should trigger a match
        response = client.post(
            "/api/v1/swipes/",
            {"name_id": str(sample_name.id), "action": "like"},
            format="json",
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["is_match"] is True
        assert data["match"] is not None
        assert data["match"]["display_name"] == sample_name.display_name
        assert data["match"]["name_id"] == str(sample_name.id)

    def test_swipe_no_match_response_has_no_match_data(self, api_client_for_user, sample_name):
        """When no match occurs, match data is null."""
        client, couple, user_a, user_b = api_client_for_user

        # Only user A likes — no match
        response = client.post(
            "/api/v1/swipes/",
            {"name_id": str(sample_name.id), "action": "like"},
            format="json",
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["is_match"] is False
        assert data["match"] is None

    def test_duplicate_dislike_then_like_does_not_create_false_match(self, api_client_for_user, sample_name):
        """A user who previously disliked cannot trigger a match by re-sending like."""
        client, couple, user_a, user_b = api_client_for_user

        # User B likes the name
        Swipe.objects.create(
            couple=couple, user=user_b, name=sample_name, action=SwipeAction.LIKE
        )

        # User A dislikes the name first
        Swipe.objects.create(
            couple=couple, user=user_a, name=sample_name, action=SwipeAction.DISLIKE
        )

        # User A now sends a 'like' request — but the stored swipe is still 'dislike'
        response = client.post(
            "/api/v1/swipes/",
            {"name_id": str(sample_name.id), "action": "like"},
            format="json",
        )

        # Should NOT trigger a match because the stored swipe is 'dislike'
        assert response.status_code == 200  # duplicate returns 200
        data = response.json()["data"]
        assert data["is_match"] is False
        assert data["match"] is None
        assert data["swipe"]["was_duplicate"] is True
        assert data["swipe"]["action"] == "dislike"  # stored action unchanged
