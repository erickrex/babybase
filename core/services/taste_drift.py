"""Taste drift tracking service for BabyBase.

Analyzes swipe patterns to summarize how a couple's taste evolves over time.
After each swipe session, recomputes parent vectors and generates a drift summary.
"""

from core.models import Couple, Swipe


def compute_taste_drift(couple: Couple) -> dict:
    """
    Analyze swipe patterns and summarize taste drift for the couple.

    Returns a dict with:
        - summary: Human-readable drift insight string
        - converging_traits: List of traits the couple is converging on
        - session_count: Number of swipe sessions analyzed
    """
    liked_names = _get_recent_liked_names(couple)

    if not liked_names:
        return {
            "summary": "",
            "converging_traits": [],
            "session_count": 0,
        }

    # Analyze patterns in liked names
    length_counts: dict[str, int] = {}
    style_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}

    for name in liked_names:
        # Length
        length = name.length_category
        if length:
            length_counts[length] = length_counts.get(length, 0) + 1

        # Style
        style = name.age_style_category
        if style:
            style_counts[style] = style_counts.get(style, 0) + 1

        # Origins
        for origin in (name.origin_backgrounds or []):
            origin_counts[origin] = origin_counts.get(origin, 0) + 1

        # Languages (proxy for international appeal)
        for lang in (name.languages or []):
            language_counts[lang] = language_counts.get(lang, 0) + 1

    total_likes = len(liked_names)
    converging_traits = []

    # Determine dominant patterns (>50% of likes)
    dominant_length = _get_dominant(length_counts, total_likes, threshold=0.5)
    dominant_style = _get_dominant(style_counts, total_likes, threshold=0.5)

    # Check if names are international (appear in 3+ languages on average)
    avg_languages = sum(len(n.languages or []) for n in liked_names) / max(total_likes, 1)
    is_international = avg_languages > 2.5

    if dominant_length:
        converging_traits.append(dominant_length)
    if dominant_style:
        converging_traits.append(dominant_style)
    if is_international:
        converging_traits.append("international")

    # Build summary text
    summary = _build_drift_summary(converging_traits, total_likes)

    return {
        "summary": summary,
        "converging_traits": converging_traits,
        "session_count": total_likes,
    }


def _get_recent_liked_names(couple: Couple, limit: int = 50):
    """Get the most recent liked names for the couple (both parents)."""
    from core.models import Name

    recent_liked_name_ids = list(
        Swipe.objects.filter(couple=couple, action="like")
        .order_by("-created_at")
        .values_list("name_id", flat=True)
        .distinct()[:limit]
    )

    if not recent_liked_name_ids:
        return []

    return list(Name.objects.filter(id__in=recent_liked_name_ids))


def _get_dominant(counts: dict[str, int], total: int, threshold: float = 0.5) -> str | None:
    """Return the dominant category if it exceeds the threshold proportion."""
    if not counts or total == 0:
        return None

    top_key = max(counts, key=counts.get)  # type: ignore[arg-type]
    if counts[top_key] / total >= threshold:
        return top_key
    return None


def _build_drift_summary(traits: list[str], total_likes: int) -> str:
    """Build a human-readable drift summary from converging traits."""
    if not traits:
        if total_likes < 5:
            return "Keep swiping to discover your shared taste!"
        return "Your taste is diverse — no strong convergence yet."

    trait_text = ", ".join(traits)
    return f"Your taste converges on {trait_text} names."
