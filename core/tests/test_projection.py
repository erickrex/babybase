"""Unit tests for the constellation projection math service (Task 4.2).

Covers the pure functions in ``core/services/projection.py``:

- ``normalize_axes`` — per-axis min-max rescale to ``[0, 1]`` with degenerate
  and empty handling.
- ``pca_project_2d`` (and ``_fix_sign_convention``) — deterministic SVD-based
  2D projection with a fixed sign convention.
- ``fetch_semantic_vectors`` — Qdrant retrieval keyed by name id, with batching
  and bounded retry-then-raise behavior (Qdrant mocked).

The math functions are pure numpy and need no database. ``fetch_semantic_vectors``
resolves names via ``NameVectorIndexRef``, so those tests use real DB rows.

Feature: constellation-and-cross-cultural-mode
Validates: Requirements 1.1, 1.2, 4.1, 5.1, 5.2
"""

import uuid
from unittest.mock import Mock, patch

import numpy as np
import pytest
from django.test import override_settings
from django.utils import timezone

from core.models import Name, NameVectorIndexRef
from core.services.projection import (
    _fix_sign_convention,
    fetch_semantic_vectors,
    normalize_axes,
    pca_project_2d,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_name(canonical: str) -> Name:
    """Create a minimal active Name row with all required fields populated."""
    return Name.objects.create(
        canonical_name=canonical,
        display_name=canonical,
        gender_usage=["girl"],
        origin_backgrounds=["Greek"],
        languages=["en"],
        scripts=["Latin"],
        variants=[],
        length_category="short",
        age_style_category="classic",
        historical_significance_score=0.5,
        semantic_summary="A test name.",
        active=True,
    )


def _make_ref(name: Name, point_id: uuid.UUID) -> NameVectorIndexRef:
    """Link a Name to a Qdrant point id via NameVectorIndexRef."""
    return NameVectorIndexRef.objects.create(
        name=name,
        qdrant_collection="test_names",
        qdrant_point_id=point_id,
        embedding_version="v1",
        indexed_at=timezone.now(),
    )


def _make_point(point_id, vector):
    """Build a stub Qdrant point exposing ``.id`` and ``.vector`` only."""
    point = Mock()
    point.id = point_id
    point.vector = vector
    return point


# ---------------------------------------------------------------------------
# normalize_axes
# ---------------------------------------------------------------------------


class TestNormalizeAxes:
    """Unit tests for ``normalize_axes``."""

    def test_empty_input_returns_empty(self):
        """An empty coordinate list returns an empty list without raising."""
        assert normalize_axes([]) == []

    def test_hand_computed_example_with_degenerate_y_axis(self):
        """x rescales linearly to [0, 1, 0.5]; the flat y axis collapses to 0.5."""
        coords = [(0.0, 5.0), (10.0, 5.0), (5.0, 5.0)]

        result = normalize_axes(coords)

        assert result == [(0.0, 0.5), (1.0, 0.5), (0.5, 0.5)]

    def test_both_axes_rescaled_independently(self):
        """Each axis is min-max scaled on its own min/max, mapping to [0, 1]."""
        # x in [1, 3] -> [0.0, 1.0, 0.5]; y in [-2, 4] -> [0.0, 1.0, 0.5].
        coords = [(1.0, -2.0), (3.0, 4.0), (2.0, 1.0)]

        result = normalize_axes(coords)

        assert result == [(0.0, 0.0), (1.0, 1.0), (0.5, 0.5)]

    def test_output_stays_within_unit_range(self):
        """Every returned coordinate is within the inclusive [0, 1] range."""
        coords = [(-100.0, 0.0), (0.0, 50.0), (100.0, -50.0), (25.0, 12.5)]

        result = normalize_axes(coords)

        assert len(result) == len(coords)
        for x, y in result:
            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0

    def test_both_axes_degenerate_map_to_half(self):
        """When both axes are flat, every coordinate becomes (0.5, 0.5)."""
        coords = [(7.0, 3.0), (7.0, 3.0), (7.0, 3.0)]

        result = normalize_axes(coords)

        assert result == [(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]


# ---------------------------------------------------------------------------
# _fix_sign_convention
# ---------------------------------------------------------------------------


class TestFixSignConvention:
    """Unit tests for the deterministic sign convention helper."""

    def test_largest_magnitude_loading_forced_positive(self):
        """Each component is flipped so its largest-|value| entry is positive."""
        components = np.array(
            [
                [-0.8, 0.1, 0.2],  # largest |value| is -0.8 at idx 0 -> flip
                [0.3, -0.9, 0.1],  # largest |value| is -0.9 at idx 1 -> flip
            ]
        )

        fixed = _fix_sign_convention(components)

        # Row 0 flipped: largest-magnitude entry (idx 0) is now positive.
        assert fixed[0][np.argmax(np.abs(fixed[0]))] > 0.0
        np.testing.assert_array_equal(fixed[0], np.array([0.8, -0.1, -0.2]))
        # Row 1 flipped: largest-magnitude entry (idx 1) is now positive.
        assert fixed[1][np.argmax(np.abs(fixed[1]))] > 0.0
        np.testing.assert_array_equal(fixed[1], np.array([-0.3, 0.9, -0.1]))

    def test_already_positive_loading_is_unchanged(self):
        """A component whose largest entry is already positive is left as-is."""
        components = np.array([[0.9, -0.2, 0.1]])

        fixed = _fix_sign_convention(components)

        np.testing.assert_array_equal(fixed[0], np.array([0.9, -0.2, 0.1]))

    def test_input_is_not_mutated(self):
        """The helper returns a new array and does not mutate its input."""
        components = np.array([[-0.8, 0.1, 0.2]])
        original = components.copy()

        _fix_sign_convention(components)

        np.testing.assert_array_equal(components, original)


# ---------------------------------------------------------------------------
# pca_project_2d
# ---------------------------------------------------------------------------


class TestPcaProject2d:
    """Unit tests for ``pca_project_2d``."""

    def test_cardinality_preserved(self):
        """The projection returns exactly one (x, y) pair per input row."""
        matrix = [
            [1.0, 2.0, 3.0, 4.0],
            [4.0, 3.0, 2.0, 1.0],
            [2.0, 2.0, 2.0, 2.0],
            [0.0, 1.0, 0.0, 1.0],
        ]

        projected = pca_project_2d(matrix)

        assert len(projected) == len(matrix)
        for point in projected:
            assert len(point) == 2

    def test_empty_input_returns_empty(self):
        """An empty matrix projects to an empty list."""
        assert pca_project_2d([]) == []

    def test_is_deterministic_across_two_calls(self):
        """Two independent calls on the same matrix are bit-for-bit identical."""
        matrix = [
            [3.1, -1.2, 0.4, 5.0],
            [-2.0, 4.4, 1.1, -3.3],
            [0.5, 0.5, -2.2, 2.2],
            [1.0, -1.0, 1.0, -1.0],
        ]

        first = pca_project_2d(matrix)
        second = pca_project_2d(matrix)

        assert first == second

    def test_sign_convention_largest_loading_positive(self):
        """The point with the larger value on the dominant axis gets a larger x.

        The matrix varies only along the first dimension, so the dominant
        principal component aligns with that dimension. Under the fixed sign
        convention (largest-|value| loading forced positive), the row with the
        most-positive value on the dominant dimension receives the largest x.
        """
        matrix = [
            [-10.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0, 0.0],
        ]

        projected = pca_project_2d(matrix)
        xs = [x for x, _ in projected]

        # Monotonic in the dominant dimension: -10 -> 0 -> 10 maps to increasing x.
        assert xs[0] < xs[1] < xs[2]

    def test_three_point_fixture_separates_along_dominant_axis(self):
        """A 3-point set spread along one direction separates along x, not y."""
        matrix = [
            [-5.0, 0.01, 0.0],
            [0.0, -0.02, 0.0],
            [5.0, 0.01, 0.0],
        ]

        projected = pca_project_2d(matrix)
        xs = [x for x, _ in projected]
        ys = [y for _, y in projected]

        x_spread = max(xs) - min(xs)
        y_spread = max(ys) - min(ys)

        # The dominant (first) direction dominates the spread along x.
        assert x_spread > y_spread
        # Points remain ordered along x by their position on the dominant axis.
        assert xs[0] < xs[1] < xs[2]


# ---------------------------------------------------------------------------
# fetch_semantic_vectors (Qdrant mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFetchSemanticVectors:
    """Unit tests for ``fetch_semantic_vectors`` with a mocked Qdrant client."""

    def test_empty_name_ids_returns_empty_without_calling_qdrant(self):
        """No name ids short-circuits to an empty result and no client call."""
        with patch("core.services.qdrant_client.get_qdrant_client") as mock_get_client:
            result = fetch_semantic_vectors([])

        assert result == {}
        mock_get_client.assert_not_called()

    def test_name_without_index_ref_is_omitted_and_qdrant_not_called(self):
        """Names with no NameVectorIndexRef are omitted; Qdrant is not queried."""
        name = _make_name("NoRefName")

        with patch("core.services.qdrant_client.get_qdrant_client") as mock_get_client:
            result = fetch_semantic_vectors([str(name.id)])

        assert result == {}
        mock_get_client.assert_not_called()

    @override_settings(QDRANT_COLLECTION="test_names")
    def test_returns_vectors_keyed_by_name_id_and_omits_missing_or_null(self):
        """Refs with a non-null semantic vector are returned; others are omitted."""
        name_a = _make_name("HasVector")
        name_b = _make_name("NullVector")
        name_c = _make_name("NoRef")  # intentionally has no index ref
        name_d = _make_name("MissingSemanticKey")

        point_a = uuid.uuid4()
        point_b = uuid.uuid4()
        point_d = uuid.uuid4()
        _make_ref(name_a, point_a)
        _make_ref(name_b, point_b)
        _make_ref(name_d, point_d)

        returned_points = [
            _make_point(point_a, {"semantic": [0.1, 0.2, 0.3]}),
            _make_point(point_b, {"semantic": None}),
            _make_point(point_d, {"other_vector": [9.0, 9.0]}),
        ]

        mock_client = Mock()
        mock_client.retrieve.return_value = returned_points

        name_ids = [str(name_a.id), str(name_b.id), str(name_c.id), str(name_d.id)]
        with patch(
            "core.services.qdrant_client.get_qdrant_client", return_value=mock_client
        ):
            result = fetch_semantic_vectors(name_ids)

        # Only the name with a non-null semantic vector survives.
        assert result == {str(name_a.id): [0.1, 0.2, 0.3]}
        assert str(name_b.id) not in result  # null semantic vector
        assert str(name_c.id) not in result  # no index ref
        assert str(name_d.id) not in result  # no 'semantic' key

    @override_settings(QDRANT_COLLECTION="test_names")
    def test_retrieval_is_batched(self, monkeypatch):
        """Point ids are retrieved in batches; retrieve is called once per batch."""
        # Shrink the batch size so 3 refs span 2 batches (sizes 2 + 1).
        monkeypatch.setattr("core.services.projection._RETRIEVE_BATCH_SIZE", 2)

        names = [_make_name(f"BatchName{i}") for i in range(3)]
        for name in names:
            _make_ref(name, uuid.uuid4())

        def fake_retrieve(collection_name, ids, with_vectors):
            return [_make_point(pid, {"semantic": [float(len(pid))]}) for pid in ids]

        mock_client = Mock()
        mock_client.retrieve.side_effect = fake_retrieve

        name_ids = [str(name.id) for name in names]
        with patch(
            "core.services.qdrant_client.get_qdrant_client", return_value=mock_client
        ):
            result = fetch_semantic_vectors(name_ids)

        # 3 ids with batch size 2 -> 2 retrieve calls, all vectors returned.
        assert mock_client.retrieve.call_count == 2
        assert len(result) == 3

    @override_settings(QDRANT_COLLECTION="test_names")
    def test_retries_then_raises_after_four_attempts(self):
        """Persistent connection errors are retried to 4 total attempts, then re-raised."""
        name = _make_name("FlakyName")
        _make_ref(name, uuid.uuid4())

        mock_client = Mock()
        mock_client.retrieve.side_effect = ConnectionError("qdrant unreachable")

        with (
            patch(
                "core.services.qdrant_client.get_qdrant_client", return_value=mock_client
            ),
            patch("core.services.projection.time.sleep") as mock_sleep,
        ):
            with pytest.raises(ConnectionError):
                fetch_semantic_vectors([str(name.id)])

        # 1 initial attempt + 3 retries = 4 total; sleeps between attempts (3 waits).
        assert mock_client.retrieve.call_count == 4
        assert mock_sleep.call_count == 3
