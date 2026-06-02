"""Taste vector computation service for BabyBase.

Computes, updates, and queries per-user taste vectors from swipe history.
Supports recency-weighted averaging, dislike repulsion, confidence scoring,
and confidence-weighted midpoint merging for couples.
"""

import logging
import math
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)

TRUST_THRESHOLDS = {
    "min_swipe_count": 20,
    "min_like_rate": 0.1,
    "max_like_rate": 0.8,
    "max_staleness_days": 30,
    "min_retrieval_score": 0.6,
}

# Recompute a user's taste vector once every this many new swipes, rather than
# on every individual swipe. Recomputation fetches all of the user's liked
# embeddings from Qdrant, so batching keeps the swipe path cheap while still
# refreshing the vector often enough to cross the Phase D trust threshold
# (min_swipe_count = 20) on a batch boundary.
TASTE_VECTOR_BATCH_SIZE = 5


def check_trust_thresholds(taste_vector) -> tuple[bool, str | None]:
    """
    Check if a single user's taste vector meets all trust thresholds.

    Returns (True, None) if all pass, or (False, "reason_string") if any fail.
    """
    from core.services.embeddings import EMBEDDING_DIM

    if len(taste_vector.embedding or []) != EMBEDDING_DIM:
        return (False, "embedding_dimension_mismatch")

    if taste_vector.swipe_count < TRUST_THRESHOLDS["min_swipe_count"]:
        return (False, "swipe_count_below_threshold")

    if taste_vector.like_rate < TRUST_THRESHOLDS["min_like_rate"]:
        return (False, "like_rate_below_threshold")

    if taste_vector.like_rate > TRUST_THRESHOLDS["max_like_rate"]:
        return (False, "like_rate_above_threshold")

    now = timezone.now()
    if taste_vector.last_updated_at is None:
        return (False, "vector_stale")

    days_since_update = (now - taste_vector.last_updated_at).total_seconds() / 86400.0
    if days_since_update > TRUST_THRESHOLDS["max_staleness_days"]:
        return (False, "vector_stale")

    return (True, None)


def select_phase(couple) -> tuple[str, dict]:
    """
    Determine whether to use Phase C or Phase D for deck generation.

    Fetches UserTasteVector for both users in the couple, checks trust thresholds,
    and returns the appropriate phase with associated data.

    Returns:
        ("phase_d", {"vec_a": [...], "conf_a": 0.8, "vec_b": [...], "conf_b": 0.7})
        or
        ("phase_c", {"reason": "user_a_swipe_count_below_threshold"})
    """
    from core.models import UserTasteVector

    # Fetch taste vector for user_a
    try:
        vec_a = UserTasteVector.objects.get(user=couple.user_a)
    except UserTasteVector.DoesNotExist:
        logger.info("No taste vector for user_a %s, selecting Phase C", couple.user_a_id)
        return ("phase_c", {"reason": "user_a_no_taste_vector"})

    # Fetch taste vector for user_b
    if couple.user_b is None:
        logger.info("Couple %s has no user_b, selecting Phase C", couple.id)
        return ("phase_c", {"reason": "user_b_no_taste_vector"})

    try:
        vec_b = UserTasteVector.objects.get(user=couple.user_b)
    except UserTasteVector.DoesNotExist:
        logger.info("No taste vector for user_b %s, selecting Phase C", couple.user_b_id)
        return ("phase_c", {"reason": "user_b_no_taste_vector"})

    # Check trust thresholds for user_a
    passes_a, reason_a = check_trust_thresholds(vec_a)
    if not passes_a:
        logger.info(
            "User_a %s failed trust threshold: %s, selecting Phase C",
            couple.user_a_id,
            reason_a,
        )
        return ("phase_c", {"reason": f"user_a_{reason_a}"})

    # Check trust thresholds for user_b
    passes_b, reason_b = check_trust_thresholds(vec_b)
    if not passes_b:
        logger.info(
            "User_b %s failed trust threshold: %s, selecting Phase C",
            couple.user_b_id,
            reason_b,
        )
        return ("phase_c", {"reason": f"user_b_{reason_b}"})

    # Both pass — return Phase D with vectors and confidence scores
    return (
        "phase_d",
        {
            "vec_a": vec_a.embedding,
            "conf_a": vec_a.confidence_score,
            "vec_b": vec_b.embedding,
            "conf_b": vec_b.confidence_score,
        },
    )


def compute_confidence_weighted_midpoint(
    vec_a: list[float],
    conf_a: float,
    vec_b: list[float],
    conf_b: float,
) -> list[float]:
    """
    Compute confidence-weighted midpoint of two taste vectors.

    merged = (conf_a * vec_a + conf_b * vec_b) / (conf_a + conf_b)
    Result is normalized to unit length.

    Precondition: conf_a + conf_b > 0 (caller ensures this via phase selection).

    Args:
        vec_a: First user's taste vector.
        conf_a: First user's confidence score.
        vec_b: Second user's taste vector.
        conf_b: Second user's confidence score.

    Returns:
        The unit-length confidence-weighted midpoint vector.
    """
    total_conf = conf_a + conf_b
    dim = len(vec_a)
    merged = [
        (conf_a * vec_a[i] + conf_b * vec_b[i]) / total_conf
        for i in range(dim)
    ]
    return normalize_vector(merged)


def compute_taste_vector(user):
    """
    Recompute the user's taste vector from all swipe history across all couples.

    Steps:
    1. Determine gender preference from the user's couple onboarding
    2. Fetch liked name embeddings filtered by gender preference
    3. Apply recency weighting (exponential decay)
    4. Compute like centroid
    5. If like_rate > 0.8 and dislike_count >= 5: apply dislike repulsion
    6. Normalize to unit length
    7. Compute vector_variance
    8. Compute confidence_score (reduced if gender filter fell back)
    9. Persist to UserTasteVector

    Returns the updated UserTasteVector instance, or None if no valid vector can be computed.
    """
    from core.models import OnboardingResponse, Swipe, UserTasteVector
    from core.services.onboarding import _fetch_vectors_for_name_ids

    # Step 1: Determine gender preference from the user's most recent onboarding
    gender_preference = "non_binary"  # Default: include all names
    latest_onboarding = (
        OnboardingResponse.objects.filter(user=user)
        .order_by("-created_at")
        .first()
    )
    if latest_onboarding and latest_onboarding.baby_gender_preference:
        gender_preference = latest_onboarding.baby_gender_preference

    # Step 2: Fetch gender-filtered liked name embeddings
    liked_vectors, liked_timestamps, gender_fallback_used = get_gender_filtered_vectors(
        user, gender_preference
    )

    if not liked_vectors:
        logger.info(
            "🧠 [taste] No liked-name vectors yet for user=%s (gender_pref=%s) — taste vector unchanged",
            user.id, gender_preference,
        )
        return None

    # Fetch dislike info separately for repulsion check
    all_swipes = Swipe.objects.filter(user=user)
    total_likes = all_swipes.filter(action="like").count()
    disliked_name_ids = list(
        all_swipes.filter(action="dislike").values_list("name_id", flat=True)
    )
    disliked_timestamps_qs = list(
        all_swipes.filter(action="dislike").values_list("created_at", flat=True)
    )
    dislike_count = len(disliked_name_ids)
    total_swipes = all_swipes.count()
    like_rate = total_likes / total_swipes if total_swipes > 0 else 0.0

    logger.info(
        "🧠 [taste] user=%s: %d liked vector(s) from %d swipes (like_rate=%.2f), recency-weighting (14d half-life)",
        user.id, len(liked_vectors), total_swipes, like_rate,
    )

    # Step 3: Apply recency weighting
    like_weights = compute_recency_weights(liked_timestamps[: len(liked_vectors)])

    # Step 4: Compute like centroid
    like_centroid = compute_weighted_centroid(liked_vectors, like_weights)

    # Step 5: Apply dislike repulsion if conditions met
    final_vector = like_centroid
    if like_rate > 0.8 and dislike_count >= 5:
        try:
            disliked_vectors = _fetch_vectors_for_name_ids([str(nid) for nid in disliked_name_ids])
        except Exception:
            logger.exception("Qdrant unreachable fetching disliked vectors for user %s", user.id)
            disliked_vectors = []

        if disliked_vectors:
            dislike_weights = compute_recency_weights(disliked_timestamps_qs[: len(disliked_vectors)])
            dislike_centroid = compute_weighted_centroid(disliked_vectors, dislike_weights)
            final_vector = apply_dislike_repulsion(like_centroid, dislike_centroid)
            logger.info(
                "🧠 [taste] user=%s: high like_rate (%.2f) with %d dislikes — repelling away from disliked names",
                user.id, like_rate, dislike_count,
            )

    # Step 6: Normalize to unit length
    final_vector = normalize_vector(final_vector)

    # Step 7: Compute vector_variance
    vector_variance = compute_vector_variance(liked_vectors, like_centroid)

    # Step 8: Compute confidence_score (reduced if gender filter fell back)
    now = timezone.now()
    days_since_update = 0.0  # Fresh computation
    confidence = compute_confidence_score(
        swipe_count=total_swipes,
        like_rate=like_rate,
        vector_variance=vector_variance,
        days_since_update=days_since_update,
    )

    # Reduce confidence when gender filter fell back to all names (less targeted signal)
    if gender_fallback_used:
        confidence *= 0.8
        logger.info(
            "Gender filter fallback used for user %s, confidence reduced to %.3f",
            user.id,
            confidence,
        )

    # Step 9: Persist to UserTasteVector (create or update)
    taste_vector, _created = UserTasteVector.objects.update_or_create(
        user=user,
        defaults={
            "embedding": final_vector,
            "swipe_count": total_swipes,
            "like_rate": like_rate,
            "vector_variance": vector_variance,
            "confidence_score": confidence,
            "last_updated_at": now,
        },
    )

    logger.info(
        "🧠 [taste] user=%s vector updated: swipes=%d like_rate=%.2f confidence=%.3f gender_filter=%s",
        user.id,
        total_swipes,
        like_rate,
        confidence,
        gender_preference,
    )

    passes, reason = check_trust_thresholds(taste_vector)
    if passes:
        logger.info(
            "🧠 [taste] user=%s now TRUSTED for Phase D personalization (confidence=%.3f)",
            user.id, confidence,
        )
    else:
        logger.info(
            "🧠 [taste] user=%s not yet trusted for Phase D (reason=%s) — decks stay on Phase C",
            user.id, reason,
        )

    return taste_vector


def maybe_recompute_taste_vector(user) -> bool:
    """Recompute a user's taste vector on swipe-batch boundaries.

    Intended to be called from the swipe flow after a new swipe is recorded.
    To avoid fetching every liked embedding from Qdrant on every swipe, the
    vector is only recomputed when the user's total swipe count is a positive
    multiple of ``TASTE_VECTOR_BATCH_SIZE``.

    This never raises into the caller: any failure (e.g. Qdrant unreachable) is
    logged and swallowed so a recompute problem can never break a swipe.

    Returns True if a recompute was attempted, False if it was skipped.
    """
    from core.models import Swipe

    swipe_count = Swipe.objects.filter(user=user).count()
    if swipe_count == 0 or swipe_count % TASTE_VECTOR_BATCH_SIZE != 0:
        return False

    logger.info(
        "🧠 [taste] Swipe batch boundary hit (%d swipes) for user=%s — recomputing taste vector",
        swipe_count, user.id,
    )
    try:
        compute_taste_vector(user)
    except Exception:
        logger.exception("🧠 [taste] Failed to recompute taste vector for user %s", user.id)
    return True


def compute_confidence_score(
    swipe_count: int,
    like_rate: float,
    vector_variance: float,
    days_since_update: float,
) -> float:
    """
    Compute composite confidence score in [0.0, 1.0].

    Combines swipe volume, like-rate quality, and vector staleness into a
    conservative trust score used for Phase D eligibility.

    Args:
        swipe_count: Total number of swipes.
        like_rate: Ratio of likes to total swipes.
        vector_variance: Average squared distance to centroid.
        days_since_update: Days since the vector was last updated.

    Returns:
        Confidence score clamped to [0.0, 1.0].
    """
    # Count factor: sigmoid centered at 20, steepness 0.15
    count_factor = 1.0 / (1.0 + math.exp(-0.15 * (swipe_count - 20)))

    # Rate factor: penalize extreme like rates
    if 0.1 <= like_rate <= 0.8:
        rate_factor = 1.0
    elif like_rate > 0.8:
        rate_factor = 1.0 - 2.5 * (like_rate - 0.8)
        rate_factor = max(rate_factor, 0.5)
    else:  # like_rate < 0.1
        rate_factor = 0.5 + 5.0 * like_rate
        rate_factor = max(rate_factor, 0.5)

    # Staleness factor: no penalty for ≤30 days, linear decay to 0 at 90 days
    if days_since_update <= 30.0:
        staleness_factor = 1.0
    elif days_since_update >= 90.0:
        staleness_factor = 0.0
    else:
        staleness_factor = 1.0 - (days_since_update - 30.0) / 60.0

    # Variance factor: no penalty (tight preferences are valid)
    variance_factor = 1.0

    return count_factor * rate_factor * staleness_factor * variance_factor


def compute_recency_weights(timestamps: list[datetime], half_life_days: float = 14.0) -> list[float]:
    """
    Compute exponential decay weights for a list of timestamps.

    weight_i = exp(-ln(2) * age_in_days_i / half_life_days)

    Age is measured relative to the most recent timestamp in the list,
    so the most recent swipe always gets weight 1.0 and older swipes decay toward 0.0.

    Args:
        timestamps: List of datetime objects representing swipe times.
        half_life_days: Number of days for the weight to decay to 0.5. Defaults to 14.0.

    Returns:
        List of float weights in [0.0, 1.0], one per timestamp.
    """
    if not timestamps:
        return []

    most_recent = max(timestamps)
    ln2 = math.log(2)
    weights = []

    for ts in timestamps:
        age_seconds = (most_recent - ts).total_seconds()
        age_days = age_seconds / 86400.0
        weight = math.exp(-ln2 * age_days / half_life_days)
        weights.append(weight)

    return weights


def compute_weighted_centroid(vectors: list[list[float]], weights: list[float]) -> list[float]:
    """
    Compute weighted average of vectors.

    centroid = sum(w_i * v_i) / sum(w_i)

    Args:
        vectors: List of equal-length float vectors.
        weights: List of float weights, one per vector.

    Returns:
        The weighted centroid vector. Returns a zero vector if total weight is zero
        or inputs are empty.
    """
    if not vectors or not weights:
        return []

    dim = len(vectors[0])
    total_weight = sum(weights)

    if total_weight == 0.0:
        return [0.0] * dim

    centroid = [0.0] * dim
    for vec, w in zip(vectors, weights):
        for i in range(dim):
            centroid[i] += w * vec[i]

    for i in range(dim):
        centroid[i] /= total_weight

    return centroid


def normalize_vector(vec: list[float]) -> list[float]:
    """
    Normalize vector to unit L2 length.

    Returns a zero vector if the input has zero magnitude.

    Args:
        vec: A list of floats representing the vector.

    Returns:
        The unit-length normalized vector, or a zero vector if input is zero.
    """
    if not vec:
        return []

    magnitude = math.sqrt(sum(x * x for x in vec))

    if magnitude == 0.0:
        return [0.0] * len(vec)

    return [x / magnitude for x in vec]


def compute_vector_variance(vectors: list[list[float]], centroid: list[float]) -> float:
    """
    Compute average squared Euclidean distance from each vector to the centroid.

    variance = (1/n) * sum(||v_i - centroid||^2)

    Args:
        vectors: List of equal-length float vectors.
        centroid: The centroid vector to measure distances from.

    Returns:
        The average squared Euclidean distance. Returns 0.0 if vectors is empty.
    """
    if not vectors:
        return 0.0

    n = len(vectors)
    total_sq_dist = 0.0

    for vec in vectors:
        sq_dist = sum((v - c) ** 2 for v, c in zip(vec, centroid))
        total_sq_dist += sq_dist

    return total_sq_dist / n


def apply_dislike_repulsion(
    like_centroid: list[float],
    dislike_centroid: list[float],
    repulsion_weight: float = 0.3,
) -> list[float]:
    """
    Subtract weighted dislike centroid from like centroid, then normalize.

    Computes: result = like_centroid - (repulsion_weight * dislike_centroid)
    The result is normalized to unit length.

    If the subtraction produces a zero vector, returns the normalized like_centroid instead.

    Note: The caller is responsible for checking activation conditions
    (like_rate > 0.8 AND dislike_count >= 5) before calling this function.

    Args:
        like_centroid: The weighted centroid of liked name embeddings.
        dislike_centroid: The weighted centroid of disliked name embeddings.
        repulsion_weight: How strongly dislikes repel. Defaults to 0.3.

    Returns:
        The unit-length repulsion-adjusted taste vector.
    """
    if not like_centroid or not dislike_centroid:
        return normalize_vector(like_centroid)

    dim = len(like_centroid)
    result = [
        like_centroid[i] - repulsion_weight * dislike_centroid[i]
        for i in range(dim)
    ]

    # Check if result is a zero vector
    magnitude = math.sqrt(sum(x * x for x in result))
    if magnitude == 0.0:
        return normalize_vector(like_centroid)

    return normalize_vector(result)


def get_gender_filtered_vectors(
    user,
    gender_preference: str,
) -> tuple[list[list[float]], list[datetime], bool]:
    """
    Fetch liked name embeddings filtered by gender preference.

    Queries all liked swipes for the user across all couples, filters by the
    couple's baby_gender_preference, and fetches embeddings from Qdrant.

    If gender_preference is 'non_binary', returns all liked names.
    If filtered count < 10, falls back to all liked names.

    Args:
        user: The User instance whose liked names to fetch.
        gender_preference: One of 'boy', 'girl', or 'non_binary'.

    Returns:
        A tuple of (vectors, timestamps, fallback_used) where:
        - vectors: list of embedding vectors from Qdrant
        - timestamps: list of swipe timestamps corresponding to the names
        - fallback_used: True if gender filter produced < 10 names and all likes were used
    """
    from core.models import Swipe
    from core.services.onboarding import _fetch_vectors_for_name_ids

    # Step 1: Fetch all liked swipes by this user across all couples
    all_liked_swipes = (
        Swipe.objects.filter(user=user, action="like")
        .select_related("name")
    )

    if not all_liked_swipes.exists():
        return ([], [], False)

    # Step 2: Apply gender filter (unless non_binary)
    fallback_used = False

    if gender_preference == "non_binary":
        # Include all liked names
        filtered_swipes = all_liked_swipes
    else:
        # Filter names where gender_usage contains the preference
        # gender_usage is a JSONField storing a list like ['boy'], ['girl'], or ['boy', 'girl']
        filtered_swipes = all_liked_swipes.filter(
            name__gender_usage__contains=gender_preference
        )

        # Step 3: Fall back to all liked names if filtered count < 10
        if filtered_swipes.count() < 10:
            filtered_swipes = all_liked_swipes
            fallback_used = True

    # Step 4: Extract name IDs and timestamps
    name_ids = []
    timestamps = []
    for swipe in filtered_swipes:
        name_ids.append(str(swipe.name_id))
        timestamps.append(swipe.created_at)

    if not name_ids:
        return ([], [], fallback_used)

    # Step 5: Fetch embeddings from Qdrant
    try:
        vectors = _fetch_vectors_for_name_ids(name_ids)
    except Exception:
        logger.exception("Qdrant unreachable fetching gender-filtered vectors for user %s", user.id)
        return ([], [], fallback_used)

    # Trim timestamps to match returned vectors (Qdrant may not return all)
    timestamps = timestamps[: len(vectors)]

    return (vectors, timestamps, fallback_used)
