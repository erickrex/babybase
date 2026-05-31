"""Constellation projection service for BabyBase.

Pure, dependency-light math for the `compute_projections` management command.
The functions here reduce high-dimensional Qdrant `semantic` vectors to 2D
coordinates and normalize them to the ``[0, 1]`` range expected by the
constellation API and frontend.

Only numpy is used (already importable under ``uv run``); scikit-learn is
intentionally not a dependency. Functions are deterministic and side-effect
free so they can be unit- and property-tested in isolation.
"""

import logging
import time

import numpy as np

logger = logging.getLogger(__name__)

# PCA to 2D needs at least this many points to be meaningful.
INSUFFICIENT_VECTORS = 3

# Number of point ids fetched per Qdrant `retrieve` call to bound payload size.
_RETRIEVE_BATCH_SIZE = 256

# Bounded retry policy for transient Qdrant errors during retrieval.
_MAX_RETRIEVE_ATTEMPTS = 4  # 1 initial attempt + 3 retries (Req 5.1)
_RETRY_BACKOFF_SECONDS = 1.0  # wait at least 1s between attempts (Req 5.1)


def normalize_axes(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Min-max normalize each axis independently to the inclusive range ``[0.0, 1.0]``.

    Each of the two coordinate axes (x and y) is rescaled in linear proportion
    to its position between that axis's minimum and maximum value, so the
    minimum maps to ``0.0``, the maximum maps to ``1.0``, and intermediate
    values fall proportionally in between. Results are clamped to ``[0.0, 1.0]``
    to guard against floating-point drift past the bounds.

    Args:
        coords: A list of ``(x, y)`` coordinate tuples to normalize.

    Returns:
        A list of normalized ``(x, y)`` tuples in the same order as the input.

        - Empty input returns an empty list without raising.
        - If an axis has equal minimum and maximum (no spread), every value on
          that axis is assigned ``0.5`` to avoid division by zero.
    """
    if not coords:
        return []

    arr = np.asarray(coords, dtype=np.float64)
    result = np.empty_like(arr)

    for axis in range(arr.shape[1]):
        column = arr[:, axis]
        axis_min = column.min()
        axis_max = column.max()

        if axis_max == axis_min:
            # Degenerate axis: no spread, so map everything to the midpoint.
            result[:, axis] = 0.5
        else:
            scaled = (column - axis_min) / (axis_max - axis_min)
            result[:, axis] = np.clip(scaled, 0.0, 1.0)

    return [(float(x), float(y)) for x, y in result]


def _fix_sign_convention(components: np.ndarray) -> np.ndarray:
    """Force a deterministic sign on each principal component.

    SVD only determines each singular vector up to a sign, so the same input
    can yield components that differ only by an overall sign flip across runs
    or platforms. To remove that ambiguity, each component (row) is flipped so
    that its largest absolute-magnitude entry is positive.

    Args:
        components: A 2D array whose rows are principal components (right
            singular vectors).

    Returns:
        A new array of the same shape with the sign convention applied. The
        input is not mutated.
    """
    fixed = np.array(components, dtype=np.float64, copy=True)
    for i in range(fixed.shape[0]):
        row = fixed[i]
        # First index of the largest-magnitude loading (argmax is deterministic
        # on ties, picking the lowest index).
        max_idx = int(np.argmax(np.abs(row)))
        if row[max_idx] < 0.0:
            fixed[i] = -row
    return fixed


def pca_project_2d(matrix: list[list[float]]) -> list[tuple[float, float]]:
    """Project an ``(n x d)`` matrix of vectors to ``(n x 2)`` via SVD-based PCA.

    The projection is deterministic and reproducible: it uses 64-bit double
    precision throughout, numpy's deterministic SVD path (no random seed or
    randomized solver), and a fixed per-component sign convention
    (:func:`_fix_sign_convention`). Rows are projected in input order, so the
    caller is responsible for ordering rows by name id when stable, identity
    independent output is required.

    Steps:
        1. Convert to a float64 ndarray.
        2. Center each column (subtract the column mean).
        3. ``U, S, Vt = np.linalg.svd(centered, full_matrices=False)``.
        4. Take the top 2 right singular vectors (``Vt[:2]``) as components.
        5. Force the sign convention on those components.
        6. Project: ``centered @ components.T`` -> ``(n x 2)``.

    Args:
        matrix: A list of equal-length numeric rows (the vectors to project).

    Returns:
        A list of exactly ``n`` ``(x, y)`` float tuples, one per input row, in
        input order. Empty input returns an empty list. When the data has
        fewer than 2 usable principal components (for example a single column,
        or fewer distinct directions than 2), the missing axis is padded with
        ``0.0`` so every row always has 2 dimensions.
    """
    if not matrix:
        return []

    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("pca_project_2d expects a 2D matrix of shape (n, d).")

    n_rows = arr.shape[0]

    # Center columns so PCA captures variance about the mean (Req 1.2).
    column_means = arr.mean(axis=0)
    centered = arr - column_means

    # Deterministic SVD: full_matrices=False keeps Vt at min(n, d) rows, so we
    # never materialize a d x d matrix for the 1024-dim semantic vectors.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)

    # Top 2 right singular vectors as principal axes, sign-stabilized.
    components = _fix_sign_convention(vt[:2])

    projected = centered @ components.T

    # Guarantee exactly 2 dimensions per row even when fewer than 2 components
    # exist (e.g. a single-column matrix); pad the missing axis with 0.0.
    if projected.shape[1] < 2:
        padding = np.zeros((n_rows, 2 - projected.shape[1]), dtype=np.float64)
        projected = np.hstack([projected, padding])

    return [(float(x), float(y)) for x, y in projected]


def fetch_semantic_vectors(name_ids: list[str]) -> dict[str, list[float]]:
    """Fetch ``semantic`` named vectors from Qdrant, keyed by name id.

    Resolves each name id to its Qdrant point id via :class:`NameVectorIndexRef`,
    then retrieves the points in batches (``with_vectors=["semantic"]``) and maps
    each returned point's vector back to its originating name id.

    Names without a :class:`NameVectorIndexRef` mapping, and points that return
    no vector or a null/absent ``semantic`` vector, are simply omitted from the
    result (Req 4.1) rather than raising.

    Transient Qdrant connection/timeout errors are retried up to 3 additional
    times (4 attempts total) with at least a 1 second wait between successive
    attempts; the underlying error is re-raised after the attempts are
    exhausted (Req 5.1, 5.2). The caller is responsible for aborting cleanly so
    that no coordinates are partially written.

    Args:
        name_ids: The name ids whose semantic vectors should be retrieved.

    Returns:
        A mapping ``{name_id: semantic_vector}`` containing only names that have
        both an index ref and a retrievable non-null semantic vector.
    """
    from django.conf import settings

    from core.models import NameVectorIndexRef
    from core.services.qdrant_client import get_qdrant_client

    if not name_ids:
        return {}

    # Map Qdrant point id -> name id so retrieved points can be associated back
    # to their names. str() keys make the mapping robust to UUID vs str id types.
    point_to_name: dict[str, str] = {}
    for name_id, point_id in NameVectorIndexRef.objects.filter(
        name_id__in=name_ids
    ).values_list("name_id", "qdrant_point_id"):
        point_to_name[str(point_id)] = str(name_id)

    if not point_to_name:
        return {}

    client = get_qdrant_client()
    collection = settings.QDRANT_COLLECTION
    all_point_ids = list(point_to_name.keys())

    result: dict[str, list[float]] = {}
    for start in range(0, len(all_point_ids), _RETRIEVE_BATCH_SIZE):
        batch = all_point_ids[start : start + _RETRIEVE_BATCH_SIZE]
        points = _retrieve_with_retry(client, collection, batch)
        for point in points:
            vector = getattr(point, "vector", None)
            if not vector or "semantic" not in vector:
                continue
            semantic = vector["semantic"]
            if semantic is None:
                continue
            name_id = point_to_name.get(str(point.id))
            if name_id is not None:
                result[name_id] = semantic

    return result


def _retrieve_with_retry(client, collection: str, point_ids: list[str]) -> list:
    """Retrieve a batch of points, retrying transient Qdrant errors.

    Retries connection/timeout failures up to 3 additional times (4 attempts
    total) with at least a 1 second pause between attempts, then re-raises the
    last error (Req 5.1, 5.2). Logs use ``%s`` interpolation and never include
    credentials or request bodies (Req 5.4, 14.2).

    Args:
        client: The Qdrant client.
        collection: The collection name to retrieve from.
        point_ids: The string point ids to retrieve in this batch.

    Returns:
        The list of retrieved points for the batch.
    """
    from qdrant_client.http.exceptions import UnexpectedResponse

    for attempt in range(1, _MAX_RETRIEVE_ATTEMPTS + 1):
        try:
            return client.retrieve(
                collection_name=collection,
                ids=point_ids,
                with_vectors=["semantic"],
            )
        except (UnexpectedResponse, ConnectionError, TimeoutError) as exc:
            if attempt >= _MAX_RETRIEVE_ATTEMPTS:
                logger.error(
                    "Qdrant retrieve failed after %s attempts for %s points: %s",
                    attempt,
                    len(point_ids),
                    exc,
                )
                raise
            logger.warning(
                "Qdrant retrieve attempt %s of %s failed for %s points, "
                "retrying in %ss: %s",
                attempt,
                _MAX_RETRIEVE_ATTEMPTS,
                len(point_ids),
                _RETRY_BACKOFF_SECONDS,
                exc,
            )
            time.sleep(_RETRY_BACKOFF_SECONDS)

    # Unreachable: the loop either returns or raises, but keeps type checkers happy.
    return []
