"""Relevance scoring service for name re-ranking.

Each scoring signal is an independent, null-safe method returning a float in [0.0, 1.0].
Missing data always returns 0.0 — never crashes, never penalizes.
"""

# Scoring weights from design doc.
# filter_fit is weighted to honor each parent's explicit length/age/historical
# preferences (raised from 0.15); the deck-internal variety signals (novelty,
# diversity) are trimmed to fund it. Weights sum to 1.0.
W_SEMANTIC = 0.35
W_COUPLE_OVERLAP = 0.20
W_FILTER_FIT = 0.25
W_BRIDGE = 0.10
W_NOVELTY = 0.05
W_DIVERSITY = 0.05

# Credit for a "middle"/compromise name that sits between preferences (e.g. a
# medium-length name when a parent wants short, a timeless name when they want
# classic, a mid-range historical score). Roughly 1/4 of a full preference
# match so these names still surface, just ranked below direct matches.
MIDDLE_CREDIT = 0.25


def _first_letter(value: object) -> str | None:
    """Return the uppercase first letter for a non-empty string."""
    if not isinstance(value, str) or not value:
        return None
    return value[0].upper()


def compute_final_score(
    semantic: float,
    couple_overlap: float,
    filter_fit: float,
    bridge: float,
    novelty: float,
    diversity: float,
) -> float:
    """Compute the weighted final score from all signals."""
    return (
        semantic * W_SEMANTIC
        + couple_overlap * W_COUPLE_OVERLAP
        + filter_fit * W_FILTER_FIT
        + bridge * W_BRIDGE
        + novelty * W_NOVELTY
        + diversity * W_DIVERSITY
    )


def semantic_fit_score(candidate_score: float | None) -> float:
    """
    Pass-through from Qdrant similarity score (already 0-1 range).

    Args:
        candidate_score: The cosine similarity score from Qdrant search.

    Returns:
        The score clamped to [0.0, 1.0], or 0.0 if None.
    """
    if candidate_score is None:
        return 0.0
    try:
        score = float(candidate_score)
        return max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        return 0.0


def couple_overlap_score(
    candidate: dict | None,
    parent_a_profile: dict | None,
    parent_b_profile: dict | None,
) -> float:
    """
    Score how well a name fits both parents' backgrounds.

    Measures overlap between the name's origin_backgrounds and each parent's
    preferred backgrounds. Higher score when name satisfies both parents.

    Args:
        candidate: Dict with name payload (must have 'origin_backgrounds').
        parent_a_profile: Dict with parent A's preferences (must have 'preferred_backgrounds').
        parent_b_profile: Dict with parent B's preferences (must have 'preferred_backgrounds').

    Returns:
        Float in [0.0, 1.0]. 0.0 if any data is missing.
    """
    if not candidate or not parent_a_profile or not parent_b_profile:
        return 0.0

    try:
        name_origins = set(candidate.get("origin_backgrounds") or [])
        if not name_origins:
            return 0.0

        a_prefs = set(parent_a_profile.get("preferred_backgrounds") or [])
        b_prefs = set(parent_b_profile.get("preferred_backgrounds") or [])

        if not a_prefs and not b_prefs:
            return 0.0

        # Score: proportion of parents whose preferences overlap with name origins
        a_overlap = len(name_origins & a_prefs) / max(len(a_prefs), 1) if a_prefs else 0.0
        b_overlap = len(name_origins & b_prefs) / max(len(b_prefs), 1) if b_prefs else 0.0

        # Average of both parents' overlap scores
        return (a_overlap + b_overlap) / 2.0
    except (TypeError, AttributeError):
        return 0.0


def _length_fit(pref_length: object, cand_length: object) -> float | None:
    """Score a name's length against one length preference.

    Returns 1.0 for a direct match, MIDDLE_CREDIT for a "middle" name (the
    candidate is medium, or the parent has no strong preference via "any"),
    0.0 for the opposite end, or None when there is nothing to score.
    """
    if not cand_length:
        return None
    if pref_length == "any":
        return MIDDLE_CREDIT  # No strong preference → treat as middle ground
    if not pref_length:
        return None
    if cand_length == "medium":
        return MIDDLE_CREDIT  # Between short and long
    return 1.0 if pref_length == cand_length else 0.0


def _age_fit(pref_age: object, cand_age: object) -> float | None:
    """Score a name's age style against one age preference.

    "old" maps to candidate "classic", "new" to "modern". "balanced" means no
    strong preference (middle credit). "timeless" candidates are themselves a
    middle style and get middle credit against a specific preference.
    """
    if not cand_age:
        return None
    if pref_age == "balanced":
        return MIDDLE_CREDIT  # No strong preference → middle ground
    if not pref_age:
        return None
    if cand_age == "timeless":
        return MIDDLE_CREDIT  # Between classic and modern
    if pref_age == "old":
        return 1.0 if cand_age == "classic" else 0.0
    if pref_age == "new":
        return 1.0 if cand_age == "modern" else 0.0
    return None


def _historical_fit(pref_hist: object, cand_hist_score: object) -> float | None:
    """Score a name's historical significance against one preference.

    historical_significance_score is a float in [0, 1]. We treat <0.3 as low,
    0.3-0.7 as the middle band, and >0.7 as high. A direct match scores 1.0,
    the opposite end 0.0, and the middle band MIDDLE_CREDIT either way.
    """
    if cand_hist_score is None or not pref_hist:
        return None
    try:
        score = float(cand_hist_score)
    except (TypeError, ValueError):
        return None

    if score < 0.3:
        band = "low"
    elif score <= 0.7:
        band = "medium"
    else:
        band = "high"

    if band == "medium":
        return 1.0 if pref_hist == "medium" else MIDDLE_CREDIT
    # band is "low" or "high": full credit on match, middle pref gets partial,
    # opposite end gets nothing.
    if pref_hist == band:
        return 1.0
    if pref_hist == "medium":
        return MIDDLE_CREDIT
    return 0.0


def explicit_filter_fit_score(
    candidate: dict | None,
    preferences: dict | None,
) -> float:
    """
    Score how well a name matches explicit preferences (length, age, historical).

    Honors each preference axis independently and gives partial ("middle")
    credit to compromise names so they still surface, ranked below direct
    matches. ``preferences`` may be a single merged couple profile or one
    parent's profile; ``explicit_filter_fit_score_for_parents`` averages two
    parents to honor each individually.

    Args:
        candidate: Dict with name payload (length_category, age_style_category,
                   historical_significance_score).
        preferences: Dict with preferences (preferred_length, preferred_age,
                     historical_importance).

    Returns:
        Float in [0.0, 1.0]. 0.0 if any data is missing.
    """
    if not candidate or not preferences:
        return 0.0

    try:
        axis_scores = [
            _length_fit(
                preferences.get("preferred_length"), candidate.get("length_category")
            ),
            _age_fit(
                preferences.get("preferred_age"), candidate.get("age_style_category")
            ),
            _historical_fit(
                preferences.get("historical_importance"),
                candidate.get("historical_significance_score"),
            ),
        ]
        scored = [s for s in axis_scores if s is not None]
        if not scored:
            return 0.0
        return sum(scored) / len(scored)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def explicit_filter_fit_score_for_parents(
    candidate: dict | None,
    parent_a_profile: dict | None,
    parent_b_profile: dict | None,
) -> float:
    """
    Score explicit filter fit against each parent independently, then average.

    Unlike scoring against a single merged profile (which collapses to a
    neutral value when parents disagree, erasing the signal), this honors each
    parent's stated length/age/historical preference. A name that strongly
    matches one parent therefore outranks a bland compromise that matches
    neither.

    When only one parent's preferences are available, falls back to that
    parent's score.

    Returns:
        Float in [0.0, 1.0]. 0.0 if no preference data is available.
    """
    if not candidate:
        return 0.0

    a_has = bool(parent_a_profile) and _has_explicit_prefs(parent_a_profile)
    b_has = bool(parent_b_profile) and _has_explicit_prefs(parent_b_profile)

    if a_has and b_has:
        a_score = explicit_filter_fit_score(candidate, parent_a_profile)
        b_score = explicit_filter_fit_score(candidate, parent_b_profile)
        return (a_score + b_score) / 2.0
    if a_has:
        return explicit_filter_fit_score(candidate, parent_a_profile)
    if b_has:
        return explicit_filter_fit_score(candidate, parent_b_profile)
    return 0.0


def _has_explicit_prefs(profile: dict) -> bool:
    """True when a profile carries at least one explicit length/age/historical pref."""
    return any(
        profile.get(key)
        for key in ("preferred_length", "preferred_age", "historical_importance")
    )


def bridge_score(
    candidate: dict | None,
    parent_a_bg: list[str] | None,
    parent_b_bg: list[str] | None,
    residence_country: str | None,
) -> float:
    """
    Score how well a name bridges both parents' backgrounds + residence country fit.

    A bridge name has origins that overlap with BOTH parents' backgrounds
    and/or has good usability in the residence country.

    Args:
        candidate: Dict with name payload (origin_backgrounds, languages).
        parent_a_bg: List of parent A's cultural backgrounds.
        parent_b_bg: List of parent B's cultural backgrounds.
        residence_country: ISO 3166-1 alpha-2 country code.

    Returns:
        Float in [0.0, 1.0]. 0.0 if any data is missing.
    """
    if not candidate:
        return 0.0

    try:
        name_origins = set(candidate.get("origin_backgrounds") or [])
        if not name_origins:
            return 0.0

        score = 0.0
        components = 0

        # Bridge component: name overlaps with both parents
        a_bg = set(parent_a_bg or [])
        b_bg = set(parent_b_bg or [])

        if a_bg and b_bg:
            components += 1
            a_match = bool(name_origins & a_bg)
            b_match = bool(name_origins & b_bg)
            if a_match and b_match:
                score += 1.0  # Perfect bridge
            elif a_match or b_match:
                score += 0.4  # Partial bridge

        # Residence country fit: name's languages include residence country language
        if residence_country:
            components += 1
            from core.services.country_languages import get_country_languages

            residence_langs = get_country_languages(residence_country)
            name_languages = set(candidate.get("languages") or [])

            if residence_langs and (name_languages & residence_langs):
                score += 1.0
            elif name_languages and len(name_languages) > 2:
                # International names get partial credit
                score += 0.5

        if components == 0:
            return 0.0

        return score / components
    except (TypeError, AttributeError):
        return 0.0


def novelty_score(
    candidate: dict | None,
    previously_seen_origins: set[str] | list[str] | None,
) -> float:
    """
    Bonus for origins not yet seen in the current deck.

    Rewards names that introduce new cultural backgrounds to the deck.

    Args:
        candidate: Dict with name payload (origin_backgrounds).
        previously_seen_origins: Set/list of origin strings already in the deck.

    Returns:
        Float in [0.0, 1.0]. 0.0 if data is missing.
    """
    if not candidate:
        return 0.0

    try:
        name_origins = set(candidate.get("origin_backgrounds") or [])
        if not name_origins:
            return 0.0

        seen = set(previously_seen_origins or [])
        if not seen:
            return 1.0  # First name always gets full novelty

        # Proportion of name's origins that are new
        new_origins = name_origins - seen
        return len(new_origins) / len(name_origins)
    except (TypeError, AttributeError):
        return 0.0


def diversity_score(
    candidate: dict | None,
    current_deck_so_far: list[dict] | None,
) -> float:
    """
    Bonus for varying first letter, origin, and style within the deck.

    Rewards names that differ from what's already in the deck.

    Args:
        candidate: Dict with name payload (canonical_name, origin_backgrounds,
                   age_style_category).
        current_deck_so_far: List of candidate dicts already selected for the deck.

    Returns:
        Float in [0.0, 1.0]. 0.0 if data is missing.
    """
    if not candidate:
        return 0.0

    try:
        if not current_deck_so_far:
            return 1.0  # First name always gets full diversity

        score = 0.0
        components = 0

        # First letter diversity
        cand_first_letter = _first_letter(candidate.get("canonical_name"))
        if cand_first_letter:
            components += 1
            first_letters = {
                first_letter
                for d in current_deck_so_far
                if (first_letter := _first_letter(d.get("canonical_name"))) is not None
            }
            if cand_first_letter not in first_letters:
                score += 1.0
            else:
                # Penalize proportionally to how many names share this letter
                same_letter_count = sum(
                    1
                    for d in current_deck_so_far
                    if _first_letter(d.get("canonical_name")) == cand_first_letter
                )
                score += max(0.0, 1.0 - (same_letter_count / len(current_deck_so_far)))

        # Origin diversity
        cand_origins = set(candidate.get("origin_backgrounds") or [])
        if cand_origins:
            components += 1
            seen_origins = set()
            for d in current_deck_so_far:
                seen_origins.update(d.get("origin_backgrounds") or [])
            new_origins = cand_origins - seen_origins
            if new_origins:
                score += len(new_origins) / len(cand_origins)
            else:
                score += 0.2  # Small base score even if origins overlap

        # Style diversity
        cand_style = candidate.get("age_style_category")
        if cand_style:
            components += 1
            deck_styles = [d.get("age_style_category") for d in current_deck_so_far if d.get("age_style_category")]
            if cand_style not in deck_styles:
                score += 1.0
            else:
                style_count = deck_styles.count(cand_style)
                score += max(0.0, 1.0 - (style_count / len(current_deck_so_far)))

        if components == 0:
            return 0.0

        return score / components
    except (TypeError, AttributeError):
        return 0.0
