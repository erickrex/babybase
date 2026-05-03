"""Relevance scoring service for name re-ranking.

Each scoring signal is an independent, null-safe method returning a float in [0.0, 1.0].
Missing data always returns 0.0 — never crashes, never penalizes.
"""

# Scoring weights from design doc
W_SEMANTIC = 0.35
W_COUPLE_OVERLAP = 0.20
W_FILTER_FIT = 0.15
W_BRIDGE = 0.10
W_NOVELTY = 0.10
W_DIVERSITY = 0.10


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


def explicit_filter_fit_score(
    candidate: dict | None,
    preferences: dict | None,
) -> float:
    """
    Score how well a name matches explicit couple preferences (length, age style, historical).

    Args:
        candidate: Dict with name payload (length_category, age_style_category,
                   historical_significance_score).
        preferences: Dict with couple preferences (preferred_length, preferred_age,
                     historical_importance).

    Returns:
        Float in [0.0, 1.0]. 0.0 if any data is missing.
    """
    if not candidate or not preferences:
        return 0.0

    try:
        score = 0.0
        checks = 0

        # Length match
        pref_length = preferences.get("preferred_length")
        cand_length = candidate.get("length_category")
        if pref_length and pref_length != "any" and cand_length:
            checks += 1
            if pref_length == cand_length:
                score += 1.0
        elif pref_length == "any":
            checks += 1
            score += 1.0  # "any" always matches

        # Age style match
        pref_age = preferences.get("preferred_age")
        cand_age = candidate.get("age_style_category")
        if pref_age and cand_age:
            checks += 1
            if pref_age == "balanced":
                score += 0.8  # balanced accepts all styles with slight preference
            elif pref_age == "old" and cand_age == "classic":
                score += 1.0
            elif pref_age == "new" and cand_age == "modern":
                score += 1.0
            elif cand_age == "timeless":
                score += 0.7  # timeless partially matches any preference

        # Historical importance match
        pref_hist = preferences.get("historical_importance")
        cand_hist_score = candidate.get("historical_significance_score")
        if pref_hist and cand_hist_score is not None:
            checks += 1
            cand_hist_score = float(cand_hist_score)
            if pref_hist == "high" and cand_hist_score > 0.7:
                score += 1.0
            elif pref_hist == "high" and cand_hist_score > 0.3:
                score += 0.5
            elif pref_hist == "medium" and 0.3 <= cand_hist_score <= 0.7:
                score += 1.0
            elif pref_hist == "medium":
                score += 0.5
            elif pref_hist == "low" and cand_hist_score < 0.3:
                score += 1.0
            elif pref_hist == "low" and cand_hist_score < 0.7:
                score += 0.5

        if checks == 0:
            return 0.0

        return score / checks
    except (TypeError, ValueError, AttributeError):
        return 0.0


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
