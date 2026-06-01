"""Onboarding service for BabyBase."""

import logging

from django.contrib.auth import get_user_model
from qdrant_client.http.exceptions import UnexpectedResponse

from core.models import Couple, OnboardingResponse

User = get_user_model()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Couple Vector Computation (Task 28)
# ---------------------------------------------------------------------------


def _compute_taste_vectors(couple: Couple) -> tuple[list[float], list[float]] | None:
    """Return (parent_a_avg, parent_b_avg) or None if insufficient data."""
    from core.services.qdrant_client import _average_vectors

    a_vectors = _get_liked_vectors_for_user(couple, couple.user_a)
    b_vectors = _get_liked_vectors_for_user(couple, couple.user_b) if couple.user_b else []
    if a_vectors and b_vectors:
        return (_average_vectors(a_vectors), _average_vectors(b_vectors))
    return None


def build_couple_query_embedding(couple: Couple) -> list[float]:
    """
    Build a query embedding for the couple.

    Phase 1 (onboarding only, no swipes yet): Embed merged preference text.
    Phase 2 (after swipes accumulate): Average liked-name vectors.

    Falls back gracefully through phases based on available data.
    """
    from core.services.embeddings import generate_embedding
    from core.services.qdrant_client import _average_vectors, _midpoint_vectors

    # Phase 2: Check for mutual likes first
    mutual_like_vectors = _get_liked_vectors_for_couple(couple, mutual_only=True)
    if mutual_like_vectors:
        return _average_vectors(mutual_like_vectors)

    # Phase 2 (no mutual likes): midpoint of each parent's liked averages
    taste = _compute_taste_vectors(couple)
    if taste is not None:
        a_avg, b_avg = taste
        return _midpoint_vectors(a_avg, b_avg)

    # Phase 1: embed from onboarding text
    profile = build_couple_retrieval_profile(couple)
    text = build_couple_profile_text(profile)
    return generate_embedding(text)


def build_couple_profile_text(profile: dict) -> str:
    """
    Build embeddable text from couple retrieval profile.

    Template: "Looking for a {baby_gender} name. Backgrounds: {backgrounds}.
    Style: {preferred_age}. Length: {preferred_length}.
    Historical importance: {historical_importance}. Lives in: {residence_country}."
    """
    backgrounds = ", ".join(profile.get("preferred_backgrounds") or [])
    baby_gender = profile.get("baby_gender", "boy")
    preferred_age = profile.get("preferred_age", "balanced")
    preferred_length = profile.get("preferred_length", "any")
    historical_importance = profile.get("historical_importance", "medium")
    residence_country = profile.get("residence_country", "international")

    return (
        f"Looking for a {baby_gender} name. "
        f"Backgrounds: {backgrounds}. "
        f"Style: {preferred_age}. "
        f"Length: {preferred_length}. "
        f"Historical importance: {historical_importance}. "
        f"Lives in: {residence_country}."
    )


def compute_bridge_centroid(couple: Couple) -> list[float]:
    """
    Midpoint of both parents' taste vectors. Used for Bridge Names mode.

    Falls back to onboarding-based query embedding if no likes exist.
    """
    from core.services.qdrant_client import _midpoint_vectors

    taste = _compute_taste_vectors(couple)
    if taste is not None:
        a_avg, b_avg = taste
        return _midpoint_vectors(a_avg, b_avg)

    # Fall back to onboarding-based query
    return build_couple_query_embedding(couple)


def _fetch_vectors_for_name_ids(
    name_ids: list[str], vector_name: str = "semantic"
) -> list[list[float]]:
    """Fetch a named vector from Qdrant for a list of name IDs.

    Defaults to the ``semantic`` named vector so existing callers are unchanged.
    """
    from django.conf import settings

    from core.models import NameVectorIndexRef
    from core.services.qdrant_client import get_qdrant_client

    point_ids = list(
        NameVectorIndexRef.objects.filter(name_id__in=name_ids).values_list(
            "qdrant_point_id", flat=True
        )
    )

    if not point_ids:
        return []

    client = get_qdrant_client()
    points = client.retrieve(
        collection_name=settings.QDRANT_COLLECTION,
        ids=[str(pid) for pid in point_ids],
        with_vectors=[vector_name],
    )

    return [p.vector[vector_name] for p in points if p.vector and vector_name in p.vector]


def _get_liked_vectors_for_couple(
    couple: Couple, mutual_only: bool = False, vector_name: str = "semantic"
) -> list[list[float]]:
    """
    Fetch named vectors for names liked by the couple.

    Defaults to the ``semantic`` named vector. Pass ``vector_name`` to retrieve a
    different named vector (e.g. ``"cross_cultural"``) for the same liked names.
    If mutual_only=True, only returns vectors for names liked by BOTH parents.
    """
    try:
        # Get liked name IDs
        swipe_qs = couple.swipes.filter(action="like")

        if mutual_only:
            # Names liked by both parents
            from django.db.models import Count

            mutual_name_ids = (
                swipe_qs.values("name_id")
                .annotate(liker_count=Count("user_id", distinct=True))
                .filter(liker_count__gte=2)
                .values_list("name_id", flat=True)
            )
            name_ids = list(mutual_name_ids)
        else:
            name_ids = list(swipe_qs.values_list("name_id", flat=True).distinct())

        if not name_ids:
            return []

        return _fetch_vectors_for_name_ids(name_ids, vector_name=vector_name)
    except (UnexpectedResponse, ConnectionError, TimeoutError) as exc:
        logger.error(
            "Failed to fetch liked vectors for couple %s (vector=%s, mutual_only=%s): %s",
            couple.id,
            vector_name,
            mutual_only,
            exc,
        )
        return []


def _get_liked_cross_cultural_vectors(
    couple: Couple, mutual_only: bool = False
) -> list[list[float]]:
    """Fetch ``cross_cultural`` vectors for names liked by the couple.

    Thin wrapper over :func:`_get_liked_vectors_for_couple` that selects the
    ``cross_cultural`` named vector. If mutual_only=True, only returns vectors
    for names liked by BOTH parents.
    """
    return _get_liked_vectors_for_couple(
        couple, mutual_only=mutual_only, vector_name="cross_cultural"
    )


def _get_liked_phonetic_vectors(
    couple: Couple, mutual_only: bool = False
) -> list[list[float]]:
    """Fetch ``phonetic_style`` vectors for names liked by the couple.

    Thin wrapper over :func:`_get_liked_vectors_for_couple` that selects the
    ``phonetic_style`` named vector. If mutual_only=True, only returns vectors
    for names liked by BOTH parents.
    """
    return _get_liked_vectors_for_couple(
        couple, mutual_only=mutual_only, vector_name="phonetic_style"
    )


def _get_liked_vectors_for_user(couple: Couple, user) -> list[list[float]]:
    """Fetch semantic vectors for names liked by a specific user in this couple."""
    if not user:
        return []

    try:
        name_ids = list(
            couple.swipes.filter(user=user, action="like").values_list("name_id", flat=True)
        )

        if not name_ids:
            return []

        return _fetch_vectors_for_name_ids(name_ids)
    except (UnexpectedResponse, ConnectionError, TimeoutError) as exc:
        logger.error(
            "Failed to fetch liked vectors for user %s in couple %s: %s",
            user.id,
            couple.id,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Onboarding Preferences (existing)
# ---------------------------------------------------------------------------


def check_gender_conflict(couple: Couple, user: "User", incoming_gender: str) -> str | None:
    """Return an error message when partner gender preferences conflict."""
    partner = couple.user_b if couple.user_a == user else couple.user_a
    if not partner:
        return None

    partner_onboarding = OnboardingResponse.objects.filter(user=partner, couple=couple).first()
    if not partner_onboarding:
        return None

    partner_gender = partner_onboarding.baby_gender_preference
    if {incoming_gender, partner_gender} != {"boy", "girl"}:
        return None

    logger.warning(
        "Gender conflict: user=%s chose %s but partner=%s chose %s",
        user.email,
        incoming_gender,
        partner.email,
        partner_gender,
    )
    return (
        "Your partner selected a different baby gender. "
        "One of you chose boy and the other chose girl. "
        "Please confirm with your partner and try again."
    )


def save_preferences(user: "User", couple: Couple | None, answers: dict) -> OnboardingResponse:
    """
    Store onboarding preferences for a user.

    If the user has a couple, saves with that couple and updates residence_country.
    If couple is None (solo onboarding), saves with couple=None.
    Creates or updates the OnboardingResponse for this user+couple.
    """
    residence_country = answers.pop("residence_country", None)

    # Update residence_country on the couple if provided and couple exists
    if residence_country and couple:
        couple.residence_country = residence_country
        couple.save(update_fields=["residence_country", "updated_at"])

    # Create or update the onboarding response
    response, _created = OnboardingResponse.objects.update_or_create(
        user=user,
        couple=couple,
        defaults={
            "preferred_name_backgrounds": answers.get("preferred_name_backgrounds", []),
            "preferred_name_age": answers.get("preferred_name_age", "balanced"),
            "baby_gender_preference": answers.get("baby_gender_preference", "boy"),
            "preferred_name_length": answers.get("preferred_name_length", "any"),
            "historical_importance": answers.get("historical_importance", "medium"),
        },
    )

    return response


def build_couple_retrieval_profile(couple: Couple) -> dict:
    """
    Merge both parents' onboarding answers into a single retrieval profile.

    Uses 40/30/30 merge strategy for backgrounds:
    - 40% overlap/bridge (backgrounds both parents share)
    - 30% parent A preferences
    - 30% parent B preferences

    Returns a dict suitable for building a query embedding.
    """
    responses = list(
        OnboardingResponse.objects.filter(couple=couple).select_related("user")
    )

    if not responses:
        return _empty_profile(couple)

    if len(responses) == 1:
        return _single_parent_profile(responses[0], couple)

    # Two parents — merge with 40/30/30 strategy
    # Determine which response belongs to user_a and user_b
    response_a = None
    response_b = None
    for r in responses:
        if r.user_id == couple.user_a_id:
            response_a = r
        else:
            response_b = r

    if not response_a or not response_b:
        # Fallback: just use whatever we have
        return _single_parent_profile(responses[0], couple)

    return _merge_profiles(response_a, response_b, couple)


def _empty_profile(couple: Couple) -> dict:
    """Return an empty profile when no onboarding data exists."""
    return {
        "preferred_backgrounds": [],
        "preferred_age": "balanced",
        "baby_gender": "boy",
        "preferred_length": "any",
        "historical_importance": "medium",
        "residence_country": couple.residence_country or "international",
    }


def _single_parent_profile(response: OnboardingResponse, couple: Couple) -> dict:
    """Return a profile based on a single parent's answers."""
    return {
        "preferred_backgrounds": response.preferred_name_backgrounds or [],
        "preferred_age": response.preferred_name_age,
        "baby_gender": response.baby_gender_preference,
        "preferred_length": response.preferred_name_length,
        "historical_importance": response.historical_importance,
        "residence_country": couple.residence_country or "international",
    }


def _merge_profiles(
    response_a: OnboardingResponse,
    response_b: OnboardingResponse,
    couple: Couple,
) -> dict:
    """
    Merge two parents' profiles using 40/30/30 strategy for backgrounds.

    40% overlap/bridge (shared backgrounds)
    30% parent A unique backgrounds
    30% parent B unique backgrounds
    """
    backgrounds_a = set(response_a.preferred_name_backgrounds or [])
    backgrounds_b = set(response_b.preferred_name_backgrounds or [])

    # Overlap (shared backgrounds)
    overlap = backgrounds_a & backgrounds_b
    unique_a = backgrounds_a - overlap
    unique_b = backgrounds_b - overlap

    # Build merged backgrounds list with 40/30/30 weighting
    merged_backgrounds = _apply_merge_ratio(
        overlap=list(overlap),
        parent_a=list(unique_a),
        parent_b=list(unique_b),
    )

    # For scalar preferences, use majority/compromise logic
    preferred_age = _merge_scalar(
        response_a.preferred_name_age,
        response_b.preferred_name_age,
        default="balanced",
    )
    baby_gender = _merge_gender(
        response_a.baby_gender_preference,
        response_b.baby_gender_preference,
    )
    preferred_length = _merge_scalar(
        response_a.preferred_name_length,
        response_b.preferred_name_length,
        default="any",
    )
    historical_importance = _merge_scalar(
        response_a.historical_importance,
        response_b.historical_importance,
        default="medium",
    )

    return {
        "preferred_backgrounds": merged_backgrounds,
        "preferred_age": preferred_age,
        "baby_gender": baby_gender,
        "preferred_length": preferred_length,
        "historical_importance": historical_importance,
        "residence_country": couple.residence_country or "international",
    }


def _apply_merge_ratio(
    overlap: list[str],
    parent_a: list[str],
    parent_b: list[str],
) -> list[str]:
    """
    Apply 40/30/30 merge ratio to background lists.

    All overlap items are included first (they represent the 40% bridge zone).
    Then proportionally include items from each parent's unique list.
    """
    # All overlap items are always included (bridge zone)
    merged = list(overlap)

    # Include unique items from each parent
    # The ratio is conceptual for deck generation; here we include all
    # but tag them with source for downstream use
    merged.extend(parent_a)
    merged.extend(parent_b)

    return merged


def _merge_scalar(value_a: str, value_b: str, default: str) -> str:
    """
    Merge two scalar preference values.

    If they agree, use that value.
    If they disagree, use the default/neutral option.
    """
    if value_a == value_b:
        return value_a
    return default


def _merge_gender(gender_a: str, gender_b: str) -> str:
    """
    Merge two baby gender preferences.

    Rules:
    - Both agree → use that value
    - One picks non_binary + other picks boy/girl → non_binary (mixed deck)
    - boy vs girl → non_binary (should not happen; view rejects this conflict)
    """
    if gender_a == gender_b:
        return gender_a
    # Any disagreement results in a mixed deck (no gender filter)
    return "non_binary"
