"""Qdrant vector search service for name retrieval."""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    NamedVector,
    SearchParams,
)

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Return a singleton QdrantClient configured from Django settings."""
    global _client
    if _client is None:
        url = getattr(settings, "QDRANT_URL", None)
        api_key = getattr(settings, "QDRANT_API_KEY", None)
        if not url:
            raise ImproperlyConfigured("QDRANT_URL must be set in Django settings.")
        logger.info("Initializing Qdrant client: url=%s", url)
        _client = QdrantClient(url=url, api_key=api_key)
    return _client


def _build_payload_filters(filters: dict | None) -> Filter | None:
    """Build Qdrant filter conditions from a dict of field->value pairs."""
    if not filters:
        return None

    must_conditions = []

    if "gender_usage" in filters:
        must_conditions.append(
            FieldCondition(key="gender_usage", match=MatchValue(value=filters["gender_usage"]))
        )

    if "active" in filters:
        must_conditions.append(
            FieldCondition(key="active", match=MatchValue(value=filters["active"]))
        )

    if "length_category" in filters:
        must_conditions.append(
            FieldCondition(key="length_category", match=MatchValue(value=filters["length_category"]))
        )

    if "age_style_category" in filters:
        must_conditions.append(
            FieldCondition(key="age_style_category", match=MatchValue(value=filters["age_style_category"]))
        )

    if not must_conditions:
        return None

    return Filter(must=must_conditions)


def search_names(
    embedding: list[float],
    filters: dict | None = None,
    limit: int = 50,
    exclude_ids: list[str] | None = None,
    vector_name: str = "semantic",
) -> list[dict]:
    """
    Filtered semantic search against the names collection.

    Args:
        embedding: Query vector (1536 dimensions).
        filters: Dict of payload field filters (e.g. {"gender_usage": "girl", "active": True}).
        limit: Max results to return.
        exclude_ids: List of Qdrant point ID strings to exclude.
        vector_name: Which named vector to search against.

    Returns:
        List of dicts with keys: point_id, name_id, canonical_name, score, payload.
    """
    client = get_qdrant_client()

    query_filter = _build_payload_filters(filters)

    # Add active=True filter by default if not specified
    if filters is None or "active" not in filters:
        active_condition = FieldCondition(key="active", match=MatchValue(value=True))
        if query_filter is None:
            query_filter = Filter(must=[active_condition])
        else:
            query_filter.must.append(active_condition)

    results = client.search(
        collection_name=settings.QDRANT_COLLECTION,
        query_vector=NamedVector(name=vector_name, vector=embedding),
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
        search_params=SearchParams(exact=False, hnsw_ef=128),
    )

    # Filter out excluded IDs in post-processing
    exclude_set = set(exclude_ids) if exclude_ids else set()

    output = []
    for hit in results:
        point_id_str = str(hit.id)
        if point_id_str in exclude_set:
            continue
        output.append(
            {
                "point_id": point_id_str,
                "name_id": hit.payload.get("name_id"),
                "canonical_name": hit.payload.get("canonical_name"),
                "score": hit.score,
                "payload": hit.payload,
            }
        )

    logger.debug(
        "Qdrant search: vector=%s limit=%d excluded=%d returned=%d",
        vector_name, limit, len(exclude_set), len(output),
    )
    return output


def get_similar_to_names(
    name_ids: list[str],
    filters: dict | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Find names similar to a set of anchor names.

    Fetches vectors for the given name IDs, averages them, and searches
    for nearest neighbors.

    Args:
        name_ids: List of Qdrant point ID strings to use as anchors.
        filters: Optional payload filters.
        limit: Max results to return.

    Returns:
        List of result dicts (same format as search_names).
    """
    if not name_ids:
        return []

    client = get_qdrant_client()

    # Fetch vectors for anchor points
    points = client.retrieve(
        collection_name=settings.QDRANT_COLLECTION,
        ids=[str(nid) for nid in name_ids],
        with_vectors=["semantic"],
    )

    if not points:
        return []

    # Average the semantic vectors
    vectors = []
    for point in points:
        if point.vector and "semantic" in point.vector:
            vectors.append(point.vector["semantic"])

    if not vectors:
        return []

    avg_vector = _average_vectors(vectors)

    # Search with the averaged vector, excluding the anchor points
    return search_names(
        embedding=avg_vector,
        filters=filters,
        limit=limit,
        exclude_ids=name_ids,
        vector_name="semantic",
    )


def get_bridge_candidates(
    parent_a_vector: list[float],
    parent_b_vector: list[float],
    filters: dict | None = None,
    limit: int = 50,
    residence_country: str | None = None,
) -> list[dict]:
    """
    Find bridge names by searching at the midpoint between two parent vectors.

    Applies international_score boosting and residence_country language filtering.

    Args:
        parent_a_vector: Parent A's taste vector (1536 dim).
        parent_b_vector: Parent B's taste vector (1536 dim).
        filters: Optional payload filters.
        limit: Max results to return.
        residence_country: ISO 3166-1 alpha-2 code for language filtering.

    Returns:
        List of result dicts (same format as search_names), with international_score
        boost applied and filtered to names usable in residence_country.
    """
    midpoint = _midpoint_vectors(parent_a_vector, parent_b_vector)

    # Retrieve more candidates for post-filtering
    retrieval_limit = limit * 2
    candidates = search_names(
        embedding=midpoint,
        filters=filters,
        limit=retrieval_limit,
        vector_name="semantic",
    )

    # Filter to names matching residence_country languages
    if residence_country:
        residence_langs = _get_country_languages(residence_country)
        if residence_langs:
            filtered = []
            for candidate in candidates:
                payload = candidate.get("payload", {})
                name_languages = set(payload.get("languages") or [])
                # Keep names that share at least one language with residence country
                # or have high international_score (usable anywhere)
                international_score = payload.get("international_score", 0.0)
                if name_languages & residence_langs or international_score >= 0.8:
                    filtered.append(candidate)
            # If filtering removed too many, fall back to unfiltered
            if len(filtered) >= limit // 2:
                candidates = filtered

    # Boost names with high international_score
    for candidate in candidates:
        payload = candidate.get("payload", {})
        international_score = payload.get("international_score", 0.0)
        if international_score and isinstance(international_score, (int, float)):
            # Boost the retrieval score by up to 15% based on international_score
            candidate["score"] = candidate.get("score", 0.0) + (international_score * 0.15)

    # Re-sort by boosted score
    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)

    return candidates[:limit]


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    """Compute element-wise average of multiple vectors."""
    if not vectors:
        return []
    n = len(vectors)
    dim = len(vectors[0])
    result = [0.0] * dim
    for vec in vectors:
        for i in range(dim):
            result[i] += vec[i]
    return [x / n for x in result]


def _midpoint_vectors(vec_a: list[float], vec_b: list[float]) -> list[float]:
    """Compute element-wise midpoint of two vectors."""
    return [(a + b) / 2.0 for a, b in zip(vec_a, vec_b)]


def _get_country_languages(country_code: str) -> set[str]:
    """Map ISO 3166-1 alpha-2 country code to primary language codes.

    Delegates to the shared country_languages utility.
    """
    from core.services.country_languages import get_country_languages

    return get_country_languages(country_code)
