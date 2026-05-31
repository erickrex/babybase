"""Build user-facing name map insights for the constellation endpoint."""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.contrib.auth import get_user_model

from core.models import (
    Couple,
    MatchStatus,
    MutualMatch,
    Name,
    OnboardingResponse,
    RecommendationDeck,
    Swipe,
    SwipeAction,
)
from core.services.couples import get_couple_for_user

User = get_user_model()

MIN_FEATURED_NAMES = 8
MAX_FEATURED_NAMES = 18
MAX_RECENT_LIKES = 40
MAX_RECOMMENDATIONS = 12
MAX_REPRESENTATIVE_SCAN = 200

STATUS_PRIORITY = {
    "shortlisted": 60,
    "matched": 50,
    "liked_by_you": 40,
    "liked_by_partner": 30,
    "recommended": 20,
    "starter": 10,
}


class NameMapContextError(Exception):
    """Raised when a user has no map-ready couple or solo onboarding context."""


def build_name_map(user: User) -> dict[str, Any]:
    """Build the constellation payload for a couple or an onboarded solo user."""
    couple = get_couple_for_user(user)
    if couple:
        return _build_couple_map(user, couple)

    solo_response = OnboardingResponse.objects.filter(user=user, couple=None).first()
    if not solo_response:
        raise NameMapContextError("Complete onboarding before viewing your name map.")

    return _build_solo_map(user, solo_response)


def _build_couple_map(user: User, couple: Couple) -> dict[str, Any]:
    featured: dict[str, dict[str, Any]] = {}

    matches = list(MutualMatch.objects.filter(couple=couple).select_related("name").order_by("-matched_at"))
    for match in matches:
        if not match.name.active:
            continue
        status = "shortlisted" if match.status == MatchStatus.SHORTLISTED else "matched"
        reason = "Shortlisted together" if status == "shortlisted" else "Matched by both parents"
        _add_featured_name(featured, match.name, status, reason, score=match.match_strength_score)

    liked_swipes = list(
        Swipe.objects.filter(couple=couple, action=SwipeAction.LIKE)
        .select_related("name", "user")
        .order_by("-created_at")[:MAX_RECENT_LIKES]
    )
    for swipe in liked_swipes:
        if not swipe.name.active:
            continue
        if swipe.user_id == user.id:
            _add_featured_name(featured, swipe.name, "liked_by_you", "Recently liked by you")
        else:
            _add_featured_name(featured, swipe.name, "liked_by_partner", "Recently liked by your partner")

    swiped_name_ids = set(Swipe.objects.filter(couple=couple).values_list("name_id", flat=True).distinct())
    latest_deck = RecommendationDeck.objects.filter(couple=couple).order_by("-created_at").first()
    if latest_deck:
        deck_items = (
            latest_deck.items.select_related("name")
            .exclude(name_id__in=swiped_name_ids)
            .order_by("rank")[:MAX_RECOMMENDATIONS]
        )
        for item in deck_items:
            if item.name.active:
                _add_featured_name(
                    featured,
                    item.name,
                    "recommended",
                    item.explanation_summary or "Recommended for your current taste",
                    score=item.rerank_score,
                    rank=item.rank,
                )

    responses = list(couple.onboarding_responses.select_related("user"))
    _fill_with_representatives(
        featured,
        responses,
        exclude_ids={item["id"] for item in featured.values()},
    )

    featured_names = _sorted_featured_names(featured)
    neighborhoods = _build_neighborhoods(featured_names)
    legacy = build_legacy_constellation(couple)
    parent_summary = _build_parent_summaries(couple, user)

    return {
        "mode": "couple" if couple.user_b_id else "solo_couple",
        "summary": _build_summary(
            mode="couple" if couple.user_b_id else "solo_couple",
            matched_count=len(matches),
            shortlisted_count=sum(1 for match in matches if match.status == MatchStatus.SHORTLISTED),
            featured_count=len(featured_names),
            current_user_likes=parent_summary["current_user"]["liked_count"],
            partner_likes=parent_summary["partner"]["liked_count"] if parent_summary["partner"] else 0,
            top_neighborhood=neighborhoods[0]["label"] if neighborhoods else None,
        ),
        "taste_neighborhoods": neighborhoods,
        "featured_names": featured_names,
        "parents": parent_summary,
        "explore": _build_explore(neighborhoods, featured_names, legacy),
        **legacy,
    }


def _build_solo_map(user: User, solo_response: OnboardingResponse) -> dict[str, Any]:
    featured: dict[str, dict[str, Any]] = {}
    _fill_with_representatives(featured, [solo_response], exclude_ids=set())

    featured_names = _sorted_featured_names(featured)
    neighborhoods = _build_neighborhoods(featured_names)
    legacy = build_legacy_constellation(None)

    parent_summary = {
        "current_user": {
            "label": "You",
            "liked_count": 0,
            "top_origins": list(solo_response.preferred_name_backgrounds[:3]),
            "top_styles": [_preference_age_label(solo_response.preferred_name_age)],
            "centroid": None,
        },
        "partner": None,
    }

    return {
        "mode": "solo",
        "summary": _build_summary(
            mode="solo",
            matched_count=0,
            shortlisted_count=0,
            featured_count=len(featured_names),
            current_user_likes=0,
            partner_likes=0,
            top_neighborhood=neighborhoods[0]["label"] if neighborhoods else None,
        ),
        "taste_neighborhoods": neighborhoods,
        "featured_names": featured_names,
        "parents": parent_summary,
        "explore": _build_explore(neighborhoods, featured_names, legacy),
        **legacy,
    }


def _add_featured_name(
    featured: dict[str, dict[str, Any]],
    name: Name,
    status: str,
    reason: str,
    *,
    score: float = 0.0,
    rank: int | None = None,
) -> None:
    name_id = str(name.id)
    next_item = _serialize_name(name, status=status, reasons=[reason], score=score, rank=rank)
    current = featured.get(name_id)
    if current is None:
        featured[name_id] = next_item
        return

    if STATUS_PRIORITY[status] > STATUS_PRIORITY[current["status"]]:
        next_item["reasons"] = _merge_reasons(next_item["reasons"], current["reasons"])
        next_item["score"] = max(next_item["score"], current["score"])
        next_item["rank"] = _best_rank(next_item["rank"], current["rank"])
        featured[name_id] = next_item
        return

    current["reasons"] = _merge_reasons(current["reasons"], [reason])
    current["score"] = max(current["score"], score)
    current["rank"] = _best_rank(current["rank"], rank)


def _fill_with_representatives(
    featured: dict[str, dict[str, Any]],
    responses: list[OnboardingResponse],
    *,
    exclude_ids: set[str],
) -> None:
    if len(featured) >= MIN_FEATURED_NAMES:
        return

    preferred_origins = {origin for response in responses for origin in response.preferred_name_backgrounds if origin}
    preferred_gender = {response.baby_gender_preference for response in responses}
    preferred_length = {response.preferred_name_length for response in responses}
    preferred_age = {response.preferred_name_age for response in responses}

    candidates = list(
        Name.objects.filter(active=True).order_by("-historical_significance_score", "display_name")[
            :MAX_REPRESENTATIVE_SCAN
        ]
    )

    ranked = sorted(
        (name for name in candidates if str(name.id) not in exclude_ids),
        key=lambda name: (
            -_preference_fit(
                name,
                preferred_origins,
                preferred_gender,
                preferred_length,
                preferred_age,
            ),
            name.display_name,
        ),
    )

    for name in ranked:
        if len(featured) >= MIN_FEATURED_NAMES:
            break
        _add_featured_name(featured, name, "starter", "Fits your stated preferences")


def _preference_fit(
    name: Name,
    origins: set[str],
    genders: set[str],
    lengths: set[str],
    ages: set[str],
) -> int:
    score = 0
    if origins and origins.intersection(name.origin_backgrounds):
        score += 4
    if "non_binary" in genders or not genders or genders.intersection(name.gender_usage):
        score += 2
    if "any" in lengths or not lengths or name.length_category in lengths:
        score += 1
    if not ages or _age_preference_matches(name.age_style_category, ages):
        score += 1
    return score


def _age_preference_matches(style: str, ages: set[str]) -> bool:
    if "balanced" in ages:
        return True
    if "old" in ages:
        return style in {"classic", "timeless"}
    if "new" in ages:
        return style == "modern"
    return False


def _sorted_featured_names(featured: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        featured.values(),
        key=lambda item: (
            -STATUS_PRIORITY[item["status"]],
            _rank_or_large(item["rank"]),
            -item["score"],
            item["display_name"],
        ),
    )[:MAX_FEATURED_NAMES]


def _build_neighborhoods(names: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for name in names:
        origin = name["origin_backgrounds"][0] if name["origin_backgrounds"] else "Global"
        style = name["age_style_category"] or "timeless"
        key = f"{style}:{origin}"
        label = f"{_display_label(style)} {origin}"
        group = grouped.setdefault(
            key,
            {
                "id": _slug(key),
                "label": label,
                "description": _neighborhood_description(style, origin),
                "count": 0,
                "matched_count": 0,
                "shortlisted_count": 0,
                "traits": {
                    "origins": [origin],
                    "styles": [style],
                    "genders": [],
                },
                "representative_names": [],
                "_all": [],
            },
        )
        group["count"] += 1
        if name["status"] == "matched":
            group["matched_count"] += 1
        if name["status"] == "shortlisted":
            group["shortlisted_count"] += 1
        group["_all"].append(name)

    neighborhoods = []
    for group in grouped.values():
        genders = Counter(gender for name in group["_all"] for gender in name["gender_usage"])
        group["traits"]["genders"] = [gender for gender, _ in genders.most_common(3)]
        group["representative_names"] = group["_all"][:4]
        del group["_all"]
        neighborhoods.append(group)

    return sorted(
        neighborhoods,
        key=lambda group: (
            -group["shortlisted_count"],
            -group["matched_count"],
            -group["count"],
            group["label"],
        ),
    )[:5]


def _build_summary(
    *,
    mode: str,
    matched_count: int,
    shortlisted_count: int,
    featured_count: int,
    current_user_likes: int,
    partner_likes: int,
    top_neighborhood: str | None,
) -> dict[str, Any]:
    stats = {
        "matched_count": matched_count,
        "shortlisted_count": shortlisted_count,
        "featured_count": featured_count,
        "current_user_likes": current_user_likes,
        "partner_likes": partner_likes,
    }

    if mode == "solo":
        body = (
            f"Your starter map is centered on {top_neighborhood}."
            if top_neighborhood
            else "Your starter map will sharpen as you like more names."
        )
        return {"title": "Your name taste", "body": body, "stats": stats}

    if mode == "solo_couple":
        body = (
            f"Your current likes point toward {top_neighborhood}."
            if top_neighborhood
            else "Like more names to build a clearer taste profile."
        )
        return {"title": "Your name taste", "body": body, "stats": stats}

    if shortlisted_count:
        body = f"{shortlisted_count} shortlisted names are anchoring your shared taste."
    elif matched_count:
        body = f"{matched_count} matched names show where your tastes overlap."
    elif current_user_likes and partner_likes:
        body = "Your likes are forming early shared neighborhoods."
    else:
        body = "Like more names to reveal stronger shared neighborhoods."

    if top_neighborhood:
        body = f"{body} The clearest neighborhood right now is {top_neighborhood}."

    return {"title": "Shared name taste", "body": body, "stats": stats}


def _build_parent_summaries(couple: Couple, current_user: User) -> dict[str, Any]:
    user_a_summary = _parent_summary(couple, couple.user_a, "Parent A")
    user_b_summary = _parent_summary(couple, couple.user_b, "Parent B") if couple.user_b else None

    if couple.user_a_id == current_user.id:
        current = {**user_a_summary, "label": "You"}
        partner = {**user_b_summary, "label": "Partner"} if user_b_summary else None
    else:
        current = {**user_b_summary, "label": "You"} if user_b_summary else _empty_parent_summary("You")
        partner = {**user_a_summary, "label": "Partner"}

    return {"current_user": current, "partner": partner}


def _parent_summary(couple: Couple, user: User | None, label: str) -> dict[str, Any]:
    if user is None:
        return _empty_parent_summary(label)

    liked_names = list(
        Name.objects.filter(
            swipes__couple=couple,
            swipes__user=user,
            swipes__action=SwipeAction.LIKE,
            active=True,
        ).distinct()
    )
    origins = Counter(origin for name in liked_names for origin in name.origin_backgrounds)
    styles = Counter(name.age_style_category for name in liked_names if name.age_style_category)

    return {
        "label": label,
        "liked_count": len(liked_names),
        "top_origins": [origin for origin, _ in origins.most_common(3)],
        "top_styles": [style for style, _ in styles.most_common(3)],
        "centroid": _compute_centroid(liked_names),
    }


def _empty_parent_summary(label: str) -> dict[str, Any]:
    return {
        "label": label,
        "liked_count": 0,
        "top_origins": [],
        "top_styles": [],
        "centroid": None,
    }


def build_legacy_constellation(couple: Couple | None) -> dict[str, Any]:
    """Return the legacy dot-map fields for secondary exploration."""
    names_qs = (
        Name.objects.filter(active=True, x_2d__isnull=False, y_2d__isnull=False)
        .order_by("display_name")
        .values(
            "id",
            "canonical_name",
            "display_name",
            "x_2d",
            "y_2d",
            "origin_backgrounds",
            "gender_usage",
            "age_style_category",
        )
    )

    names_data = []
    cluster_points: dict[str, list[tuple[float, float]]] = {}

    for name in names_qs:
        origins = name["origin_backgrounds"] or []
        cluster_label = origins[0] if origins else "Other"
        names_data.append(
            {
                "id": str(name["id"]),
                "canonical_name": name["canonical_name"],
                "display_name": name["display_name"],
                "x": name["x_2d"],
                "y": name["y_2d"],
                "cluster": cluster_label,
                "origin_backgrounds": origins,
                "gender_usage": name["gender_usage"],
                "age_style_category": name["age_style_category"],
            }
        )
        cluster_points.setdefault(cluster_label, []).append((name["x_2d"], name["y_2d"]))

    clusters = []
    for label, points in cluster_points.items():
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        clusters.append(
            {
                "label": label,
                "centroid_x": round(cx, 4),
                "centroid_y": round(cy, 4),
                "count": len(points),
            }
        )

    matched_name_ids: list[str] = []
    if couple:
        matched_name_ids = [
            str(name_id) for name_id in MutualMatch.objects.filter(couple=couple).values_list("name_id", flat=True)
        ]

    return {
        "names": names_data,
        "clusters": clusters,
        "couple_centroids": _compute_couple_centroids(couple) if couple else {"parent_a": None, "parent_b": None},
        "matched_name_ids": matched_name_ids,
    }


def _build_explore(
    neighborhoods: list[dict[str, Any]],
    featured_names: list[dict[str, Any]],
    legacy: dict[str, Any],
) -> dict[str, Any]:
    bubbles = []
    for neighborhood in neighborhoods:
        points = [
            (name["x"], name["y"])
            for name in neighborhood["representative_names"]
            if name["x"] is not None and name["y"] is not None
        ]
        if not points:
            points = [
                (name["x"], name["y"]) for name in featured_names if name["x"] is not None and name["y"] is not None
            ]
        centroid = _centroid_from_points(points)
        bubbles.append(
            {
                "id": neighborhood["id"],
                "label": neighborhood["label"],
                "count": neighborhood["count"],
                "centroid_x": centroid["centroid_x"] if centroid else 0.5,
                "centroid_y": centroid["centroid_y"] if centroid else 0.5,
                "matched_count": neighborhood["matched_count"],
                "shortlisted_count": neighborhood["shortlisted_count"],
            }
        )

    return {
        "bubbles": bubbles,
        "featured_name_ids": [name["id"] for name in featured_names],
        "all_name_count": len(legacy["names"]),
    }


def _compute_couple_centroids(couple: Couple) -> dict[str, Any]:
    result = {"parent_a": None, "parent_b": None}

    for key, user in [("parent_a", couple.user_a), ("parent_b", couple.user_b)]:
        if user is None:
            continue

        positions = list(
            Name.objects.filter(
                swipes__couple=couple,
                swipes__user=user,
                swipes__action=SwipeAction.LIKE,
                x_2d__isnull=False,
                y_2d__isnull=False,
            ).values_list("x_2d", "y_2d")
        )
        if not positions:
            continue

        centroid = _centroid_from_points(positions)
        if centroid is None:
            continue

        max_dist = 0.0
        for px, py in positions:
            dist = ((px - centroid["centroid_x"]) ** 2 + (py - centroid["centroid_y"]) ** 2) ** 0.5
            max_dist = max(max_dist, dist)

        result[key] = {
            **centroid,
            "radius": round(max_dist, 4),
            "liked_count": len(positions),
        }

    return result


def _compute_centroid(names: list[Name]) -> dict[str, Any] | None:
    points = [(name.x_2d, name.y_2d) for name in names if name.x_2d is not None and name.y_2d is not None]
    centroid = _centroid_from_points(points)
    if centroid is None:
        return None

    return {**centroid, "liked_count": len(points)}


def _centroid_from_points(points: list[tuple[float, float]]) -> dict[str, float] | None:
    if not points:
        return None
    return {
        "centroid_x": round(sum(point[0] for point in points) / len(points), 4),
        "centroid_y": round(sum(point[1] for point in points) / len(points), 4),
    }


def _serialize_name(
    name: Name,
    *,
    status: str,
    reasons: list[str],
    score: float = 0.0,
    rank: int | None = None,
) -> dict[str, Any]:
    return {
        "id": str(name.id),
        "canonical_name": name.canonical_name,
        "display_name": name.display_name,
        "origin_backgrounds": name.origin_backgrounds,
        "gender_usage": name.gender_usage,
        "length_category": name.length_category,
        "age_style_category": name.age_style_category,
        "historical_significance_score": name.historical_significance_score,
        "x": name.x_2d,
        "y": name.y_2d,
        "status": status,
        "reasons": reasons,
        "score": score,
        "rank": rank,
    }


def _merge_reasons(primary: list[str], secondary: list[str]) -> list[str]:
    merged = []
    for reason in [*primary, *secondary]:
        if reason and reason not in merged:
            merged.append(reason)
    return merged[:3]


def _rank_or_large(rank: int | None) -> int:
    return rank if rank is not None else 9999


def _best_rank(first: int | None, second: int | None) -> int | None:
    rank = min(_rank_or_large(first), _rank_or_large(second))
    return None if rank == 9999 else rank


def _display_label(value: str) -> str:
    return value.replace("_", " ").title()


def _preference_age_label(value: str) -> str:
    if value == "new":
        return "modern"
    if value == "old":
        return "classic"
    return "balanced"


def _neighborhood_description(style: str, origin: str) -> str:
    return f"{_display_label(style)} names with {origin} roots."


def _slug(value: str) -> str:
    return value.lower().replace(":", "-").replace("/", "-").replace(" ", "-").replace("_", "-")
