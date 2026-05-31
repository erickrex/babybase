"""Command tests for ``compute_projections`` (Task 4.3, Qdrant mocked).

Exercises the orchestration in
``core/management/commands/compute_projections.py`` end to end with the Qdrant
retrieval boundary (``fetch_semantic_vectors``) mocked, asserting the
persistence-selection, abort, reporting, and order-independence behavior the
command is responsible for.

The command imports ``fetch_semantic_vectors`` at module top, so it is patched
at ``core.management.commands.compute_projections.fetch_semantic_vectors`` (the
name it is looked up under) rather than at the service module.

Feature: constellation-and-cross-cultural-mode
Validates: Requirements 1.5, 1.6, 1.7, 3.3, 4.2, 4.3, 4.4, 5.3, 6.1, 6.2, 6.4
"""

import io
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import Name
from core.services.projection import normalize_axes, pca_project_2d

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_TARGET = "core.management.commands.compute_projections.fetch_semantic_vectors"


def _make_name(canonical: str, x_2d=None, y_2d=None, active: bool = True) -> Name:
    """Create an active Name row, optionally with pre-stored 2D coordinates."""
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
        active=active,
        x_2d=x_2d,
        y_2d=y_2d,
    )


def _run(force: bool = False) -> str:
    """Invoke the command, capturing stdout, and return the captured text."""
    out = io.StringIO()
    call_command("compute_projections", force=force, stdout=out)
    return out.getvalue()


def _expected_coords(vectors: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    """Replicate the command's projection to map each name id -> expected (x, y).

    Mirrors the command exactly: active names ordered by id, the PCA input matrix
    assembled from the has-vector names in that order, then per-axis normalized.
    """
    names = list(Name.objects.filter(active=True).order_by("id"))
    has_vector = [name for name in names if str(name.id) in vectors]
    matrix = [vectors[str(name.id)] for name in has_vector]
    coords = normalize_axes(pca_project_2d(matrix))
    return {str(name.id): coord for name, coord in zip(has_vector, coords)}


# Four mutually distinct vectors so PCA yields well-separated coordinates.
_VECTORS = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeProjectionsCommand:
    """End-to-end command behavior with the Qdrant retrieval boundary mocked."""

    def test_insufficient_vectors_writes_nothing_and_reports(self):
        """Fewer than 3 retrievable vectors -> no writes; insufficient message (Req 1.6, 4.4)."""
        names = [_make_name(f"Insufficient{i}") for i in range(4)]
        # Only 2 of the 4 names have a retrievable vector (< INSUFFICIENT_VECTORS).
        vectors = {str(names[0].id): _VECTORS[0], str(names[1].id): _VECTORS[1]}

        with patch(_PATCH_TARGET, return_value=vectors):
            output = _run(force=False)

        assert "Insufficient vectors" in output
        # No coordinates were written: every name still has null x_2d / y_2d.
        for name in names:
            name.refresh_from_db()
            assert name.x_2d is None
            assert name.y_2d is None

    def test_without_force_only_fills_null_and_leaves_stored_zero_untouched(self):
        """Without --force, only x_2d-null names are written; a stored 0.0 is untouched (Req 6.2)."""
        n1 = _make_name("FillMe1")  # x_2d is None -> should be written
        n2 = _make_name("FillMe2")  # x_2d is None -> should be written
        # Stored valid coordinate of 0.0 (distinct from null); y sentinel proves no write.
        n3 = _make_name("AlreadyStored", x_2d=0.0, y_2d=0.42)
        n4 = _make_name("FillMe3")  # x_2d is None -> should be written

        vectors = {
            str(n1.id): _VECTORS[0],
            str(n2.id): _VECTORS[1],
            str(n3.id): _VECTORS[2],
            str(n4.id): _VECTORS[3],
        }
        expected = _expected_coords(vectors)

        with patch(_PATCH_TARGET, return_value=vectors):
            output = _run(force=False)

        # The three x_2d-null names received their computed coordinates.
        for name in (n1, n2, n4):
            name.refresh_from_db()
            exp_x, exp_y = expected[str(name.id)]
            assert name.x_2d == pytest.approx(exp_x)
            assert name.y_2d == pytest.approx(exp_y)

        # The name with a stored 0.0 was left exactly as it was.
        n3.refresh_from_db()
        assert n3.x_2d == 0.0
        assert n3.y_2d == 0.42

        # All four participated in the projection; only three were written.
        assert "Projected 4" in output
        assert "wrote 3" in output

    def test_force_overwrites_all_including_stored_zero(self):
        """With --force, every has-vector name is overwritten, including the stored 0.0 (Req 6.1)."""
        n1 = _make_name("OverwriteMe1")
        n2 = _make_name("OverwriteMe2")
        n3 = _make_name("StoredZero", x_2d=0.0, y_2d=0.42)
        n4 = _make_name("OverwriteMe3")

        vectors = {
            str(n1.id): _VECTORS[0],
            str(n2.id): _VECTORS[1],
            str(n3.id): _VECTORS[2],
            str(n4.id): _VECTORS[3],
        }
        expected = _expected_coords(vectors)

        with patch(_PATCH_TARGET, return_value=vectors):
            output = _run(force=True)

        # Every name now carries its freshly computed coordinate.
        for name in (n1, n2, n3, n4):
            name.refresh_from_db()
            exp_x, exp_y = expected[str(name.id)]
            assert name.x_2d == pytest.approx(exp_x)
            assert name.y_2d == pytest.approx(exp_y)

        # The previously stored (0.0, 0.42) coordinate was overwritten.
        n3.refresh_from_db()
        assert (n3.x_2d, n3.y_2d) != (0.0, 0.42)

        assert "wrote 4" in output

    def test_qdrant_failure_aborts_with_error_and_changes_nothing(self):
        """A Qdrant retrieval failure raises CommandError and writes nothing (Req 5.3)."""
        n1 = _make_name("Untouched1")  # null coords stay null
        n2 = _make_name("Untouched2", x_2d=0.25, y_2d=0.75)  # stored coords stay put
        n3 = _make_name("Untouched3")

        with patch(_PATCH_TARGET, side_effect=ConnectionError("qdrant unreachable")):
            with pytest.raises(CommandError):
                _run(force=True)

        # No coordinate changed: nulls remain null, stored values remain identical.
        n1.refresh_from_db()
        n2.refresh_from_db()
        n3.refresh_from_db()
        assert n1.x_2d is None and n1.y_2d is None
        assert n2.x_2d == 0.25 and n2.y_2d == 0.75
        assert n3.x_2d is None and n3.y_2d is None

    def test_reports_projected_and_skipped_counts(self):
        """Output reports the projected count and the skipped (no-vector) count (Req 4.3)."""
        with_vectors = [_make_name(f"HasVec{i}") for i in range(3)]
        without_vectors = [_make_name(f"NoVec{i}") for i in range(2)]

        vectors = {
            str(with_vectors[0].id): _VECTORS[0],
            str(with_vectors[1].id): _VECTORS[1],
            str(with_vectors[2].id): _VECTORS[2],
        }

        with patch(_PATCH_TARGET, return_value=vectors):
            output = _run(force=False)

        # 3 names projected, 2 skipped for lack of a retrievable vector.
        assert "Projected 3" in output
        assert "skipped 2" in output
        # The two vectorless names keep their (null) coordinates.
        for name in without_vectors:
            name.refresh_from_db()
            assert name.x_2d is None
            assert name.y_2d is None

    # Feature: constellation-and-cross-cultural-mode, Property 3: Order independence
    def test_order_independence_same_coords_regardless_of_fetch_order(self):
        """Persisted coords per name are identical regardless of fetch dict order (Req 3.3).

        The command sorts active names by id before assembling the PCA matrix, so
        the order in which ``fetch_semantic_vectors`` yields its mapping must not
        change any name's stored coordinate.
        """
        n1 = _make_name("Order1")
        n2 = _make_name("Order2")
        n3 = _make_name("Order3")
        n4 = _make_name("Order4")

        pairs = [
            (str(n1.id), _VECTORS[0]),
            (str(n2.id), _VECTORS[1]),
            (str(n3.id), _VECTORS[2]),
            (str(n4.id), _VECTORS[3]),
        ]
        forward = dict(pairs)
        shuffled = dict(reversed(pairs))  # same mapping, different insertion order

        # First run with the forward ordering (force so it always writes).
        with patch(_PATCH_TARGET, return_value=forward):
            _run(force=True)
        first = {}
        for name in (n1, n2, n3, n4):
            name.refresh_from_db()
            first[str(name.id)] = (name.x_2d, name.y_2d)

        # Second run with the reversed ordering of the same name->vector mapping.
        with patch(_PATCH_TARGET, return_value=shuffled):
            _run(force=True)
        for name in (n1, n2, n3, n4):
            name.refresh_from_db()
            assert name.x_2d == pytest.approx(first[str(name.id)][0])
            assert name.y_2d == pytest.approx(first[str(name.id)][1])
