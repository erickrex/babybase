"""Property-based tests for the constellation projection math service.

Uses Hypothesis to verify formal invariants of the pure projection functions
in ``core/services/projection.py`` (``pca_project_2d`` and ``normalize_axes``).
Each property maps to a correctness property from the design document.

These functions are pure numpy math with no Django/Qdrant/DB dependencies, so
the tests do not touch the database.

Feature: constellation-and-cross-cultural-mode
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from core.services.projection import normalize_axes, pca_project_2d

# ---------------------------------------------------------------------------
# Custom Strategies
# ---------------------------------------------------------------------------

# Finite float64 values bounded well within range so centering and SVD do not
# overflow. width=64 matches the float64 precision the implementation uses.
finite_float = st.floats(
    allow_nan=False,
    allow_infinity=False,
    width=64,
    min_value=-1e6,
    max_value=1e6,
)


@st.composite
def st_matrix(draw, min_rows=2, max_rows=20, min_cols=8, max_cols=32):
    """Generate an ``n x d`` matrix of finite float64 rows of equal length.

    n >= 2 so the projection has at least two points; d is kept small (8-32)
    to keep SVD runs fast. The algorithm is dimension-agnostic, so a modest d
    exercises the same code path as the production 1024-dim vectors.
    """
    n = draw(st.integers(min_value=min_rows, max_value=max_rows))
    d = draw(st.integers(min_value=min_cols, max_value=max_cols))
    row = st.lists(finite_float, min_size=d, max_size=d)
    return draw(st.lists(row, min_size=n, max_size=n))


@st.composite
def st_coords_with_constant_axis(draw):
    """Generate ``(x, y)`` coords where one axis is exactly constant.

    Returns ``(coords, axis_index)`` where every value on ``axis_index`` is the
    same literal value (so min == max on that axis), while the other axis varies
    freely. Used to exercise the degenerate-axis -> 0.5 normalization rule.
    """
    n = draw(st.integers(min_value=1, max_value=30))
    constant_value = draw(finite_float)
    axis_index = draw(st.sampled_from([0, 1]))
    other_values = draw(st.lists(finite_float, min_size=n, max_size=n))

    coords = []
    for other in other_values:
        if axis_index == 0:
            coords.append((constant_value, other))
        else:
            coords.append((other, constant_value))
    return coords, axis_index


# ---------------------------------------------------------------------------
# Property 1: Normalized coordinates stay in range
# Feature: constellation-and-cross-cultural-mode, Property 1: Normalized coordinates stay in range
# ---------------------------------------------------------------------------


class TestNormalizedCoordinatesInRange:
    """
    **Validates: Requirements 2.1, 2.2, 2.3, 16.1**

    For any finite input matrix with >= 2 rows, every coordinate produced by
    ``normalize_axes(pca_project_2d(matrix))`` is within ``[0.0, 1.0]``.
    """

    @given(matrix=st_matrix())
    @settings(max_examples=100)
    def test_normalized_coords_within_unit_range(self, matrix):
        """Every normalized x and y falls within the inclusive [0, 1] range."""
        coords = normalize_axes(pca_project_2d(matrix))

        assert len(coords) == len(matrix)
        for x, y in coords:
            assert 0.0 <= x <= 1.0, f"x={x} out of [0, 1]"
            assert 0.0 <= y <= 1.0, f"y={y} out of [0, 1]"


# ---------------------------------------------------------------------------
# Property 2: Projection determinism
# Feature: constellation-and-cross-cultural-mode, Property 2: Projection determinism
# ---------------------------------------------------------------------------


class TestProjectionDeterminism:
    """
    **Validates: Requirements 3.1, 3.2, 3.4, 16.2**

    For any input matrix, two independent calls to ``pca_project_2d`` (then
    ``normalize_axes``) produce coordinates that are exactly equal element-wise
    (absolute difference 0.0).
    """

    @given(matrix=st_matrix())
    @settings(max_examples=100)
    def test_two_calls_are_exactly_equal(self, matrix):
        """Running the projection twice yields bit-for-bit identical output."""
        first = normalize_axes(pca_project_2d(matrix))
        second = normalize_axes(pca_project_2d(matrix))

        assert len(first) == len(second) == len(matrix)
        for (x1, y1), (x2, y2) in zip(first, second):
            assert abs(x1 - x2) == 0.0, f"x differs: {x1} != {x2}"
            assert abs(y1 - y2) == 0.0, f"y differs: {y1} != {y2}"


# ---------------------------------------------------------------------------
# Property 4: Degenerate axis maps to 0.5
# Feature: constellation-and-cross-cultural-mode, Property 4: Degenerate axis maps to 0.5
# ---------------------------------------------------------------------------


class TestDegenerateAxisMapsToHalf:
    """
    **Validates: Requirements 2.4**

    For any set of coordinates where all values on an axis are equal,
    ``normalize_axes`` assigns exactly 0.5 to every value on that axis (no NaN,
    no division error).
    """

    @given(data=st_coords_with_constant_axis())
    @settings(max_examples=100)
    def test_constant_axis_becomes_half(self, data):
        """A flat (min == max) axis normalizes every value on it to exactly 0.5."""
        coords, axis_index = data

        normalized = normalize_axes(coords)

        assert len(normalized) == len(coords)
        for point in normalized:
            value = point[axis_index]
            assert value == 0.5, f"constant axis value {value} != 0.5"


# ---------------------------------------------------------------------------
# Property 5: Empty input is safe
# Feature: constellation-and-cross-cultural-mode, Property 5: Empty input is safe
# ---------------------------------------------------------------------------


class TestEmptyInputIsSafe:
    """
    **Validates: Requirements 2.5**

    ``normalize_axes([])`` returns ``[]`` and raises nothing.
    """

    def test_empty_input_returns_empty(self):
        """Normalizing an empty coordinate list returns an empty list."""
        assert normalize_axes([]) == []


# ---------------------------------------------------------------------------
# Property 6: Output cardinality preserved
# Feature: constellation-and-cross-cultural-mode, Property 6: Output cardinality preserved
# ---------------------------------------------------------------------------


class TestOutputCardinalityPreserved:
    """
    **Validates: Requirements 1.2, 1.3**

    For any input matrix of ``n`` rows, ``pca_project_2d`` returns exactly
    ``n`` ``(x, y)`` pairs.
    """

    @given(matrix=st_matrix())
    @settings(max_examples=100)
    def test_output_row_count_matches_input(self, matrix):
        """The projection returns exactly one (x, y) pair per input row."""
        projected = pca_project_2d(matrix)

        assert len(projected) == len(matrix)
        for point in projected:
            assert len(point) == 2, f"expected 2D point, got {point!r}"
