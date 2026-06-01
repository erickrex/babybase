"""Qdrant vector search service for name retrieval."""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchValue,
    SearchParams,
)

from core.services.embeddings import validate_embedding_dimension

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
        _client = QdrantClient(
            url=url,
            api_key=api_key,
            timeout=getattr(settings, "QDRANT_TIMEOUT_SECONDS", 60),
        )
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
        embedding: Query vector (1024 dimensions).
        filters: Dict of payload field filters (e.g. {"gender_usage": "girl", "active": True}).
        limit: Max results to return.
        exclude_ids: List of Qdrant point ID strings to exclude.
        vector_name: Which named vector to search against.

    Returns:
        List of dicts with keys: point_id, name_id, canonical_name, score, payload.
    """
    validate_embedding_dimension(embedding, context="Qdrant query embedding")
    client = get_qdrant_client()

    query_filter = _build_payload_filters(filters)

    # Add active=True filter by default if not specified
    if filters is None or "active" not in filters:
        active_condition = FieldCondition(key="active", match=MatchValue(value=True))
        if query_filter is None:
            query_filter = Filter(must=[active_condition])
        else:
            query_filter.must.append(active_condition)

    exclude_list = list(dict.fromkeys(exclude_ids or []))
    exclude_set = set(exclude_list)
    if exclude_list:
        exclude_condition = HasIdCondition(has_id=exclude_list)
        if query_filter is None:
            query_filter = Filter(must_not=[exclude_condition])
        elif query_filter.must_not is None:
            query_filter.must_not = [exclude_condition]
        else:
            query_filter.must_not.append(exclude_condition)

    results = client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=embedding,
        using=vector_name,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
        search_params=SearchParams(exact=False, hnsw_ef=128),
    ).points

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
    vector_name: str = "semantic",
) -> list[dict]:
    """
    Find names similar to a set of anchor names.

    Fetches the named vectors for the given name IDs, averages them, and
    searches for nearest neighbors against the same named vector.

    Args:
        name_ids: List of Qdrant point ID strings to use as anchors.
        filters: Optional payload filters.
        limit: Max results to return.
        vector_name: Which named vector to anchor on and search against
            (e.g. "semantic" or "phonetic_style"). Defaults to "semantic",
            preserving the existing "More Like This" caller.

    Returns:
        List of result dicts (same format as search_names). Returns an empty
        list when no anchor IDs are given, no points are found, or none of the
        anchor points have a stored vector under vector_name.
    """
    if not name_ids:
        return []

    client = get_qdrant_client()

    # Fetch vectors for anchor points
    points = client.retrieve(
        collection_name=settings.QDRANT_COLLECTION,
        ids=[str(nid) for nid in name_ids],
        with_vectors=[vector_name],
    )

    if not points:
        return []

    # Average the stored named vectors
    vectors = []
    for point in points:
        if point.vector and vector_name in point.vector:
            vectors.append(point.vector[vector_name])

    if not vectors:
        # Req 8.7 / 11.4: missing stored vector → empty result, no crash
        return []

    avg_vector = _average_vectors(vectors)

    # Search with the averaged vector, excluding the anchor points
    return search_names(
        embedding=avg_vector,
        filters=filters,
        limit=limit,
        exclude_ids=name_ids,
        vector_name=vector_name,
    )


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
