"""Constellation (Name Map) views for BabyBase."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.models import MutualMatch, Name, Swipe, SwipeAction
from core.services.couples import get_couple_for_user

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def constellation_view(request: Request) -> Response:
    """
    Return constellation data for the 2D name map.

    GET /api/v1/constellation/

    Returns:
        - names: All active names with x,y positions and cluster labels
        - clusters: Unique cluster labels with their centroid positions
        - couple_centroids: Average x,y of each parent's liked names
        - matched_name_ids: List of matched name IDs (highlighted on map)
    """
    couple = get_couple_for_user(request.user)
    if not couple:
        return Response(
            {"status": "error", "message": "You must be in a couple to view the constellation."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get all active names with projections
    names = Name.objects.filter(active=True, x_2d__isnull=False, y_2d__isnull=False)

    # Build name data with cluster labels
    names_data = []
    cluster_points: dict[str, list[tuple[float, float]]] = {}

    for name in names:
        # Primary cluster label = first origin_background
        cluster_label = (name.origin_backgrounds[0] if name.origin_backgrounds else "Other")

        names_data.append({
            "id": str(name.id),
            "canonical_name": name.canonical_name,
            "display_name": name.display_name,
            "x": name.x_2d,
            "y": name.y_2d,
            "cluster": cluster_label,
            "origin_backgrounds": name.origin_backgrounds,
            "gender_usage": name.gender_usage,
            "age_style_category": name.age_style_category,
        })

        # Accumulate cluster points for centroid computation
        if cluster_label not in cluster_points:
            cluster_points[cluster_label] = []
        cluster_points[cluster_label].append((name.x_2d, name.y_2d))

    # Compute cluster centroids
    clusters = []
    for label, points in cluster_points.items():
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        clusters.append({
            "label": label,
            "centroid_x": round(cx, 4),
            "centroid_y": round(cy, 4),
            "count": len(points),
        })

    # Compute couple centroids (average position of each parent's liked names)
    couple_centroids = _compute_couple_centroids(couple)

    # Get matched name IDs
    matched_name_ids = list(
        MutualMatch.objects.filter(couple=couple)
        .values_list("name_id", flat=True)
    )
    matched_name_ids = [str(nid) for nid in matched_name_ids]

    return Response(
        {
            "status": "success",
            "data": {
                "names": names_data,
                "clusters": clusters,
                "couple_centroids": couple_centroids,
                "matched_name_ids": matched_name_ids,
            },
        },
        status=status.HTTP_200_OK,
    )


def _compute_couple_centroids(couple) -> dict:
    """
    Compute average x,y position of each parent's liked names.

    Returns dict with parent_a and parent_b centroids + radius.
    """
    result = {"parent_a": None, "parent_b": None}

    for key, user in [("parent_a", couple.user_a), ("parent_b", couple.user_b)]:
        if user is None:
            continue

        liked_name_ids = Swipe.objects.filter(
            couple=couple, user=user, action=SwipeAction.LIKE
        ).values_list("name_id", flat=True)

        liked_names = Name.objects.filter(
            id__in=liked_name_ids, x_2d__isnull=False, y_2d__isnull=False
        )

        if not liked_names.exists():
            continue

        positions = list(liked_names.values_list("x_2d", "y_2d"))
        cx = sum(p[0] for p in positions) / len(positions)
        cy = sum(p[1] for p in positions) / len(positions)

        # Compute radius as max distance from centroid to any liked name
        max_dist = 0.0
        for px, py in positions:
            dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            max_dist = max(max_dist, dist)

        result[key] = {
            "centroid_x": round(cx, 4),
            "centroid_y": round(cy, 4),
            "radius": round(max_dist, 4),
            "liked_count": len(positions),
        }

    return result
