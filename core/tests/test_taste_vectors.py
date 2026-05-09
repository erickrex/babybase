"""Unit and integration tests for taste vector computation, confidence scoring,
dislike repulsion, phase selection, midpoint merging, solo onboarding,
couple formation association, and deck generation with Phase D.

Tasks 14.1–14.6 of the taste-vector-deck-sharing spec.
"""

import math
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    Couple,
    CoupleStatus,
    Name,
    OnboardingResponse,
    RecommendationDeck,
    Swipe,
    SwipeAction,
    UserTasteVector,
)
from core.services.taste_vectors import (
    apply_dislike_repulsion,
    compute_confidence_score,
    compute_confidence_weighted_midpoint,
    compute_recency_weights,
    compute_taste_vector,
    compute_weighted_centroid,
    normalize_vector,
    select_phase,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Task 14.1: Unit tests for taste vector computation
# Requirements: 3.1, 3.2, 3.4
# ---------------------------------------------------------------------------


class TestRecencyWeighting:
    """Tests for compute_recency_weights with known timestamps."""

    def test_single_timestamp_weight_is_one(self):
        """A single timestamp should get weight 1.0 (most recent = itself)."""
        now = timezone.now()
        weights = compute_recency_weights([now])
        assert weights == [1.0]

    def test_most_recent_gets_weight_one(self):
        """The most recent timestamp always gets weight 1.0."""
        now = timezone.now()
        timestamps = [now - timedelta(days=14), now - timedelta(days=7), now]
        weights = compute_recency_weights(timestamps)
        assert weights[2] == pytest.approx(1.0)

    def test_half_life_decay_at_14_days(self):
        """A timestamp 14 days old should have weight ~0.5 with default half_life=14."""
        now = timezone.now()
        timestamps = [now - timedelta(days=14), now]
        weights = compute_recency_weights(timestamps, half_life_days=14.0)
        assert weights[0] == pytest.approx(0.5, abs=0.01)
        assert weights[1] == pytest.approx(1.0)

    def test_28_days_old_weight_is_quarter(self):
        """A timestamp 28 days old (2 half-lives) should have weight ~0.25."""
        now = timezone.now()
        timestamps = [now - timedelta(days=28), now]
        weights = compute_recency_weights(timestamps, half_life_days=14.0)
        assert weights[0] == pytest.approx(0.25, abs=0.01)

    def test_empty_timestamps_returns_empty(self):
        """Empty input returns empty list."""
        assert compute_recency_weights([]) == []

    def test_weights_are_monotonically_decreasing_with_age(self):
        """Older timestamps get lower weights."""
        now = timezone.now()
        timestamps = [now - timedelta(days=d) for d in [30, 20, 10, 0]]
        weights = compute_recency_weights(timestamps)
        # weights[3] > weights[2] > weights[1] > weights[0]
        assert weights[3] > weights[2] > weights[1] > weights[0]


class TestWeightedCentroid:
    """Tests for compute_weighted_centroid with simple vectors."""

    def test_equal_weights_gives_simple_average(self):
        """Equal weights produce the arithmetic mean."""
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        weights = [1.0, 1.0]
        centroid = compute_weighted_centroid(vectors, weights)
        assert centroid == pytest.approx([0.5, 0.5])

    def test_single_vector_returns_itself(self):
        """A single vector with any weight returns itself."""
        vectors = [[3.0, 4.0, 5.0]]
        weights = [2.0]
        centroid = compute_weighted_centroid(vectors, weights)
        assert centroid == pytest.approx([3.0, 4.0, 5.0])

    def test_zero_weight_vector_ignored(self):
        """A vector with weight 0 does not contribute to the centroid."""
        vectors = [[10.0, 0.0], [0.0, 10.0]]
        weights = [1.0, 0.0]
        centroid = compute_weighted_centroid(vectors, weights)
        assert centroid == pytest.approx([10.0, 0.0])

    def test_asymmetric_weights(self):
        """Higher weight pulls centroid toward that vector."""
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        weights = [3.0, 1.0]
        centroid = compute_weighted_centroid(vectors, weights)
        # (3*1 + 1*0)/4 = 0.75, (3*0 + 1*1)/4 = 0.25
        assert centroid == pytest.approx([0.75, 0.25])

    def test_empty_vectors_returns_empty(self):
        """Empty input returns empty list."""
        assert compute_weighted_centroid([], []) == []


class TestNormalizeVector:
    """Tests for normalize_vector with zero vector and unit vector."""

    def test_zero_vector_returns_zero_vector(self):
        """A zero vector normalizes to a zero vector (no division by zero)."""
        result = normalize_vector([0.0, 0.0, 0.0])
        assert result == [0.0, 0.0, 0.0]

    def test_unit_vector_unchanged(self):
        """A unit vector normalizes to itself."""
        unit = [1.0, 0.0, 0.0]
        result = normalize_vector(unit)
        assert result == pytest.approx(unit)

    def test_arbitrary_vector_has_unit_length(self):
        """Any non-zero vector normalizes to unit length."""
        vec = [3.0, 4.0]
        result = normalize_vector(vec)
        magnitude = math.sqrt(sum(x * x for x in result))
        assert magnitude == pytest.approx(1.0)
        assert result == pytest.approx([0.6, 0.8])

    def test_empty_vector_returns_empty(self):
        """Empty input returns empty list."""
        assert normalize_vector([]) == []

    def test_negative_values_normalized(self):
        """Negative values are handled correctly."""
        vec = [-3.0, 4.0]
        result = normalize_vector(vec)
        magnitude = math.sqrt(sum(x * x for x in result))
        assert magnitude == pytest.approx(1.0)


class TestComputeTasteVectorEndToEnd:
    """Tests for compute_taste_vector end-to-end with mocked Qdrant."""

    @pytest.mark.django_db
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_computes_vector_from_liked_swipes(self, mock_fetch):
        """compute_taste_vector produces a valid UserTasteVector from swipe history."""
        user = User.objects.create_user(email="tv_user@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user, status=CoupleStatus.ACTIVE, residence_country="US"
        )

        # Create names and swipes
        names = []
        for i in range(25):
            name = Name.objects.create(
                canonical_name=f"TVName{i}",
                display_name=f"TVName{i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test name.",
                active=True,
            )
            names.append(name)

        # Create 20 likes and 5 dislikes
        for i in range(20):
            Swipe.objects.create(
                couple=couple, user=user, name=names[i], action=SwipeAction.LIKE
            )
        for i in range(20, 25):
            Swipe.objects.create(
                couple=couple, user=user, name=names[i], action=SwipeAction.DISLIKE
            )

        # Mock Qdrant returning 3-dim vectors for simplicity
        mock_fetch.return_value = [[1.0, 0.0, 0.0]] * 20

        result = compute_taste_vector(user)

        assert result is not None
        assert isinstance(result, UserTasteVector)
        assert result.swipe_count == 25
        assert result.like_rate == pytest.approx(0.8)
        assert result.confidence_score > 0.0
        assert len(result.embedding) == 3
        # Normalized unit vector
        magnitude = math.sqrt(sum(x * x for x in result.embedding))
        assert magnitude == pytest.approx(1.0, abs=0.01)

    @pytest.mark.django_db
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_no_swipes_returns_none(self, mock_fetch):
        """compute_taste_vector returns None when user has no swipes."""
        user = User.objects.create_user(email="tv_noswipe@test.com", password="testpass123")
        result = compute_taste_vector(user)
        assert result is None
        mock_fetch.assert_not_called()

    @pytest.mark.django_db
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_only_dislikes_returns_none(self, mock_fetch):
        """compute_taste_vector returns None when user has only dislikes (no likes)."""
        user = User.objects.create_user(email="tv_dislike@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user, status=CoupleStatus.ACTIVE, residence_country="US"
        )
        name = Name.objects.create(
            canonical_name="DislikeOnly",
            display_name="DislikeOnly",
            gender_usage=["boy"],
            origin_backgrounds=["Spanish"],
            languages=["es"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Test.",
            active=True,
        )
        Swipe.objects.create(
            couple=couple, user=user, name=name, action=SwipeAction.DISLIKE
        )

        result = compute_taste_vector(user)
        assert result is None


# ---------------------------------------------------------------------------
# Task 14.2: Unit tests for confidence scoring
# Requirements: 4.1, 4.2, 4.3, 4.5
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    """Tests for compute_confidence_score boundary conditions."""

    def test_swipe_count_19_confidence_below_half(self):
        """swipe_count=19 → confidence < 0.5 (sigmoid below center)."""
        score = compute_confidence_score(
            swipe_count=19, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        assert score < 0.5

    def test_swipe_count_20_confidence_approx_half(self):
        """swipe_count=20 → confidence ≈ 0.5 (sigmoid at center)."""
        score = compute_confidence_score(
            swipe_count=20, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        assert score == pytest.approx(0.5, abs=0.01)

    def test_swipe_count_100_confidence_near_one(self):
        """swipe_count=100 with optimal inputs → confidence near 1.0."""
        score = compute_confidence_score(
            swipe_count=100, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        assert score > 0.9

    def test_like_rate_optimal_no_penalty(self):
        """like_rate=0.5 (within [0.1, 0.8]) → no rate penalty."""
        score_optimal = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        score_edge = compute_confidence_score(
            swipe_count=50, like_rate=0.3, vector_variance=0.1, days_since_update=0.0
        )
        # Both in optimal range, should be equal
        assert score_optimal == pytest.approx(score_edge)

    def test_like_rate_high_penalized(self):
        """like_rate=0.95 → penalized (rate_factor < 1.0)."""
        score_optimal = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        score_high = compute_confidence_score(
            swipe_count=50, like_rate=0.95, vector_variance=0.1, days_since_update=0.0
        )
        assert score_high < score_optimal

    def test_like_rate_low_penalized(self):
        """like_rate=0.05 → penalized (rate_factor < 1.0)."""
        score_optimal = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        score_low = compute_confidence_score(
            swipe_count=50, like_rate=0.05, vector_variance=0.1, days_since_update=0.0
        )
        assert score_low < score_optimal

    def test_staleness_0_days_no_penalty(self):
        """0 days since update → staleness_factor = 1.0."""
        score = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        score_30 = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=30.0
        )
        # Both should be equal (no penalty up to 30 days)
        assert score == pytest.approx(score_30)

    def test_staleness_60_days_reduced(self):
        """60 days since update → staleness_factor = 0.5."""
        score_fresh = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=0.0
        )
        score_stale = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=60.0
        )
        # staleness_factor at 60 days = 1.0 - (60-30)/60 = 0.5
        assert score_stale == pytest.approx(score_fresh * 0.5, abs=0.01)

    def test_staleness_90_days_zero(self):
        """90 days since update → staleness_factor = 0.0, confidence = 0.0."""
        score = compute_confidence_score(
            swipe_count=50, like_rate=0.5, vector_variance=0.1, days_since_update=90.0
        )
        assert score == pytest.approx(0.0)

    def test_confidence_always_in_range(self):
        """Confidence score is always in [0.0, 1.0] for various inputs."""
        test_cases = [
            (0, 0.0, 0.0, 0.0),
            (1000, 0.5, 100.0, 0.0),
            (5, 0.99, 0.001, 100.0),
            (50, 0.05, 50.0, 45.0),
        ]
        for swipe_count, like_rate, variance, days in test_cases:
            score = compute_confidence_score(swipe_count, like_rate, variance, days)
            assert 0.0 <= score <= 1.0, f"Failed for inputs: {swipe_count}, {like_rate}, {variance}, {days}"


# ---------------------------------------------------------------------------
# Task 14.3: Unit tests for dislike repulsion
# Requirements: 12.1, 12.2, 12.3, 12.4
# ---------------------------------------------------------------------------


class TestDislikeRepulsion:
    """Tests for apply_dislike_repulsion and activation conditions."""

    def test_repulsion_applied_modifies_vector(self):
        """Repulsion subtracts weighted dislike centroid from like centroid."""
        like_centroid = [1.0, 0.0, 0.0]
        dislike_centroid = [0.0, 1.0, 0.0]
        result = apply_dislike_repulsion(like_centroid, dislike_centroid, repulsion_weight=0.3)

        # Pre-normalization: [1.0, -0.3, 0.0], then normalized
        pre_norm = [1.0, -0.3, 0.0]
        mag = math.sqrt(sum(x * x for x in pre_norm))
        expected = [x / mag for x in pre_norm]
        assert result == pytest.approx(expected, abs=1e-6)

    def test_repulsion_result_is_unit_length(self):
        """The output of apply_dislike_repulsion is always unit length."""
        like_centroid = [0.5, 0.5, 0.5]
        dislike_centroid = [0.1, 0.2, 0.3]
        result = apply_dislike_repulsion(like_centroid, dislike_centroid)
        magnitude = math.sqrt(sum(x * x for x in result))
        assert magnitude == pytest.approx(1.0, abs=0.01)

    def test_zero_vector_edge_case_uses_like_centroid(self):
        """When repulsion produces a zero vector, use normalized like centroid."""
        # If like_centroid = repulsion_weight * dislike_centroid, result is zero
        like_centroid = [0.3, 0.3, 0.3]
        dislike_centroid = [1.0, 1.0, 1.0]
        # result = [0.3 - 0.3*1.0, 0.3 - 0.3*1.0, 0.3 - 0.3*1.0] = [0, 0, 0]
        result = apply_dislike_repulsion(like_centroid, dislike_centroid, repulsion_weight=0.3)
        # Should fall back to normalized like_centroid
        expected = normalize_vector(like_centroid)
        assert result == pytest.approx(expected, abs=1e-6)

    @pytest.mark.django_db
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_repulsion_applied_when_like_rate_above_08_and_dislikes_gte_5(self, mock_fetch):
        """Repulsion is applied when like_rate > 0.8 and dislike_count >= 5."""
        user = User.objects.create_user(email="repulsion_yes@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user, status=CoupleStatus.ACTIVE, residence_country="US"
        )

        names = []
        for i in range(30):
            name = Name.objects.create(
                canonical_name=f"RepYes{i}",
                display_name=f"RepYes{i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test.",
                active=True,
            )
            names.append(name)

        # 25 likes, 5 dislikes → like_rate = 25/30 ≈ 0.833 > 0.8
        for i in range(25):
            Swipe.objects.create(couple=couple, user=user, name=names[i], action=SwipeAction.LIKE)
        for i in range(25, 30):
            Swipe.objects.create(couple=couple, user=user, name=names[i], action=SwipeAction.DISLIKE)

        # Mock: first call for liked vectors, second for disliked vectors
        liked_vecs = [[1.0, 0.0, 0.0]] * 25
        disliked_vecs = [[0.0, 1.0, 0.0]] * 5
        mock_fetch.side_effect = [liked_vecs, disliked_vecs]

        result = compute_taste_vector(user)

        assert result is not None
        # Repulsion was applied: vector should NOT be [1, 0, 0]
        # It should be normalized(like_centroid - 0.3 * dislike_centroid)
        # = normalized([1, 0, 0] - 0.3*[0, 1, 0]) = normalized([1, -0.3, 0])
        expected_pre = [1.0, -0.3, 0.0]
        mag = math.sqrt(sum(x * x for x in expected_pre))
        expected = [x / mag for x in expected_pre]
        assert result.embedding == pytest.approx(expected, abs=0.01)
        # Verify fetch was called twice (liked + disliked)
        assert mock_fetch.call_count == 2

    @pytest.mark.django_db
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_repulsion_skipped_when_dislike_count_below_5(self, mock_fetch):
        """Repulsion is skipped when dislike_count < 5 even if like_rate > 0.8."""
        user = User.objects.create_user(email="repulsion_skip_d@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user, status=CoupleStatus.ACTIVE, residence_country="US"
        )

        names = []
        for i in range(24):
            name = Name.objects.create(
                canonical_name=f"RepSkipD{i}",
                display_name=f"RepSkipD{i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test.",
                active=True,
            )
            names.append(name)

        # 20 likes, 4 dislikes → like_rate = 20/24 ≈ 0.833 > 0.8, but dislike_count=4 < 5
        for i in range(20):
            Swipe.objects.create(couple=couple, user=user, name=names[i], action=SwipeAction.LIKE)
        for i in range(20, 24):
            Swipe.objects.create(couple=couple, user=user, name=names[i], action=SwipeAction.DISLIKE)

        mock_fetch.return_value = [[1.0, 0.0, 0.0]] * 20

        result = compute_taste_vector(user)

        assert result is not None
        # Repulsion NOT applied: vector should be normalized like centroid = [1, 0, 0]
        assert result.embedding == pytest.approx([1.0, 0.0, 0.0], abs=0.01)
        # Only one fetch call (for likes only, no dislike fetch)
        assert mock_fetch.call_count == 1

    @pytest.mark.django_db
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_repulsion_skipped_when_like_rate_below_08(self, mock_fetch):
        """Repulsion is skipped when like_rate <= 0.8 even with >= 5 dislikes."""
        user = User.objects.create_user(email="repulsion_skip_r@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user, status=CoupleStatus.ACTIVE, residence_country="US"
        )

        names = []
        for i in range(20):
            name = Name.objects.create(
                canonical_name=f"RepSkipR{i}",
                display_name=f"RepSkipR{i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test.",
                active=True,
            )
            names.append(name)

        # 10 likes, 10 dislikes → like_rate = 0.5 <= 0.8, dislike_count=10 >= 5
        for i in range(10):
            Swipe.objects.create(couple=couple, user=user, name=names[i], action=SwipeAction.LIKE)
        for i in range(10, 20):
            Swipe.objects.create(couple=couple, user=user, name=names[i], action=SwipeAction.DISLIKE)

        mock_fetch.return_value = [[1.0, 0.0, 0.0]] * 10

        result = compute_taste_vector(user)

        assert result is not None
        # Repulsion NOT applied
        assert result.embedding == pytest.approx([1.0, 0.0, 0.0], abs=0.01)
        # Only one fetch call (for likes only)
        assert mock_fetch.call_count == 1


# ---------------------------------------------------------------------------
# Task 14.4: Unit tests for phase selector and midpoint merger
# Requirements: 5.1, 5.2, 5.3, 6.1, 6.2
# ---------------------------------------------------------------------------


class TestPhaseSelector:
    """Tests for select_phase and check_trust_thresholds."""

    @pytest.mark.django_db
    def test_both_users_meet_thresholds_phase_d(self):
        """Both users meet all trust thresholds → Phase D selected."""
        user_a = User.objects.create_user(email="phase_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="phase_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * 10,
            swipe_count=30,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.8,
            last_updated_at=now,
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.2] * 10,
            swipe_count=25,
            like_rate=0.4,
            vector_variance=0.2,
            confidence_score=0.7,
            last_updated_at=now,
        )

        phase, data = select_phase(couple)

        assert phase == "phase_d"
        assert data["vec_a"] == [0.1] * 10
        assert data["conf_a"] == 0.8
        assert data["vec_b"] == [0.2] * 10
        assert data["conf_b"] == 0.7

    @pytest.mark.django_db
    def test_one_user_below_swipe_threshold_phase_c(self):
        """One user has swipe_count < 20 → Phase C selected."""
        user_a = User.objects.create_user(email="phase_low_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="phase_low_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * 10,
            swipe_count=15,  # Below threshold
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.3,
            last_updated_at=now,
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.2] * 10,
            swipe_count=30,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.8,
            last_updated_at=now,
        )

        phase, data = select_phase(couple)

        assert phase == "phase_c"
        assert "reason" in data
        assert "swipe_count" in data["reason"]

    @pytest.mark.django_db
    def test_missing_taste_vector_phase_c(self):
        """Missing UserTasteVector for one user → Phase C selected."""
        user_a = User.objects.create_user(email="phase_miss_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="phase_miss_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        # Only user_a has a taste vector
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * 10,
            swipe_count=30,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.8,
            last_updated_at=timezone.now(),
        )

        phase, data = select_phase(couple)

        assert phase == "phase_c"
        assert "no_taste_vector" in data["reason"]

    @pytest.mark.django_db
    def test_stale_vector_phase_c(self):
        """Vector older than 30 days → Phase C selected."""
        user_a = User.objects.create_user(email="phase_stale_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="phase_stale_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        stale_time = timezone.now() - timedelta(days=35)
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * 10,
            swipe_count=30,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.8,
            last_updated_at=stale_time,
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.2] * 10,
            swipe_count=30,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.8,
            last_updated_at=timezone.now(),
        )

        phase, data = select_phase(couple)

        assert phase == "phase_c"
        assert "stale" in data["reason"]

    @pytest.mark.django_db
    def test_like_rate_above_threshold_phase_c(self):
        """like_rate > 0.8 → Phase C selected."""
        user_a = User.objects.create_user(email="phase_lr_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="phase_lr_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * 10,
            swipe_count=30,
            like_rate=0.9,  # Above max threshold
            vector_variance=0.1,
            confidence_score=0.6,
            last_updated_at=now,
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.2] * 10,
            swipe_count=30,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.8,
            last_updated_at=now,
        )

        phase, data = select_phase(couple)

        assert phase == "phase_c"
        assert "like_rate" in data["reason"]


class TestMidpointMerger:
    """Tests for compute_confidence_weighted_midpoint."""

    def test_equal_confidence_equal_weighting(self):
        """Equal confidence → midpoint is simple average (normalized)."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        result = compute_confidence_weighted_midpoint(vec_a, 0.8, vec_b, 0.8)

        # Pre-normalization: (0.8*[1,0,0] + 0.8*[0,1,0]) / 1.6 = [0.5, 0.5, 0]
        # Normalized: [0.5/sqrt(0.5), 0.5/sqrt(0.5), 0]
        expected_pre = [0.5, 0.5, 0.0]
        mag = math.sqrt(sum(x * x for x in expected_pre))
        expected = [x / mag for x in expected_pre]
        assert result == pytest.approx(expected, abs=1e-6)

    def test_asymmetric_confidence_pulls_toward_higher(self):
        """Higher confidence pulls midpoint closer to that vector."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]

        # conf_a much higher than conf_b
        result = compute_confidence_weighted_midpoint(vec_a, 0.9, vec_b, 0.1)

        # Pre-normalization: (0.9*[1,0,0] + 0.1*[0,1,0]) / 1.0 = [0.9, 0.1, 0]
        # Cosine similarity to vec_a should be higher than to vec_b
        cos_a = sum(r * a for r, a in zip(result, vec_a))
        cos_b = sum(r * b for r, b in zip(result, vec_b))
        assert cos_a > cos_b

    def test_midpoint_is_unit_length(self):
        """The merged vector is always unit length."""
        vec_a = [0.5, 0.3, 0.8, 0.1]
        vec_b = [0.2, 0.7, 0.1, 0.6]
        result = compute_confidence_weighted_midpoint(vec_a, 0.6, vec_b, 0.4)
        magnitude = math.sqrt(sum(x * x for x in result))
        assert magnitude == pytest.approx(1.0, abs=0.01)

    def test_one_zero_confidence_uses_other_vector(self):
        """If one confidence is near-zero, result is close to the other vector."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        result = compute_confidence_weighted_midpoint(vec_a, 0.99, vec_b, 0.01)

        # Should be very close to normalized vec_a
        cos_a = sum(r * a for r, a in zip(result, vec_a))
        assert cos_a > 0.99


# ---------------------------------------------------------------------------
# Task 14.5: Unit tests for solo onboarding and couple formation association
# Requirements: 2.1, 2.2, 2.3, 11.1
# ---------------------------------------------------------------------------


class TestSoloOnboarding:
    """Tests for save_preferences with and without couple."""

    @pytest.mark.django_db
    def test_save_preferences_without_couple(self):
        """Solo user can save preferences with couple=None."""
        from core.services.onboarding import save_preferences

        user = User.objects.create_user(email="solo@test.com", password="testpass123")

        answers = {
            "preferred_name_backgrounds": ["Spanish", "German"],
            "preferred_name_age": "balanced",
            "baby_gender_preference": "boy",
            "preferred_name_length": "any",
            "historical_importance": "medium",
            "residence_country": "DE",
        }

        response = save_preferences(user, couple=None, answers=answers)

        assert response is not None
        assert response.user == user
        assert response.couple is None
        assert response.preferred_name_backgrounds == ["Spanish", "German"]
        assert response.baby_gender_preference == "boy"

    @pytest.mark.django_db
    def test_save_preferences_with_couple(self):
        """User in a couple saves preferences linked to the couple."""
        from core.services.onboarding import save_preferences

        user = User.objects.create_user(email="coupled@test.com", password="testpass123")
        partner = User.objects.create_user(email="partner@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user, user_b=partner, status=CoupleStatus.ACTIVE
        )

        answers = {
            "preferred_name_backgrounds": ["Russian"],
            "preferred_name_age": "old",
            "baby_gender_preference": "girl",
            "preferred_name_length": "short",
            "historical_importance": "high",
            "residence_country": "RU",
        }

        response = save_preferences(user, couple=couple, answers=answers)

        assert response.couple == couple
        assert response.preferred_name_backgrounds == ["Russian"]
        # Residence country should be updated on the couple
        couple.refresh_from_db()
        assert couple.residence_country == "RU"

    @pytest.mark.django_db
    def test_save_preferences_solo_does_not_update_couple_country(self):
        """Solo onboarding with couple=None does not crash on residence_country."""
        from core.services.onboarding import save_preferences

        user = User.objects.create_user(email="solo_country@test.com", password="testpass123")

        answers = {
            "preferred_name_backgrounds": ["Spanish"],
            "preferred_name_age": "balanced",
            "baby_gender_preference": "boy",
            "preferred_name_length": "any",
            "historical_importance": "medium",
            "residence_country": "ES",
        }

        # Should not raise even though couple is None
        response = save_preferences(user, couple=None, answers=answers)
        assert response.couple is None


class TestCoupleFormationAssociation:
    """Tests for connect_pending_invite and create_couple associating solo responses."""

    @pytest.mark.django_db
    def test_connect_pending_invite_associates_solo_onboarding(self):
        """connect_pending_invite associates solo OnboardingResponse with new couple."""
        from core.services.couples import connect_pending_invite, create_couple

        user_a = User.objects.create_user(email="inv_a@test.com", password="testpass123")

        # User A creates a pending invite
        couple = create_couple(user_a, "inv_b@test.com")
        assert couple.status == CoupleStatus.PENDING

        # User A onboards solo
        OnboardingResponse.objects.create(
            user=user_a,
            couple=None,
            preferred_name_backgrounds=["Spanish"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )

        # Partner signs up
        user_b = User.objects.create_user(email="inv_b@test.com", password="testpass123")

        # Partner also onboards solo before connecting
        OnboardingResponse.objects.create(
            user=user_b,
            couple=None,
            preferred_name_backgrounds=["Russian"],
            preferred_name_age="old",
            baby_gender_preference="girl",
            preferred_name_length="short",
            historical_importance="high",
        )

        # Connect the pending invite
        connected = connect_pending_invite(user_b)

        assert connected is not None
        assert connected.status == CoupleStatus.ACTIVE

        # Both solo onboarding responses should now be associated with the couple
        resp_a = OnboardingResponse.objects.get(user=user_a)
        resp_b = OnboardingResponse.objects.get(user=user_b)
        assert resp_a.couple == connected
        assert resp_b.couple == connected

    @pytest.mark.django_db
    def test_create_couple_immediate_connection_associates_solo_responses(self):
        """create_couple with existing partner associates solo OnboardingResponses."""
        from core.services.couples import create_couple

        user_a = User.objects.create_user(email="imm_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="imm_b@test.com", password="testpass123")

        # Both users onboard solo
        OnboardingResponse.objects.create(
            user=user_a,
            couple=None,
            preferred_name_backgrounds=["German"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )
        OnboardingResponse.objects.create(
            user=user_b,
            couple=None,
            preferred_name_backgrounds=["French"],
            preferred_name_age="new",
            baby_gender_preference="girl",
            preferred_name_length="long",
            historical_importance="low",
        )

        # Create couple (partner already exists → immediate connection)
        couple = create_couple(user_a, user_b.email)

        assert couple.status == CoupleStatus.ACTIVE

        # Both solo responses should be associated
        resp_a = OnboardingResponse.objects.get(user=user_a)
        resp_b = OnboardingResponse.objects.get(user=user_b)
        assert resp_a.couple == couple
        assert resp_b.couple == couple


# ---------------------------------------------------------------------------
# Task 14.6: Integration tests for deck generation with Phase D
# Requirements: 6.3, 9.1, 9.2, 10.1, 10.2
# ---------------------------------------------------------------------------


class TestDeckGenerationPhaseD:
    """Integration tests for deck generation with Phase D."""

    @pytest.fixture
    def phase_d_couple(self, db):
        """Create a couple with both users meeting Phase D thresholds."""
        user_a = User.objects.create_user(email="deck_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="deck_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a,
            user_b=user_b,
            status=CoupleStatus.ACTIVE,
            residence_country="DE",
        )
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["Spanish", "German"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )
        OnboardingResponse.objects.create(
            user=user_b,
            couple=couple,
            preferred_name_backgrounds=["Russian", "German"],
            preferred_name_age="old",
            baby_gender_preference="boy",
            preferred_name_length="short",
            historical_importance="high",
        )

        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * 1536,
            swipe_count=40,
            like_rate=0.5,
            vector_variance=0.1,
            confidence_score=0.85,
            last_updated_at=now,
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.2] * 1536,
            swipe_count=35,
            like_rate=0.4,
            vector_variance=0.15,
            confidence_score=0.75,
            last_updated_at=now,
        )
        return couple, user_a, user_b

    @pytest.fixture
    def sample_names(self, db):
        """Create sample names for deck generation tests."""
        names = []
        name_data = [
            ("DeckSofia", ["Spanish", "Greek"], "classic", 0.8),
            ("DeckMateo", ["Spanish"], "modern", 0.4),
            ("DeckNadia", ["Russian", "Arabic"], "timeless", 0.6),
            ("DeckLeo", ["German", "Spanish"], "classic", 0.5),
            ("DeckKai", ["Japanese", "German"], "modern", 0.3),
        ]
        for canonical, origins, style, hist in name_data:
            name = Name.objects.create(
                canonical_name=canonical,
                display_name=canonical,
                gender_usage=["boy"],
                origin_backgrounds=origins,
                languages=["en"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category=style,
                historical_significance_score=hist,
                semantic_summary=f"A {style} name.",
                active=True,
            )
            names.append(name)
        return names

    @pytest.mark.django_db
    @patch("core.services.recommendations.search_names")
    def test_full_pipeline_phase_d_with_metrics(self, mock_search, phase_d_couple, sample_names):
        """Full pipeline: Phase D selected, quality metrics in retrieval_profile_json."""
        from core.services.recommendations import generate_deck

        couple, user_a, user_b = phase_d_couple

        # Mock Qdrant returning good scores (>= 0.6)
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.85 - i * 0.05,
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
            for i, name in enumerate(sample_names)
        ]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="best_match")

        assert isinstance(deck, RecommendationDeck)
        assert deck.items.count() > 0

        # Verify quality metrics in retrieval_profile_json
        profile = deck.retrieval_profile_json
        assert profile["phase_used"] == "phase_d"
        assert profile["user_a_confidence_score"] == 0.85
        assert profile["user_b_confidence_score"] == 0.75
        assert profile["user_a_swipe_count"] == 40
        assert profile["user_b_swipe_count"] == 35
        assert profile["top_retrieval_score"] > 0.0
        assert profile["fallback_reason"] is None

    @pytest.mark.django_db
    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_sparse_retrieval_fallback_top_score_below_06(
        self, mock_embedding, mock_search, phase_d_couple, sample_names
    ):
        """Top score < 0.6 triggers Phase C fallback."""
        from core.services.recommendations import generate_deck

        couple, user_a, user_b = phase_d_couple

        # Phase D search returns low scores
        low_candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.4 - i * 0.05,
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
            for i, name in enumerate(sample_names)
        ]
        # Phase C fallback search returns good scores
        good_candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.8 - i * 0.05,
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
            for i, name in enumerate(sample_names)
        ]
        mock_search.side_effect = [low_candidates, good_candidates]
        mock_embedding.return_value = [0.3] * 1536

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        # Verify fallback was triggered
        profile = deck.retrieval_profile_json
        assert profile["phase_used"] == "phase_c"
        assert profile["fallback_reason"] == "top_score_below_threshold"
        # Phase C embedding was called for fallback
        mock_embedding.assert_called_once_with(couple)

    @pytest.mark.django_db
    @patch("core.services.recommendations.search_names")
    def test_relaxed_diversity_when_pool_sparse(self, mock_search, phase_d_couple, sample_names):
        """Fewer than 10 candidates above 0.5 triggers relaxed diversity."""
        from core.services.recommendations import generate_deck

        couple, user_a, user_b = phase_d_couple

        # All candidates have rerank_score that will be below 0.5 after scoring
        # Use low retrieval scores so final rerank scores are low
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.65,  # Above 0.6 so no Phase C fallback
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
            for i, name in enumerate(sample_names)
        ]
        mock_search.return_value = candidates

        # This should succeed without error even with sparse pool
        deck = generate_deck(couple, mode="best_match")
        assert isinstance(deck, RecommendationDeck)
        # With only 5 candidates total, all should be in the deck
        assert deck.items.count() == len(sample_names)

    @pytest.mark.django_db
    @patch("core.services.recommendations.search_names")
    @patch("core.services.onboarding._fetch_vectors_for_name_ids")
    def test_couple_formation_flow_register_onboard_solo_form_couple_generate_deck(
        self, mock_fetch_vectors, mock_search
    ):
        """Full flow: register → onboard solo → form couple → generate deck."""
        from core.services.couples import create_couple
        from core.services.onboarding import save_preferences
        from core.services.recommendations import generate_deck

        # Step 1: Both users register
        user_a = User.objects.create_user(email="flow_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="flow_b@test.com", password="testpass123")

        # Step 2: Both onboard solo
        answers_a = {
            "preferred_name_backgrounds": ["Spanish"],
            "preferred_name_age": "balanced",
            "baby_gender_preference": "boy",
            "preferred_name_length": "any",
            "historical_importance": "medium",
        }
        answers_b = {
            "preferred_name_backgrounds": ["German"],
            "preferred_name_age": "old",
            "baby_gender_preference": "boy",
            "preferred_name_length": "short",
            "historical_importance": "high",
        }
        save_preferences(user_a, couple=None, answers=answers_a)
        save_preferences(user_b, couple=None, answers=answers_b)

        # Verify solo onboarding saved
        assert OnboardingResponse.objects.filter(user=user_a, couple=None).exists()
        assert OnboardingResponse.objects.filter(user=user_b, couple=None).exists()

        # Step 3: Form couple (immediate connection since both exist)
        couple = create_couple(user_a, user_b.email)
        assert couple.status == CoupleStatus.ACTIVE

        # Verify solo responses are now associated
        assert OnboardingResponse.objects.filter(user=user_a, couple=couple).exists()
        assert OnboardingResponse.objects.filter(user=user_b, couple=couple).exists()

        # Step 4: Create names and swipes to build taste vectors
        names = []
        for i in range(5):
            name = Name.objects.create(
                canonical_name=f"FlowName{i}",
                display_name=f"FlowName{i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test.",
                active=True,
            )
            names.append(name)

        # Step 5: Generate deck (will use Phase C since no taste vectors yet)
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.8 - i * 0.05,
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
            for i, name in enumerate(names)
        ]
        mock_search.return_value = candidates

        with patch("core.services.embeddings.generate_embedding", return_value=[0.1] * 1536):
            deck = generate_deck(couple, mode="best_match")

        assert isinstance(deck, RecommendationDeck)
        assert deck.items.count() > 0

        # Verify Phase C was used (no taste vectors)
        profile = deck.retrieval_profile_json
        assert profile["phase_used"] == "phase_c"

    @pytest.mark.django_db
    @patch("core.services.recommendations.search_names")
    def test_quality_metrics_present_for_phase_c(self, mock_search):
        """Phase C deck generation also includes all quality metrics."""
        from core.services.recommendations import generate_deck

        user_a = User.objects.create_user(email="qm_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="qm_b@test.com", password="testpass123")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE, residence_country="DE"
        )
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["Spanish"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )
        OnboardingResponse.objects.create(
            user=user_b,
            couple=couple,
            preferred_name_backgrounds=["German"],
            preferred_name_age="old",
            baby_gender_preference="boy",
            preferred_name_length="short",
            historical_importance="high",
        )

        name = Name.objects.create(
            canonical_name="QMName",
            display_name="QMName",
            gender_usage=["boy"],
            origin_backgrounds=["Spanish"],
            languages=["es"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Test.",
            active=True,
        )

        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.8,
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
        ]
        mock_search.return_value = candidates

        with patch("core.services.embeddings.generate_embedding", return_value=[0.1] * 1536):
            deck = generate_deck(couple, mode="best_match")

        profile = deck.retrieval_profile_json
        # All required quality metric fields present
        assert "phase_used" in profile
        assert "user_a_confidence_score" in profile
        assert "user_b_confidence_score" in profile
        assert "user_a_swipe_count" in profile
        assert "user_b_swipe_count" in profile
        assert "top_retrieval_score" in profile
        assert "fallback_reason" in profile
        # Phase C values
        assert profile["phase_used"] == "phase_c"
        assert profile["user_a_confidence_score"] == 0.0
        assert profile["user_b_confidence_score"] == 0.0
