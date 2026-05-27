"""Recommendation deck generation orchestrator.

Handles the full pipeline: build query → retrieve from Qdrant → re-rank → persist deck.
"""

import logging

from django.utils import timezone

from core.models import (
    Couple,
    DeckMode,
    OnboardingResponse,
    RecommendationDeck,
    RecommendationDeckItem,
)
from core.services.couples import get_couple_for_user
from core.services.onboarding import (
    build_couple_query_embedding,
    build_couple_retrieval_profile,
    compute_bridge_centroid,
)
from core.services.qdrant_client import search_names
from core.services.relevance import (
    bridge_score,
    compute_final_score,
    couple_overlap_score,
    diversity_score,
    explicit_filter_fit_score,
    novelty_score,
    semantic_fit_score,
)
from core.services.taste_vectors import (
    TRUST_THRESHOLDS,
    compute_confidence_weighted_midpoint,
    select_phase,
)

logger = logging.getLogger(__name__)

# Default deck size
DECK_SIZE = 50
# Retrieve more candidates than needed for re-ranking
RETRIEVAL_MULTIPLIER = 2


class DeckEligibilityError(Exception):
    """Raised when a user is not ready to generate a recommendation deck."""


def prepare_couple_for_deck(user) -> Couple:
    """Return an active deck-ready couple, creating a solo couple when appropriate."""
    from core.models import CoupleStatus

    couple = get_couple_for_user(user)
    if not couple:
        if not OnboardingResponse.objects.filter(user=user, couple=None).exists():
            raise DeckEligibilityError("You must complete onboarding before generating a deck.")
        couple = Couple.objects.create(user_a=user, user_b=None, status=CoupleStatus.ACTIVE)
        updated = OnboardingResponse.objects.filter(user=user, couple=None).update(couple=couple)
        if updated:
            logger.info("Associated %d solo onboarding response(s) with new solo couple=%s", updated, couple.id)
        logger.info("Created solo couple: couple=%s user=%s", couple.id, user.email)

    if couple.status != "active":
        raise DeckEligibilityError("Your couple must be active to generate a deck.")

    if couple.user_b is None:
        if not OnboardingResponse.objects.filter(couple=couple, user=user).exists():
            raise DeckEligibilityError("You must complete onboarding before generating a deck.")
        return couple

    onboarded_user_ids = set(
        OnboardingResponse.objects.filter(couple=couple, user_id__in=[couple.user_a_id, couple.user_b_id])
        .values_list("user_id", flat=True)
        .distinct()
    )
    if onboarded_user_ids != {couple.user_a_id, couple.user_b_id}:
        raise DeckEligibilityError("Both partners must complete onboarding before generating a deck.")

    return couple


def get_cached_deck(couple: Couple, mode: str) -> RecommendationDeck | None:
    """Return the newest unexpired deck with unswiped items for the couple and mode."""
    swiped_name_ids = _get_excluded_name_ids(couple)
    decks = (
        RecommendationDeck.objects.filter(
            couple=couple,
            mode=mode,
            expires_at__gt=timezone.now(),
            items__isnull=False,
        )
        .distinct()
        .order_by("-created_at")
    )
    for deck in decks:
        if deck.items.exclude(name_id__in=swiped_name_ids).exists():
            return deck
    return None


def generate_deck(couple: Couple, mode: str = "best_match") -> RecommendationDeck:
    """
    Full deck generation pipeline.

    Steps:
    1. Build query embedding based on mode
    2. Get excluded name IDs (all previously swiped by either parent)
    3. Query Qdrant with embedding + payload filters + exclusions
    4. Re-rank candidates with scoring formula
    5. Apply diversity constraints
    6. Persist deck to DB (with quality metrics)
    7. Return deck

    Args:
        couple: The Couple instance to generate a deck for.
        mode: One of 'best_match', 'bridge_names', 'more_like_this', 'wildcard'.

    Returns:
        The persisted RecommendationDeck with items.
    """
    from core.models import UserTasteVector

    # Step 1: Build query embedding based on mode
    logger.info("Building new deck: couple=%s mode=%s", couple.id, mode)
    embedding = _build_query_embedding_for_mode(couple, mode)

    # Track whether Phase D was used (for sparse retrieval fallback)
    phase_used = None
    fallback_reason = None
    if mode == DeckMode.BEST_MATCH:
        phase, _phase_data = select_phase(couple)
        phase_used = phase
        if phase == "phase_c":
            fallback_reason = _phase_data.get("reason")

    # Step 2: Get excluded name IDs (all previously swiped)
    excluded_name_ids = _get_excluded_name_ids(couple)

    # Step 3: Build payload filters from couple profile
    profile = build_couple_retrieval_profile(couple)
    filters = _build_payload_filters(profile)

    # Get Qdrant point IDs to exclude
    excluded_point_ids = _get_excluded_point_ids(excluded_name_ids)

    # Adjust retrieval params based on mode
    retrieval_limit = DECK_SIZE * RETRIEVAL_MULTIPLIER
    if mode == "wildcard":
        retrieval_limit = DECK_SIZE * 3  # Cast wider net for wildcards

    # Step 4: Query Qdrant
    candidates = search_names(
        embedding=embedding,
        filters=filters,
        limit=retrieval_limit,
        exclude_ids=excluded_point_ids,
        vector_name="semantic",
    )

    if not candidates:
        # If no results with filters, try without strict filters
        logger.warning("No candidates with filters, retrying without strict filters: couple=%s", couple.id)
        candidates = search_names(
            embedding=embedding,
            filters={"active": True},
            limit=retrieval_limit,
            exclude_ids=excluded_point_ids,
            vector_name="semantic",
        )

    # Step 4b: Sparse retrieval fallback — if Phase D was used and top score < 0.6,
    # discard results and regenerate with Phase C embedding
    if phase_used == "phase_d" and candidates:
        top_score = max(c.get("score", 0.0) for c in candidates)
        min_retrieval_score = TRUST_THRESHOLDS["min_retrieval_score"]
        if top_score < min_retrieval_score:
            logger.warning(
                "Sparse retrieval fallback: top_score=%.3f < %.1f, "
                "discarding Phase D results and regenerating with Phase C: couple=%s",
                top_score,
                min_retrieval_score,
                couple.id,
            )
            fallback_reason = "top_score_below_threshold"
            phase_used = "phase_c"
            # Regenerate with Phase C embedding
            embedding = build_couple_query_embedding(couple)
            candidates = search_names(
                embedding=embedding,
                filters=filters,
                limit=retrieval_limit,
                exclude_ids=excluded_point_ids,
                vector_name="semantic",
            )
            if not candidates:
                logger.warning(
                    "No candidates with Phase C fallback filters, retrying without strict filters: couple=%s",
                    couple.id,
                )
                candidates = search_names(
                    embedding=embedding,
                    filters={"active": True},
                    limit=retrieval_limit,
                    exclude_ids=excluded_point_ids,
                    vector_name="semantic",
                )

    # Compute top_retrieval_score from final candidates
    top_retrieval_score = 0.0
    if candidates:
        top_retrieval_score = max(c.get("score", 0.0) for c in candidates)

    # Step 5: Re-rank candidates
    parent_a_profile, parent_b_profile = _get_parent_profiles(couple)
    ranked_candidates = _rerank_candidates(
        candidates=candidates,
        couple=couple,
        profile=profile,
        parent_a_profile=parent_a_profile,
        parent_b_profile=parent_b_profile,
        mode=mode,
    )

    # Step 5b: Check for sparse pool (fewer than 10 candidates above 0.5)
    above_threshold_count = sum(1 for c in ranked_candidates if c.get("rerank_score", 0) > 0.5)
    sparse_pool = above_threshold_count < 10
    if sparse_pool:
        logger.info(
            "Sparse pool detected: only %d candidates above 0.5 (threshold: 10), "
            "relaxing diversity constraints: couple=%s",
            above_threshold_count,
            couple.id,
        )

    # Step 6: Apply diversity constraints (relaxed if pool is sparse)
    final_candidates = _apply_diversity_constraints(
        ranked_candidates, deck_size=DECK_SIZE, relaxed=sparse_pool
    )
    final_candidates = _interleave_by_first_letter(final_candidates)

    # Compute quality metrics for logging
    user_a_confidence = 0.0
    user_b_confidence = 0.0
    user_a_swipe_count = 0
    user_b_swipe_count = 0

    try:
        vec_a = UserTasteVector.objects.get(user=couple.user_a)
        user_a_confidence = vec_a.confidence_score
        user_a_swipe_count = vec_a.swipe_count
    except UserTasteVector.DoesNotExist:
        pass

    if couple.user_b is not None:
        try:
            vec_b = UserTasteVector.objects.get(user=couple.user_b)
            user_b_confidence = vec_b.confidence_score
            user_b_swipe_count = vec_b.swipe_count
        except UserTasteVector.DoesNotExist:
            pass

    quality_metrics = {
        "phase_used": phase_used or "phase_c",
        "user_a_confidence_score": user_a_confidence,
        "user_b_confidence_score": user_b_confidence,
        "user_a_swipe_count": user_a_swipe_count,
        "user_b_swipe_count": user_b_swipe_count,
        "top_retrieval_score": top_retrieval_score,
        "fallback_reason": fallback_reason,
    }

    # Step 7: Persist deck to DB (with quality metrics)
    deck = _persist_deck(couple, final_candidates, mode, profile, quality_metrics)

    logger.info("Deck generated: id=%s couple=%s mode=%s items=%d", deck.id, couple.id, mode, len(final_candidates))
    return deck


def _build_query_embedding_for_mode(couple: Couple, mode: str) -> list[float]:
    """Build the appropriate query embedding based on the recommendation mode."""
    if mode == DeckMode.BEST_MATCH:
        # Try Phase D (taste vectors) first, fall back to Phase C (stated preferences)
        phase, phase_data = select_phase(couple)
        if phase == "phase_d":
            logger.info(
                "Using Phase D for couple=%s (conf_a=%.3f, conf_b=%.3f)",
                couple.id,
                phase_data["conf_a"],
                phase_data["conf_b"],
            )
            return compute_confidence_weighted_midpoint(
                phase_data["vec_a"],
                phase_data["conf_a"],
                phase_data["vec_b"],
                phase_data["conf_b"],
            )
        # Phase C: fall through to standard couple query embedding
        logger.info("Using Phase C for couple=%s (reason=%s)", couple.id, phase_data.get("reason"))
        return build_couple_query_embedding(couple)

    elif mode == DeckMode.BRIDGE_NAMES:
        # Bridge centroid (midpoint of both parents' taste vectors)
        return compute_bridge_centroid(couple)

    elif mode == DeckMode.MORE_LIKE_THIS:
        # Average vectors of mutual likes
        from core.services.onboarding import _get_liked_vectors_for_couple
        from core.services.qdrant_client import _average_vectors

        mutual_vectors = _get_liked_vectors_for_couple(couple, mutual_only=True)
        if mutual_vectors:
            return _average_vectors(mutual_vectors)
        # Fall back to standard couple embedding
        return build_couple_query_embedding(couple)

    elif mode == DeckMode.WILDCARD:
        # Use couple embedding but we'll increase distance threshold in retrieval
        # The wider net is handled by retrieval_limit increase
        # We also search with a slightly perturbed vector to find serendipitous picks
        return build_couple_query_embedding(couple)

    else:
        # Default to best_match for unknown modes
        return build_couple_query_embedding(couple)


def _get_excluded_name_ids(couple: Couple) -> list[str]:
    """Get all name IDs previously swiped by either parent in this couple."""
    swiped_name_ids = list(
        couple.swipes.values_list("name_id", flat=True).distinct()
    )
    return [str(nid) for nid in swiped_name_ids]


def _get_excluded_point_ids(name_ids: list[str]) -> list[str]:
    """Convert name IDs to Qdrant point IDs for exclusion."""
    if not name_ids:
        return []

    from core.models import NameVectorIndexRef

    point_ids = list(
        NameVectorIndexRef.objects.filter(
            name_id__in=name_ids
        ).values_list("qdrant_point_id", flat=True)
    )
    return [str(pid) for pid in point_ids]


def _build_payload_filters(profile: dict) -> dict:
    """Build Qdrant payload filters from the couple retrieval profile."""
    filters = {"active": True}

    # Gender filter
    baby_gender = profile.get("baby_gender")
    if baby_gender and baby_gender != "non_binary":
        filters["gender_usage"] = baby_gender

    return filters


def _get_parent_profiles(couple: Couple) -> tuple[dict, dict]:
    """Get individual parent profiles for scoring."""
    responses = list(
        OnboardingResponse.objects.filter(couple=couple).select_related("user")
    )

    parent_a_profile = {"preferred_backgrounds": []}
    parent_b_profile = {"preferred_backgrounds": []}

    for r in responses:
        profile_data = {
            "preferred_backgrounds": r.preferred_name_backgrounds or [],
        }
        if r.user_id == couple.user_a_id:
            parent_a_profile = profile_data
        else:
            parent_b_profile = profile_data

    return parent_a_profile, parent_b_profile


def _rerank_candidates(
    candidates: list[dict],
    couple: Couple,
    profile: dict,
    parent_a_profile: dict,
    parent_b_profile: dict,
    mode: str,
) -> list[dict]:
    """
    Re-rank candidates using the multi-signal scoring formula.

    Each candidate gets a final_score computed from all signals.
    """
    pending_candidates = []

    for candidate in candidates:
        payload = candidate.get("payload", {})

        sem_score = semantic_fit_score(candidate.get("score"))
        overlap = couple_overlap_score(payload, parent_a_profile, parent_b_profile)
        filter_fit = explicit_filter_fit_score(payload, profile)
        parent_a_bg = parent_a_profile.get("preferred_backgrounds", [])
        parent_b_bg = parent_b_profile.get("preferred_backgrounds", [])
        residence = couple.residence_country or ""
        b_score = bridge_score(payload, parent_a_bg, parent_b_bg, residence)

        pending_candidates.append(
            {
                **candidate,
                "payload": payload,
                "retrieval_score": float(candidate.get("score") or 0.0),
                "_signal_bundle": {
                    "semantic": sem_score,
                    "couple_overlap": overlap,
                    "filter_fit": filter_fit,
                    "bridge": b_score,
                },
            }
        )

    ranked_candidates: list[dict] = []
    ranked_payloads: list[dict] = []
    seen_origins: set[str] = set()

    while pending_candidates:
        best_candidate = None
        best_key = None

        for candidate in pending_candidates:
            payload = candidate.get("payload", {})
            signals = candidate["_signal_bundle"]
            n_score = novelty_score(payload, seen_origins)
            d_score = diversity_score(payload, ranked_payloads)

            final = compute_final_score(
                signals["semantic"],
                signals["couple_overlap"],
                signals["filter_fit"],
                signals["bridge"],
                n_score,
                d_score,
            )
            final = _apply_mode_score_adjustments(
                mode=mode,
                final=final,
                semantic=signals["semantic"],
                couple_overlap=signals["couple_overlap"],
                filter_fit=signals["filter_fit"],
                bridge=signals["bridge"],
                novelty=n_score,
                diversity=d_score,
            )

            candidate["rerank_score"] = final

            identity = str(payload.get("name_id") or candidate.get("name_id") or "")
            name = str(payload.get("canonical_name") or "")
            candidate_key = (final, candidate["retrieval_score"], name, identity)

            if best_key is None or candidate_key > best_key:
                best_key = candidate_key
                best_candidate = candidate

        assert best_candidate is not None
        pending_candidates.remove(best_candidate)
        ranked_candidates.append(best_candidate)
        ranked_payloads.append(best_candidate.get("payload", {}))
        seen_origins.update(best_candidate.get("payload", {}).get("origin_backgrounds") or [])

    for candidate in ranked_candidates:
        candidate.pop("_signal_bundle", None)

    return ranked_candidates


def _apply_mode_score_adjustments(
    mode: str,
    final: float,
    semantic: float,
    couple_overlap: float,
    filter_fit: float,
    bridge: float,
    novelty: float,
    diversity: float,
) -> float:
    """Apply mode-specific reranking adjustments to the base final score."""
    if mode == DeckMode.BRIDGE_NAMES:
        return final + bridge * 0.15

    if mode == DeckMode.WILDCARD:
        direct_sim = semantic
        latent_compat = (couple_overlap + filter_fit + bridge) / 3.0
        serendipity_bonus = max(0.0, latent_compat - direct_sim) * 0.20
        return final + diversity * 0.10 + novelty * 0.10 + serendipity_bonus

    return final


def _apply_diversity_constraints(
    candidates: list[dict], deck_size: int = 50, relaxed: bool = False
) -> list[dict]:
    """
    Apply diversity constraints to the ranked candidate list.

    Ensures variety in first letter, origin, and style within the final deck.
    Uses a greedy selection approach.

    When relaxed=True (sparse pool: fewer than 10 candidates above 0.5),
    diversity thresholds are doubled to avoid over-filtering a limited pool.
    """
    if len(candidates) <= deck_size:
        return candidates

    selected = []
    first_letters_count: dict[str, int] = {}
    origins_count: dict[str, int] = {}
    styles_count: dict[str, int] = {}

    max_per_letter = max(3, deck_size // 10)
    max_per_origin = max(5, deck_size // 5)
    max_per_style = max(deck_size // 3, 10)

    # Relax constraints for sparse pools (Requirement 9.2)
    if relaxed:
        max_per_letter *= 2
        max_per_origin *= 2
        max_per_style *= 2

    for candidate in candidates:
        if len(selected) >= deck_size:
            break

        payload = candidate.get("payload", {})
        name = payload.get("canonical_name", "")
        first_letter = name[0].upper() if name else ""
        origins = payload.get("origin_backgrounds") or []
        style = payload.get("age_style_category", "")

        # Check first letter constraint
        if first_letter and first_letters_count.get(first_letter, 0) >= max_per_letter:
            # Allow if it's a high-scoring candidate (top 20% boost)
            if candidate.get("rerank_score", 0) < 0.5:
                continue

        # Check origin constraint
        origin_blocked = False
        for origin in origins:
            if origins_count.get(origin, 0) >= max_per_origin:
                origin_blocked = True
                break
        if origin_blocked and candidate.get("rerank_score", 0) < 0.5:
            continue

        # Check style constraint
        if style and styles_count.get(style, 0) >= max_per_style:
            if candidate.get("rerank_score", 0) < 0.5:
                continue

        # Accept candidate
        selected.append(candidate)

        # Update counts
        if first_letter:
            first_letters_count[first_letter] = first_letters_count.get(first_letter, 0) + 1
        for origin in origins:
            origins_count[origin] = origins_count.get(origin, 0) + 1
        if style:
            styles_count[style] = styles_count.get(style, 0) + 1

    # If we didn't fill the deck due to constraints, add remaining candidates
    if len(selected) < deck_size:
        remaining = [c for c in candidates if c not in selected]
        selected.extend(remaining[: deck_size - len(selected)])

    return selected


def _interleave_by_first_letter(candidates: list[dict]) -> list[dict]:
    """Return candidates in rounds by first letter while preserving rank within each letter."""
    grouped_candidates: dict[str, list[dict]] = {}
    for candidate in candidates:
        payload = candidate.get("payload", {})
        name = payload.get("canonical_name", "")
        first_letter = name[0].upper() if name else ""
        grouped_candidates.setdefault(first_letter, []).append(candidate)

    interleaved: list[dict] = []
    while grouped_candidates:
        letters_by_next_score = sorted(
            grouped_candidates,
            key=lambda letter: (
                grouped_candidates[letter][0].get("rerank_score", 0.0),
                grouped_candidates[letter][0].get("retrieval_score", 0.0),
                grouped_candidates[letter][0].get("payload", {}).get("canonical_name", ""),
            ),
            reverse=True,
        )
        for letter in letters_by_next_score:
            interleaved.append(grouped_candidates[letter].pop(0))
            if not grouped_candidates[letter]:
                del grouped_candidates[letter]

    return interleaved


def _persist_deck(
    couple: Couple,
    candidates: list[dict],
    mode: str,
    profile: dict,
    quality_metrics: dict | None = None,
) -> RecommendationDeck:
    """Persist the generated deck and its items to the database.

    Args:
        couple: The Couple instance.
        candidates: Final ranked candidates to persist as deck items.
        mode: The deck generation mode.
        profile: The retrieval profile dict (couple preferences).
        quality_metrics: Optional dict of quality metrics to merge into retrieval_profile_json.
    """
    # Merge quality metrics into the retrieval profile
    retrieval_profile = {**profile}
    if quality_metrics:
        retrieval_profile.update(quality_metrics)

    # Create the deck
    deck = RecommendationDeck.objects.create(
        couple=couple,
        mode=mode,
        retrieval_profile_json=retrieval_profile,
        expires_at=timezone.now() + timezone.timedelta(days=7),
    )

    # Create deck items
    items_to_create = []
    for rank, candidate in enumerate(candidates, start=1):
        payload = candidate.get("payload", {})
        name_id = payload.get("name_id") or candidate.get("name_id")

        if not name_id:
            continue

        # Build explanation summary
        explanation = _build_explanation(payload, mode)

        items_to_create.append(
            RecommendationDeckItem(
                deck=deck,
                name_id=name_id,
                rank=rank,
                retrieval_score=candidate.get("retrieval_score", 0.0),
                rerank_score=candidate.get("rerank_score", 0.0),
                explanation_summary=explanation,
            )
        )

    if items_to_create:
        RecommendationDeckItem.objects.bulk_create(items_to_create)

    return deck


def _build_explanation(payload: dict, mode: str) -> str:
    """Build a template-based explanation for a deck item."""
    origins = payload.get("origin_backgrounds") or []
    style = payload.get("age_style_category", "")

    origins_text = " and ".join(origins[:3]) if origins else "diverse"
    style_text = style if style else "versatile"

    if mode == DeckMode.BRIDGE_NAMES:
        return f"{style_text.capitalize()} name with {origins_text} roots — bridges both backgrounds."
    elif mode == DeckMode.MORE_LIKE_THIS:
        return f"Similar to names you both liked. {style_text.capitalize()} style with {origins_text} origins."
    elif mode == DeckMode.WILDCARD:
        return (
            f"Wildcard Pick! {style_text.capitalize()} name from {origins_text} tradition"
            f" — a surprising find outside your usual picks."
        )
    else:
        return f"{style_text.capitalize()} name used across {origins_text} contexts."
