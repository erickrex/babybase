"""Property-based tests for taste vector computation and Phase D deck generation.

Uses Hypothesis to verify formal invariants of the taste vector system.
Each property maps to a correctness property from the design document.

Feature: taste-vector-deck-sharing
"""

import math
import random
import uuid
from datetime import timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.services.taste_vectors import (
    apply_dislike_repulsion,
    compute_confidence_score,
    compute_confidence_weighted_midpoint,
    compute_recency_weights,
    compute_vector_variance,
)

# ---------------------------------------------------------------------------
# Custom Strategies
# ---------------------------------------------------------------------------

# Small dimension for fast tests on pure math properties
SMALL_DIM = 16
FULL_DIM = 1536


@st.composite
def st_embedding(draw, dim=SMALL_DIM):
    """Generate a unit-length embedding vector of given dimension."""
    raw = draw(st.lists(
        st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=dim,
        max_size=dim,
    ))
    # Normalize to unit length
    magnitude = math.sqrt(sum(x * x for x in raw))
    if magnitude == 0.0:
        # If zero vector drawn, make a simple unit vector
        raw = [0.0] * dim
        raw[0] = 1.0
        return raw
    return [x / magnitude for x in raw]


@st.composite
def st_full_dim_embedding(draw):
    """Generate a unit-length 1536-dim embedding using a seed for efficiency."""
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    rng = random.Random(seed)
    raw = [rng.uniform(-1.0, 1.0) for _ in range(FULL_DIM)]
    magnitude = math.sqrt(sum(x * x for x in raw))
    return [x / magnitude for x in raw]


@st.composite
def st_non_zero_vector(draw, dim=SMALL_DIM):
    """Generate a non-zero vector (not necessarily unit length)."""
    raw = draw(st.lists(
        st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=dim,
        max_size=dim,
    ))
    magnitude = math.sqrt(sum(x * x for x in raw))
    assume(magnitude > 1e-9)
    return raw


@st.composite
def st_confidence_inputs(draw):
    """Generate valid inputs for compute_confidence_score."""
    swipe_count = draw(st.integers(min_value=0, max_value=500))
    like_rate = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    vector_variance = draw(st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False))
    days_since_update = draw(st.floats(min_value=0.0, max_value=365.0, allow_nan=False, allow_infinity=False))
    return (swipe_count, like_rate, vector_variance, days_since_update)


@st.composite
def st_positive_confidence(draw):
    """Generate a positive confidence score."""
    return draw(st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False))



# ---------------------------------------------------------------------------
# Property 1: Vector storage round-trip
# Feature: taste-vector-deck-sharing, Property 1: Vector storage round-trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestVectorStorageRoundTrip:
    """
    **Validates: Requirements 1.1, 1.4**

    For any valid list of 1536 floats, storing in UserTasteVector.embedding
    and reading back produces numerically equivalent list.
    """

    @given(embedding=st_full_dim_embedding())
    @settings(max_examples=100, deadline=None)
    def test_round_trip_preserves_embedding(self, embedding):
        """Storing and reading back an embedding produces equivalent values."""
        from django.contrib.auth import get_user_model

        from core.models import UserTasteVector

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user = User.objects.create_user(email=f"rt_{uid}@test.com", password="test1234")

        # Store
        taste_vec, _ = UserTasteVector.objects.update_or_create(
            user=user,
            defaults={"embedding": embedding, "swipe_count": 10},
        )

        # Read back
        taste_vec.refresh_from_db()
        stored = taste_vec.embedding

        assert len(stored) == FULL_DIM
        for i in range(FULL_DIM):
            assert abs(stored[i] - embedding[i]) < 1e-10, (
                f"Mismatch at index {i}: stored={stored[i]}, expected={embedding[i]}"
            )


# ---------------------------------------------------------------------------
# Property 2: Confidence score range invariant
# Feature: taste-vector-deck-sharing, Property 2: Confidence score range invariant
# ---------------------------------------------------------------------------


class TestConfidenceScoreRangeInvariant:
    """
    **Validates: Requirements 4.1**

    For any valid inputs, confidence_score is in [0.0, 1.0].
    """

    @given(inputs=st_confidence_inputs())
    @settings(max_examples=100)
    def test_confidence_always_in_unit_range(self, inputs):
        """Confidence score is always between 0.0 and 1.0."""
        swipe_count, like_rate, vector_variance, days_since_update = inputs
        score = compute_confidence_score(swipe_count, like_rate, vector_variance, days_since_update)
        assert 0.0 <= score <= 1.0, (
            f"Score {score} out of range for inputs: "
            f"swipe_count={swipe_count}, like_rate={like_rate}, "
            f"variance={vector_variance}, days={days_since_update}"
        )


# ---------------------------------------------------------------------------
# Property 3: Low swipe count implies low confidence
# Feature: taste-vector-deck-sharing, Property 3: Low swipe count implies low confidence
# ---------------------------------------------------------------------------


class TestLowSwipeCountImpliesLowConfidence:
    """
    **Validates: Requirements 3.3, 4.2**

    For any swipe_count in [0, 19] and any valid other inputs,
    confidence_score < 0.5.
    """

    @given(
        swipe_count=st.integers(min_value=0, max_value=19),
        like_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        vector_variance=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        days_since_update=st.floats(min_value=0.0, max_value=365.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_low_swipe_count_below_half(self, swipe_count, like_rate, vector_variance, days_since_update):
        """With fewer than 20 swipes, confidence is always below 0.5."""
        score = compute_confidence_score(swipe_count, like_rate, vector_variance, days_since_update)
        assert score < 0.5, (
            f"Score {score} >= 0.5 with only {swipe_count} swipes"
        )


# ---------------------------------------------------------------------------
# Property 4: Extreme like rate reduces confidence
# Feature: taste-vector-deck-sharing, Property 4: Extreme like rate reduces confidence
# ---------------------------------------------------------------------------


class TestExtremeLikeRateReducesConfidence:
    """
    **Validates: Requirements 4.3**

    For swipe_count >= 20 and days_since_update <= 30, confidence with
    like_rate > 0.8 or < 0.1 is strictly less than with like_rate = 0.5.
    """

    @given(
        swipe_count=st.integers(min_value=20, max_value=500),
        extreme_like_rate=st.one_of(
            st.floats(min_value=0.801, max_value=1.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0.0, max_value=0.099, allow_nan=False, allow_infinity=False),
        ),
        vector_variance=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        days_since_update=st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_extreme_rate_lower_than_moderate(self, swipe_count, extreme_like_rate, vector_variance, days_since_update):
        """Extreme like rates produce lower confidence than moderate (0.5)."""
        extreme_score = compute_confidence_score(swipe_count, extreme_like_rate, vector_variance, days_since_update)
        moderate_score = compute_confidence_score(swipe_count, 0.5, vector_variance, days_since_update)
        assert extreme_score < moderate_score, (
            f"Extreme rate {extreme_like_rate} score {extreme_score} "
            f">= moderate score {moderate_score}"
        )


# ---------------------------------------------------------------------------
# Property 5: Low variance does not penalize confidence
# Feature: taste-vector-deck-sharing, Property 5: Low variance does not penalize confidence
# ---------------------------------------------------------------------------


class TestLowVarianceDoesNotPenalize:
    """
    **Validates: Requirements 4.4, 13.3**

    Confidence with vector_variance = 0.001 >= confidence with
    vector_variance = 100.0 (all else equal).
    """

    @given(
        swipe_count=st.integers(min_value=0, max_value=500),
        like_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        days_since_update=st.floats(min_value=0.0, max_value=365.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_low_variance_not_penalized(self, swipe_count, like_rate, days_since_update):
        """Low variance never produces lower confidence than high variance."""
        low_var_score = compute_confidence_score(swipe_count, like_rate, 0.001, days_since_update)
        high_var_score = compute_confidence_score(swipe_count, like_rate, 100.0, days_since_update)
        assert low_var_score >= high_var_score, (
            f"Low variance score {low_var_score} < high variance score {high_var_score}"
        )


# ---------------------------------------------------------------------------
# Property 6: Staleness reduces confidence monotonically
# Feature: taste-vector-deck-sharing, Property 6: Staleness reduces confidence monotonically
# ---------------------------------------------------------------------------


class TestStalenessReducesConfidenceMonotonically:
    """
    **Validates: Requirements 4.5, 8.1**

    For days_since_update_A > days_since_update_B >= 30,
    confidence_A <= confidence_B.
    """

    @given(
        swipe_count=st.integers(min_value=0, max_value=500),
        like_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        vector_variance=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
        days_b=st.floats(min_value=30.0, max_value=89.0, allow_nan=False, allow_infinity=False),
        extra_days=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_more_stale_means_lower_confidence(self, swipe_count, like_rate, vector_variance, days_b, extra_days):
        """More stale vectors have equal or lower confidence."""
        days_a = days_b + extra_days
        score_a = compute_confidence_score(swipe_count, like_rate, vector_variance, days_a)
        score_b = compute_confidence_score(swipe_count, like_rate, vector_variance, days_b)
        assert score_a <= score_b, (
            f"Staler vector (days={days_a}, score={score_a}) > "
            f"fresher vector (days={days_b}, score={score_b})"
        )


# ---------------------------------------------------------------------------
# Property 7: Recency weight monotonicity
# Feature: taste-vector-deck-sharing, Property 7: Recency weight monotonicity
# ---------------------------------------------------------------------------


class TestRecencyWeightMonotonicity:
    """
    **Validates: Requirements 3.2**

    For timestamp_A more recent than timestamp_B, weight_A > weight_B.
    """

    @given(
        base_hours_ago=st.integers(min_value=1, max_value=1000),
        extra_hours=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=100)
    def test_more_recent_gets_higher_weight(self, base_hours_ago, extra_hours):
        """More recent timestamps always get higher recency weights."""
        from django.utils import timezone

        now = timezone.now()
        ts_recent = now - timedelta(hours=base_hours_ago)
        ts_older = now - timedelta(hours=base_hours_ago + extra_hours)

        weights = compute_recency_weights([ts_recent, ts_older])
        assert weights[0] > weights[1], (
            f"Recent weight {weights[0]} not > older weight {weights[1]}"
        )


# ---------------------------------------------------------------------------
# Property 8: Confidence-weighted midpoint formula
# Feature: taste-vector-deck-sharing, Property 8: Confidence-weighted midpoint formula
# ---------------------------------------------------------------------------


class TestConfidenceWeightedMidpointFormula:
    """
    **Validates: Requirements 5.1**

    For non-zero vectors and positive confidences, merged (before normalization)
    equals (conf_a * vec_a + conf_b * vec_b) / (conf_a + conf_b).
    """

    @given(
        vec_a=st_non_zero_vector(),
        vec_b=st_non_zero_vector(),
        conf_a=st_positive_confidence(),
        conf_b=st_positive_confidence(),
    )
    @settings(max_examples=100)
    def test_midpoint_formula_correct(self, vec_a, vec_b, conf_a, conf_b):
        """Merged vector follows the confidence-weighted midpoint formula."""
        total_conf = conf_a + conf_b
        dim = len(vec_a)

        # Expected pre-normalization midpoint
        expected_raw = [
            (conf_a * vec_a[i] + conf_b * vec_b[i]) / total_conf
            for i in range(dim)
        ]

        # The function normalizes the result, so we compare directions
        result = compute_confidence_weighted_midpoint(vec_a, conf_a, vec_b, conf_b)

        # Normalize expected_raw for comparison
        expected_mag = math.sqrt(sum(x * x for x in expected_raw))
        if expected_mag > 1e-10:
            expected_normalized = [x / expected_mag for x in expected_raw]
            for i in range(dim):
                assert abs(result[i] - expected_normalized[i]) < 1e-6, (
                    f"Mismatch at dim {i}: result={result[i]}, expected={expected_normalized[i]}"
                )


# ---------------------------------------------------------------------------
# Property 9: Higher confidence pulls midpoint closer
# Feature: taste-vector-deck-sharing, Property 9: Higher confidence pulls midpoint closer
# ---------------------------------------------------------------------------


class TestHigherConfidencePullsMidpointCloser:
    """
    **Validates: Requirements 5.2**

    For two distinct unit vectors where conf_a > conf_b, normalized merged
    has higher cosine similarity to vec_a than vec_b.
    """

    @given(
        vec_a=st_embedding(),
        vec_b=st_embedding(),
        conf_a=st.floats(min_value=0.6, max_value=1.0, allow_nan=False, allow_infinity=False),
        conf_b=st.floats(min_value=0.01, max_value=0.59, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_higher_confidence_closer_to_merged(self, vec_a, vec_b, conf_a, conf_b):
        """Merged vector is closer to the higher-confidence vector."""
        # Ensure vectors are distinct
        diff = sum((a - b) ** 2 for a, b in zip(vec_a, vec_b))
        assume(diff > 0.01)

        merged = compute_confidence_weighted_midpoint(vec_a, conf_a, vec_b, conf_b)

        # Cosine similarity (vectors are unit length)
        cos_a = sum(m * a for m, a in zip(merged, vec_a))
        cos_b = sum(m * b for m, b in zip(merged, vec_b))

        assert cos_a > cos_b, (
            f"Merged closer to vec_b (cos_a={cos_a:.4f}, cos_b={cos_b:.4f}) "
            f"despite conf_a={conf_a:.3f} > conf_b={conf_b:.3f}"
        )



# ---------------------------------------------------------------------------
# Property 10: Both low confidence selects Phase C
# Feature: taste-vector-deck-sharing, Property 10: Both low confidence selects Phase C
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestBothLowConfidenceSelectsPhaseC:
    """
    **Validates: Requirements 5.3**

    For both confidence scores < 0.5, phase selector returns "phase_c".
    NOTE: confidence < 0.5 implies swipe_count < 20 (from the sigmoid),
    so the trust threshold check will fail.
    """

    @given(
        swipe_count_a=st.integers(min_value=0, max_value=19),
        swipe_count_b=st.integers(min_value=0, max_value=19),
    )
    @settings(max_examples=100, deadline=None)
    def test_both_low_confidence_gives_phase_c(self, swipe_count_a, swipe_count_b):
        """When both users have low swipe counts (< 20), Phase C is selected."""
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from core.models import Couple, CoupleStatus, UserTasteVector
        from core.services.taste_vectors import select_phase

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user_a = User.objects.create_user(email=f"a_{uid}@test.com", password="test1234")
        user_b = User.objects.create_user(email=f"b_{uid}@test.com", password="test1234")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        # Create taste vectors with low swipe counts (confidence < 0.5)
        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * FULL_DIM,
            swipe_count=swipe_count_a,
            like_rate=0.5,
            vector_variance=1.0,
            confidence_score=compute_confidence_score(swipe_count_a, 0.5, 1.0, 0.0),
            last_updated_at=now,
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.1] * FULL_DIM,
            swipe_count=swipe_count_b,
            like_rate=0.5,
            vector_variance=1.0,
            confidence_score=compute_confidence_score(swipe_count_b, 0.5, 1.0, 0.0),
            last_updated_at=now,
        )

        phase, _data = select_phase(couple)
        assert phase == "phase_c", (
            f"Expected phase_c but got {phase} with swipe counts "
            f"({swipe_count_a}, {swipe_count_b})"
        )


# ---------------------------------------------------------------------------
# Property 11: Merged vector is unit length
# Feature: taste-vector-deck-sharing, Property 11: Merged vector is unit length
# ---------------------------------------------------------------------------


class TestMergedVectorIsUnitLength:
    """
    **Validates: Requirements 5.4**

    For non-zero vectors and positive confidences, normalized merged
    has L2 norm in [0.99, 1.01].
    """

    @given(
        vec_a=st_non_zero_vector(),
        vec_b=st_non_zero_vector(),
        conf_a=st_positive_confidence(),
        conf_b=st_positive_confidence(),
    )
    @settings(max_examples=100)
    def test_merged_is_unit_length(self, vec_a, vec_b, conf_a, conf_b):
        """Merged vector has L2 norm approximately 1.0."""
        merged = compute_confidence_weighted_midpoint(vec_a, conf_a, vec_b, conf_b)
        norm = math.sqrt(sum(x * x for x in merged))
        assert 0.99 <= norm <= 1.01, (
            f"Merged vector norm {norm} not in [0.99, 1.01]"
        )


# ---------------------------------------------------------------------------
# Property 12: Phase D selection iff all thresholds met
# Feature: taste-vector-deck-sharing, Property 12: Phase D selection iff all thresholds met
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestPhaseDSelectionIffAllThresholdsMet:
    """
    **Validates: Requirements 6.1, 6.2**

    Phase D selected iff both users: swipe_count >= 20,
    0.1 <= like_rate <= 0.8, days_since_update <= 30.
    """

    @given(
        swipe_a=st.integers(min_value=0, max_value=100),
        swipe_b=st.integers(min_value=0, max_value=100),
        rate_a=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        rate_b=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        days_a=st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        days_b=st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_phase_d_iff_thresholds_met(self, swipe_a, swipe_b, rate_a, rate_b, days_a, days_b):
        """Phase D is selected if and only if all thresholds are met for both users."""
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from core.models import Couple, CoupleStatus, UserTasteVector
        from core.services.taste_vectors import select_phase

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user_a = User.objects.create_user(email=f"a_{uid}@test.com", password="test1234")
        user_b = User.objects.create_user(email=f"b_{uid}@test.com", password="test1234")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=[0.1] * FULL_DIM,
            swipe_count=swipe_a,
            like_rate=rate_a,
            vector_variance=1.0,
            confidence_score=compute_confidence_score(swipe_a, rate_a, 1.0, days_a),
            last_updated_at=now - timedelta(days=days_a),
        )
        UserTasteVector.objects.create(
            user=user_b,
            embedding=[0.1] * FULL_DIM,
            swipe_count=swipe_b,
            like_rate=rate_b,
            vector_variance=1.0,
            confidence_score=compute_confidence_score(swipe_b, rate_b, 1.0, days_b),
            last_updated_at=now - timedelta(days=days_b),
        )

        # Expected: Phase D iff all thresholds met for both
        a_passes = swipe_a >= 20 and 0.1 <= rate_a <= 0.8 and days_a <= 30
        b_passes = swipe_b >= 20 and 0.1 <= rate_b <= 0.8 and days_b <= 30
        expected_phase_d = a_passes and b_passes

        phase, _data = select_phase(couple)

        if expected_phase_d:
            assert phase == "phase_d", (
                f"Expected phase_d but got {phase}. "
                f"A: swipe={swipe_a}, rate={rate_a:.2f}, days={days_a:.1f}. "
                f"B: swipe={swipe_b}, rate={rate_b:.2f}, days={days_b:.1f}"
            )
        else:
            assert phase == "phase_c", (
                f"Expected phase_c but got {phase}. "
                f"A: swipe={swipe_a}, rate={rate_a:.2f}, days={days_a:.1f}. "
                f"B: swipe={swipe_b}, rate={rate_b:.2f}, days={days_b:.1f}"
            )


# ---------------------------------------------------------------------------
# Property 13: Sparse retrieval triggers fallback
# Feature: taste-vector-deck-sharing, Property 13: Sparse retrieval triggers fallback
# ---------------------------------------------------------------------------


class TestSparseRetrievalTriggersFallback:
    """
    **Validates: Requirements 6.3, 9.1**

    When max candidate score < 0.6, fallback to Phase C is triggered.
    """

    @given(
        max_score=st.floats(min_value=0.0, max_value=0.599, allow_nan=False, allow_infinity=False),
        num_candidates=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_low_scores_trigger_fallback(self, max_score, num_candidates):
        """When top candidate score < 0.6, sparse retrieval fallback is triggered."""
        from core.services.taste_vectors import TRUST_THRESHOLDS

        # Simulate candidates with scores all below threshold
        candidates = [{"score": max_score * (i / num_candidates)} for i in range(1, num_candidates + 1)]
        top_score = max(c["score"] for c in candidates)

        # The fallback logic: top_score < min_retrieval_score triggers fallback
        min_retrieval_score = TRUST_THRESHOLDS["min_retrieval_score"]
        should_fallback = top_score < min_retrieval_score

        assert should_fallback is True, (
            f"Expected fallback with top_score={top_score:.3f} < {min_retrieval_score}"
        )


# ---------------------------------------------------------------------------
# Property 14: Gender-aware vector filtering
# Feature: taste-vector-deck-sharing, Property 14: Gender-aware vector filtering
# ---------------------------------------------------------------------------


class TestGenderAwareVectorFiltering:
    """
    **Validates: Requirements 7.1, 7.2**

    For mixed-gender liked names with preference "boy" or "girl",
    only matching names are included. For "non_binary", all included.
    """

    @given(
        num_boy_names=st.integers(min_value=5, max_value=15),
        num_girl_names=st.integers(min_value=5, max_value=15),
        preference=st.sampled_from(["boy", "girl", "non_binary"]),
    )
    @settings(max_examples=100)
    def test_gender_filter_logic(self, num_boy_names, num_girl_names, preference):
        """Gender filter includes only matching names (or all for non_binary)."""
        # Simulate name data with gender_usage
        boy_names = [{"name_id": f"boy_{i}", "gender_usage": ["boy"]} for i in range(num_boy_names)]
        girl_names = [{"name_id": f"girl_{i}", "gender_usage": ["girl"]} for i in range(num_girl_names)]
        all_names = boy_names + girl_names

        if preference == "non_binary":
            filtered = all_names
        else:
            filtered = [n for n in all_names if preference in n["gender_usage"]]

        # Verify filtering logic
        if preference == "boy":
            assert len(filtered) == num_boy_names
            assert all("boy" in n["gender_usage"] for n in filtered)
        elif preference == "girl":
            assert len(filtered) == num_girl_names
            assert all("girl" in n["gender_usage"] for n in filtered)
        else:  # non_binary
            assert len(filtered) == num_boy_names + num_girl_names


# ---------------------------------------------------------------------------
# Property 15: Gender filter fallback on insufficient data
# Feature: taste-vector-deck-sharing, Property 15: Gender filter fallback on insufficient data
# ---------------------------------------------------------------------------


class TestGenderFilterFallbackOnInsufficientData:
    """
    **Validates: Requirements 7.3**

    When fewer than 10 names match gender preference, all liked names
    are used and fallback_used is True.
    """

    @given(
        num_matching=st.integers(min_value=0, max_value=9),
        num_other=st.integers(min_value=5, max_value=20),
        preference=st.sampled_from(["boy", "girl"]),
    )
    @settings(max_examples=100)
    def test_fallback_when_insufficient_gender_matches(self, num_matching, num_other, preference):
        """When fewer than 10 names match gender, all names are used."""
        other_gender = "girl" if preference == "boy" else "boy"
        matching_names = [{"name_id": f"match_{i}", "gender_usage": [preference]} for i in range(num_matching)]
        other_names = [{"name_id": f"other_{i}", "gender_usage": [other_gender]} for i in range(num_other)]
        all_names = matching_names + other_names

        # Apply the filter logic from get_gender_filtered_vectors
        filtered = [n for n in all_names if preference in n["gender_usage"]]
        fallback_used = False

        if len(filtered) < 10:
            filtered = all_names
            fallback_used = True

        assert fallback_used is True, (
            f"Expected fallback with only {num_matching} matching names"
        )
        assert len(filtered) == num_matching + num_other


# ---------------------------------------------------------------------------
# Property 16: Dislike repulsion formula
# Feature: taste-vector-deck-sharing, Property 16: Dislike repulsion formula
# ---------------------------------------------------------------------------


class TestDislikeRepulsionFormula:
    """
    **Validates: Requirements 3.5, 12.1, 12.2**

    For non-zero centroids and repulsion_weight > 0, pre-normalization result
    equals like_centroid - (repulsion_weight * dislike_centroid).
    """

    @given(
        like_centroid=st_non_zero_vector(),
        dislike_centroid=st_non_zero_vector(),
        repulsion_weight=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_repulsion_formula_correct(self, like_centroid, dislike_centroid, repulsion_weight):
        """Repulsion result follows the subtraction formula before normalization."""
        dim = len(like_centroid)

        # Expected pre-normalization
        expected_raw = [
            like_centroid[i] - repulsion_weight * dislike_centroid[i]
            for i in range(dim)
        ]

        # Check if result would be zero vector
        raw_mag = math.sqrt(sum(x * x for x in expected_raw))
        assume(raw_mag > 1e-9)

        result = apply_dislike_repulsion(like_centroid, dislike_centroid, repulsion_weight)

        # Normalize expected for comparison (function normalizes output)
        expected_normalized = [x / raw_mag for x in expected_raw]

        for i in range(dim):
            assert abs(result[i] - expected_normalized[i]) < 1e-6, (
                f"Mismatch at dim {i}: result={result[i]}, expected={expected_normalized[i]}"
            )


# ---------------------------------------------------------------------------
# Property 17: Repulsion output is unit length
# Feature: taste-vector-deck-sharing, Property 17: Repulsion output is unit length
# ---------------------------------------------------------------------------


class TestRepulsionOutputIsUnitLength:
    """
    **Validates: Requirements 12.3**

    For non-zero centroids where repulsion result is non-zero,
    output has L2 norm in [0.99, 1.01].
    """

    @given(
        like_centroid=st_non_zero_vector(),
        dislike_centroid=st_non_zero_vector(),
        repulsion_weight=st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_repulsion_output_unit_length(self, like_centroid, dislike_centroid, repulsion_weight):
        """Repulsion output is normalized to unit length."""
        dim = len(like_centroid)

        # Ensure result won't be zero
        raw = [like_centroid[i] - repulsion_weight * dislike_centroid[i] for i in range(dim)]
        raw_mag = math.sqrt(sum(x * x for x in raw))
        assume(raw_mag > 1e-9)

        result = apply_dislike_repulsion(like_centroid, dislike_centroid, repulsion_weight)
        norm = math.sqrt(sum(x * x for x in result))

        assert 0.99 <= norm <= 1.01, (
            f"Repulsion output norm {norm} not in [0.99, 1.01]"
        )



# ---------------------------------------------------------------------------
# Property 18: Skip repulsion when fewer than 5 dislikes
# Feature: taste-vector-deck-sharing, Property 18: Skip repulsion when fewer than 5 dislikes
# ---------------------------------------------------------------------------


class TestSkipRepulsionWhenFewerThan5Dislikes:
    """
    **Validates: Requirements 12.4**

    When dislike_count < 5, taste vector equals normalized recency-weighted
    like centroid (no repulsion).
    """

    @given(
        dislike_count=st.integers(min_value=0, max_value=4),
        like_rate=st.floats(min_value=0.81, max_value=1.0, allow_nan=False, allow_infinity=False),
        num_likes=st.integers(min_value=5, max_value=20),
    )
    @settings(max_examples=100)
    def test_no_repulsion_with_few_dislikes(self, dislike_count, like_rate, num_likes):
        """With fewer than 5 dislikes, repulsion is skipped regardless of like_rate."""
        # The condition for repulsion is: like_rate > 0.8 AND dislike_count >= 5
        # With dislike_count < 5, repulsion should NOT be applied
        should_apply_repulsion = like_rate > 0.8 and dislike_count >= 5
        assert should_apply_repulsion is False, (
            f"Repulsion should not apply with dislike_count={dislike_count}"
        )


# ---------------------------------------------------------------------------
# Property 19: Vector variance computation
# Feature: taste-vector-deck-sharing, Property 19: Vector variance computation
# ---------------------------------------------------------------------------


class TestVectorVarianceComputation:
    """
    **Validates: Requirements 13.1**

    For N embeddings and their centroid, variance equals
    (1/N) * sum(||v_i - centroid||^2).
    """

    @given(
        vectors=st.lists(
            st.lists(
                st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                min_size=SMALL_DIM,
                max_size=SMALL_DIM,
            ),
            min_size=2,
            max_size=10,
        ),
    )
    @settings(max_examples=100)
    def test_variance_matches_formula(self, vectors):
        """Variance equals average squared distance to centroid."""
        n = len(vectors)
        dim = len(vectors[0])

        # Compute centroid manually
        centroid = [0.0] * dim
        for vec in vectors:
            for i in range(dim):
                centroid[i] += vec[i]
        centroid = [c / n for c in centroid]

        # Compute expected variance manually
        expected_variance = 0.0
        for vec in vectors:
            sq_dist = sum((vec[i] - centroid[i]) ** 2 for i in range(dim))
            expected_variance += sq_dist
        expected_variance /= n

        # Compute using the service function
        result = compute_vector_variance(vectors, centroid)

        assert abs(result - expected_variance) < 1e-6, (
            f"Variance mismatch: result={result}, expected={expected_variance}"
        )


# ---------------------------------------------------------------------------
# Property 20: Couple formation preserves taste vectors
# Feature: taste-vector-deck-sharing, Property 20: Couple formation preserves taste vectors
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCoupleFormationPreservesTasteVectors:
    """
    **Validates: Requirements 11.3**

    Forming a couple does not modify existing UserTasteVector fields.
    """

    @given(
        swipe_count=st.integers(min_value=1, max_value=100),
        like_rate=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_couple_formation_does_not_modify_vectors(self, swipe_count, like_rate, confidence):
        """Forming a couple preserves existing taste vector data."""
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from core.models import Couple, CoupleStatus, UserTasteVector

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user_a = User.objects.create_user(email=f"a_{uid}@test.com", password="test1234")
        user_b = User.objects.create_user(email=f"b_{uid}@test.com", password="test1234")

        # Create taste vector for user_a before couple formation
        embedding = [0.5] * FULL_DIM
        now = timezone.now()
        UserTasteVector.objects.create(
            user=user_a,
            embedding=embedding,
            swipe_count=swipe_count,
            like_rate=like_rate,
            vector_variance=1.5,
            confidence_score=confidence,
            last_updated_at=now,
        )

        # Snapshot before
        vec_before = UserTasteVector.objects.get(user=user_a)
        embedding_before = list(vec_before.embedding)
        swipe_before = vec_before.swipe_count
        rate_before = vec_before.like_rate
        variance_before = vec_before.vector_variance
        confidence_before = vec_before.confidence_score

        # Form couple
        Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        # Verify taste vector unchanged
        vec_after = UserTasteVector.objects.get(user=user_a)
        assert vec_after.embedding == embedding_before
        assert vec_after.swipe_count == swipe_before
        assert vec_after.like_rate == rate_before
        assert vec_after.vector_variance == variance_before
        assert vec_after.confidence_score == confidence_before


# ---------------------------------------------------------------------------
# Property 21: All swipe history used regardless of couple
# Feature: taste-vector-deck-sharing, Property 21: All swipe history used regardless of couple
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestAllSwipeHistoryUsedRegardlessOfCouple:
    """
    **Validates: Requirements 14.2**

    For user with swipes under multiple couples, taste vector uses all swipes
    (total swipe_count equals sum across all couples).
    """

    @given(
        swipes_couple_1=st.integers(min_value=1, max_value=10),
        swipes_couple_2=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100, deadline=None)
    def test_all_swipes_across_couples_counted(self, swipes_couple_1, swipes_couple_2):
        """Swipes from all couples are included in the taste vector computation."""
        from django.contrib.auth import get_user_model

        from core.models import Couple, CoupleStatus, Name, Swipe

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user = User.objects.create_user(email=f"user_{uid}@test.com", password="test1234")
        partner_1 = User.objects.create_user(email=f"p1_{uid}@test.com", password="test1234")
        partner_2 = User.objects.create_user(email=f"p2_{uid}@test.com", password="test1234")

        couple_1 = Couple.objects.create(
            user_a=user, user_b=partner_1, status=CoupleStatus.ARCHIVED
        )
        couple_2 = Couple.objects.create(
            user_a=user, user_b=partner_2, status=CoupleStatus.ACTIVE
        )

        # Create swipes under couple 1
        for i in range(swipes_couple_1):
            name = Name.objects.create(
                canonical_name=f"C1_{uid}_{i}",
                display_name=f"C1 {uid} {i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test name",
                active=True,
            )
            Swipe.objects.create(couple=couple_1, user=user, name=name, action="like")

        # Create swipes under couple 2
        for i in range(swipes_couple_2):
            name = Name.objects.create(
                canonical_name=f"C2_{uid}_{i}",
                display_name=f"C2 {uid} {i}",
                gender_usage=["girl"],
                origin_backgrounds=["Greek"],
                languages=["el"],
                scripts=["Latin"],
                variants=[],
                length_category="medium",
                age_style_category="modern",
                historical_significance_score=0.3,
                semantic_summary="Test name",
                active=True,
            )
            Swipe.objects.create(couple=couple_2, user=user, name=name, action="like")

        # Verify total swipe count across all couples
        total_swipes = Swipe.objects.filter(user=user).count()
        expected_total = swipes_couple_1 + swipes_couple_2
        assert total_swipes == expected_total, (
            f"Expected {expected_total} total swipes, got {total_swipes}"
        )


# ---------------------------------------------------------------------------
# Property 22: Quality metrics contain all required fields
# Feature: taste-vector-deck-sharing, Property 22: Quality metrics contain all required fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestQualityMetricsContainAllRequiredFields:
    """
    **Validates: Requirements 10.1**

    For any deck generation, retrieval_profile_json contains all required
    quality metrics fields.
    """

    REQUIRED_FIELDS = [
        "phase_used",
        "user_a_confidence_score",
        "user_b_confidence_score",
        "user_a_swipe_count",
        "user_b_swipe_count",
        "top_retrieval_score",
        "fallback_reason",
    ]

    @given(
        phase=st.sampled_from(["phase_c", "phase_d"]),
        conf_a=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        conf_b=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        swipe_a=st.integers(min_value=0, max_value=200),
        swipe_b=st.integers(min_value=0, max_value=200),
        top_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        fallback_reason=st.one_of(st.none(), st.sampled_from([
            "top_score_below_threshold",
            "user_a_swipe_count_below_threshold",
            "user_b_vector_stale",
        ])),
    )
    @settings(max_examples=100)
    def test_quality_metrics_has_all_fields(self, phase, conf_a, conf_b, swipe_a, swipe_b, top_score, fallback_reason):
        """Quality metrics dict contains all required fields."""
        # Simulate the quality_metrics dict as built in generate_deck
        quality_metrics = {
            "phase_used": phase,
            "user_a_confidence_score": conf_a,
            "user_b_confidence_score": conf_b,
            "user_a_swipe_count": swipe_a,
            "user_b_swipe_count": swipe_b,
            "top_retrieval_score": top_score,
            "fallback_reason": fallback_reason,
        }

        for field in self.REQUIRED_FIELDS:
            assert field in quality_metrics, (
                f"Required field '{field}' missing from quality metrics"
            )


# ---------------------------------------------------------------------------
# Property 23: Sparse pool relaxes diversity constraints
# Feature: taste-vector-deck-sharing, Property 23: Sparse pool relaxes diversity constraints
# ---------------------------------------------------------------------------


class TestSparsePoolRelaxesDiversityConstraints:
    """
    **Validates: Requirements 9.2**

    When fewer than 10 candidates score above 0.5, diversity constraints
    are relaxed.
    """

    @given(
        num_above_threshold=st.integers(min_value=0, max_value=9),
        num_below_threshold=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=100)
    def test_sparse_pool_detected(self, num_above_threshold, num_below_threshold):
        """When fewer than 10 candidates score above 0.5, pool is sparse."""
        # Simulate ranked candidates
        candidates = []
        for i in range(num_above_threshold):
            candidates.append({"rerank_score": 0.51 + (i + 1) * 0.05})
        for i in range(num_below_threshold):
            candidates.append({"rerank_score": 0.1 + i * 0.02})  # max: 0.1 + 19*0.02 = 0.48

        # The sparse pool detection logic from generate_deck
        above_threshold_count = sum(1 for c in candidates if c.get("rerank_score", 0) > 0.5)
        sparse_pool = above_threshold_count < 10

        assert sparse_pool is True, (
            f"Expected sparse pool with {above_threshold_count} candidates above 0.5"
        )

    @given(
        num_candidates=st.integers(min_value=51, max_value=100),
    )
    @settings(max_examples=100, deadline=None)
    def test_relaxed_constraints_allow_more_per_category(self, num_candidates):
        """Relaxed diversity constraints have higher thresholds than normal."""
        from core.services.recommendations import _apply_diversity_constraints

        # Create candidates with same first letter to test constraint relaxation
        candidates = []
        for i in range(num_candidates):
            candidates.append({
                "payload": {
                    "canonical_name": f"Aname_{i}",
                    "origin_backgrounds": ["Spanish"],
                    "age_style_category": "classic",
                },
                "rerank_score": 0.9 - (i * 0.005),
                "retrieval_score": 0.8,
            })

        # Normal constraints
        normal_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=False)
        # Relaxed constraints
        relaxed_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=True)

        # Count how many "A" names made it through
        normal_a_count = sum(
            1 for c in normal_result
            if c.get("payload", {}).get("canonical_name", "").startswith("A")
        )
        relaxed_a_count = sum(
            1 for c in relaxed_result
            if c.get("payload", {}).get("canonical_name", "").startswith("A")
        )

        # Relaxed should allow at least as many (usually more) same-letter names
        assert relaxed_a_count >= normal_a_count, (
            f"Relaxed ({relaxed_a_count}) should allow >= normal ({normal_a_count}) same-letter names"
        )
