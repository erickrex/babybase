"""Swipe and match service for BabyBase.

Handles swipe recording, mutual match detection, and similar name retrieval.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.models import (
    Couple,
    MatchStatus,
    MutualMatch,
    Name,
    RecommendationDeck,
    Swipe,
    SwipeAction,
)
from core.services.qdrant_client import get_similar_to_names

User = get_user_model()
logger = logging.getLogger(__name__)


class SwipeValidationError(Exception):
    """Raised when a swipe fails validation."""

    pass


def validate_swipe(user: "User", couple: Couple, name_id: str) -> Name:
    """
    Server-side validation for a swipe action.

    Checks:
        - User is a member of the couple
        - Name exists and is active

    Args:
        user: The user performing the swipe.
        couple: The couple context.
        name_id: UUID of the name being swiped.

    Returns:
        The validated Name instance.

    Raises:
        SwipeValidationError: If any validation check fails.
    """
    # Check user is in the couple
    if couple.user_a != user and couple.user_b != user:
        raise SwipeValidationError("User is not a member of this couple.")

    # Check name exists and is active
    try:
        name = Name.objects.get(id=name_id)
    except Name.DoesNotExist:
        raise SwipeValidationError("Name not found.")

    if not name.active:
        raise SwipeValidationError("Name is no longer active.")

    return name


def validate_source_deck(couple: Couple, name_id: str, deck_id: str | None = None) -> RecommendationDeck | None:
    """Return a valid source deck, or raise when a provided deck does not contain the name."""
    if not deck_id:
        return None

    source_deck = (
        RecommendationDeck.objects.filter(id=deck_id, couple=couple, items__name_id=name_id)
        .distinct()
        .first()
    )
    if source_deck is None:
        raise SwipeValidationError("Deck not found for this couple and name.")

    return source_deck


def record_swipe(
    user: "User",
    couple: Couple,
    name_id: str,
    action: str,
    source_deck: RecommendationDeck | None = None,
) -> tuple[Swipe, bool]:
    """
    Persist a swipe record. Handles duplicates gracefully.

    If a swipe already exists for (couple, user, name), returns the existing
    swipe without error.

    Args:
        user: The user performing the swipe.
        couple: The couple context.
        name_id: UUID of the name being swiped.
        action: One of 'like', 'dislike', 'maybe'.
        source_deck: Optional source recommendation deck.

    Returns:
        Tuple of (Swipe instance, created: bool).
        created=False means a duplicate was found and returned.
    """
    # Try to create; handle duplicate gracefully
    try:
        with transaction.atomic():
            swipe = Swipe.objects.create(
                couple=couple,
                user=user,
                name_id=name_id,
                action=action,
                source_deck=source_deck,
            )
        return swipe, True
    except IntegrityError:
        # Duplicate swipe — return existing
        logger.debug("Duplicate swipe ignored: user=%s name=%s", user.email, name_id)
        existing = Swipe.objects.get(couple=couple, user=user, name_id=name_id)
        return existing, False


def check_mutual_match(couple: Couple, name_id: str) -> bool:
    """
    Check if both parents have a 'like' swipe on this name.

    A mutual match requires BOTH user_a and user_b to have action='like'
    on the same name within the same couple.

    Args:
        couple: The couple to check.
        name_id: UUID of the name.

    Returns:
        True if both parents liked the name, False otherwise.
    """
    if not couple.user_b:
        return False

    likes = Swipe.objects.filter(
        couple=couple,
        name_id=name_id,
        action=SwipeAction.LIKE,
    ).values_list("user_id", flat=True)

    like_user_ids = set(likes)
    return couple.user_a_id in like_user_ids and couple.user_b_id in like_user_ids


def create_match(couple: Couple, name_id: str) -> MutualMatch:
    """
    Create a MutualMatch record with a computed strength score.

    If a match already exists for this couple+name, returns the existing one.

    Args:
        couple: The couple.
        name_id: UUID of the matched name.

    Returns:
        The MutualMatch instance (created or existing).
    """
    # Check if match already exists
    existing = MutualMatch.objects.filter(couple=couple, name_id=name_id).first()
    if existing:
        return existing

    # Compute match strength score from the name's semantic fit
    # For MVP, use a simple heuristic based on the name's historical significance
    # and whether it bridges both parents' backgrounds
    strength = _compute_match_strength(couple, name_id)

    match = MutualMatch.objects.create(
        couple=couple,
        name_id=name_id,
        match_strength_score=strength,
        status=MatchStatus.ACTIVE,
    )
    logger.info("Match created: couple=%s name=%s strength=%.3f", couple.id, name_id, strength)
    return match


def _compute_match_strength(couple: Couple, name_id: str) -> float:
    """
    Compute a match strength score for MVP.

    Uses the name's metadata to derive a simple strength score.
    In future, this could incorporate Qdrant similarity scores.
    """
    try:
        name = Name.objects.get(id=name_id)
    except Name.DoesNotExist:
        return 0.0

    # Simple heuristic: combine historical significance with origin diversity
    score = 0.0

    # Historical significance contributes up to 0.4
    score += min(name.historical_significance_score, 1.0) * 0.4

    # Origin diversity: more origins = higher bridge potential (up to 0.3)
    origin_count = len(name.origin_backgrounds) if name.origin_backgrounds else 0
    score += min(origin_count / 5.0, 1.0) * 0.3

    # Language diversity: more languages = more international (up to 0.3)
    lang_count = len(name.languages) if name.languages else 0
    score += min(lang_count / 4.0, 1.0) * 0.3

    return round(min(score, 1.0), 3)


def get_similar_names(name_id: str, couple: Couple) -> list[dict]:
    """
    Find names similar to a given name, excluding already-swiped names.

    Fetches the name's vector from Qdrant and searches for nearest neighbors.

    Args:
        name_id: UUID of the anchor name.
        couple: The couple (used to exclude already-swiped names).

    Returns:
        List of similar name dicts from Qdrant (top 10).
    """
    from core.models import NameVectorIndexRef

    # Get the Qdrant point ID for this name
    try:
        vector_ref = NameVectorIndexRef.objects.get(name_id=name_id)
    except NameVectorIndexRef.DoesNotExist:
        return []

    # Get already-swiped name IDs for exclusion
    swiped_name_ids = list(
        Swipe.objects.filter(couple=couple)
        .values_list("name__vector_ref__qdrant_point_id", flat=True)
        .distinct()
    )
    swiped_point_ids = [str(pid) for pid in swiped_name_ids if pid]

    # Search for similar names via Qdrant
    results = get_similar_to_names(
        name_ids=[str(vector_ref.qdrant_point_id)],
        filters={"active": True},
        limit=10 + len(swiped_point_ids),  # Request extra to account for post-filtering
    )

    # Filter out already-swiped names from results
    swiped_set = set(swiped_point_ids)
    filtered_results = [r for r in results if r.get("point_id") not in swiped_set]

    return filtered_results[:10]
