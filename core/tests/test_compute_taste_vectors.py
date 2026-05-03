"""Unit tests for _compute_taste_vectors and the refactored callers (Task 13)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_couple():
    """Create a mock couple with user_a and user_b."""
    couple = MagicMock()
    couple.id = uuid.uuid4()
    couple.user_a = MagicMock()
    couple.user_a.id = uuid.uuid4()
    couple.user_b = MagicMock()
    couple.user_b.id = uuid.uuid4()
    return couple


@pytest.fixture
def mock_couple_solo():
    """Create a mock couple with only user_a (no partner yet)."""
    couple = MagicMock()
    couple.id = uuid.uuid4()
    couple.user_a = MagicMock()
    couple.user_a.id = uuid.uuid4()
    couple.user_b = None
    return couple


class TestComputeTasteVectors:
    """Tests for _compute_taste_vectors helper."""

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    def test_returns_averaged_vectors_when_both_parents_have_likes(
        self, mock_get_vectors, mock_couple
    ):
        """Should return (a_avg, b_avg) when both parents have liked vectors."""
        a_vectors = [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]
        b_vectors = [[2.0, 3.0, 4.0], [4.0, 5.0, 6.0]]

        mock_get_vectors.side_effect = [a_vectors, b_vectors]

        from core.services.onboarding import _compute_taste_vectors

        result = _compute_taste_vectors(mock_couple)

        assert result is not None
        a_avg, b_avg = result
        # a_avg = average of [1,2,3] and [3,4,5] = [2,3,4]
        assert a_avg == [2.0, 3.0, 4.0]
        # b_avg = average of [2,3,4] and [4,5,6] = [3,4,5]
        assert b_avg == [3.0, 4.0, 5.0]

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    def test_returns_none_when_user_a_has_no_likes(self, mock_get_vectors, mock_couple):
        """Should return None when user_a has no liked vectors."""
        mock_get_vectors.side_effect = [[], [[1.0, 2.0, 3.0]]]

        from core.services.onboarding import _compute_taste_vectors

        result = _compute_taste_vectors(mock_couple)
        assert result is None

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    def test_returns_none_when_user_b_has_no_likes(self, mock_get_vectors, mock_couple):
        """Should return None when user_b has no liked vectors."""
        mock_get_vectors.side_effect = [[[1.0, 2.0, 3.0]], []]

        from core.services.onboarding import _compute_taste_vectors

        result = _compute_taste_vectors(mock_couple)
        assert result is None

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    def test_returns_none_when_no_user_b(self, mock_get_vectors, mock_couple_solo):
        """Should return None when couple has no user_b."""
        mock_get_vectors.return_value = [[1.0, 2.0, 3.0]]

        from core.services.onboarding import _compute_taste_vectors

        result = _compute_taste_vectors(mock_couple_solo)
        assert result is None


class TestComputeBridgeCentroidRefactored:
    """Tests verifying compute_bridge_centroid produces same output after refactor."""

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    def test_returns_midpoint_when_both_parents_have_likes(
        self, mock_get_vectors, mock_couple
    ):
        """Should return midpoint of both parents' averaged vectors."""
        a_vectors = [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]
        b_vectors = [[2.0, 3.0, 4.0], [4.0, 5.0, 6.0]]

        mock_get_vectors.side_effect = [a_vectors, b_vectors]

        from core.services.onboarding import compute_bridge_centroid

        result = compute_bridge_centroid(mock_couple)

        # a_avg = [2, 3, 4], b_avg = [3, 4, 5], midpoint = [2.5, 3.5, 4.5]
        assert result == [2.5, 3.5, 4.5]

    @patch("core.services.onboarding.build_couple_query_embedding")
    @patch("core.services.onboarding._get_liked_vectors_for_user")
    def test_falls_back_to_query_embedding_when_no_likes(
        self, mock_get_vectors, mock_build_embedding, mock_couple
    ):
        """Should fall back to build_couple_query_embedding when _compute_taste_vectors returns None."""
        mock_get_vectors.return_value = []
        mock_build_embedding.return_value = [0.5, 0.5, 0.5]

        from core.services.onboarding import compute_bridge_centroid

        result = compute_bridge_centroid(mock_couple)

        assert result == [0.5, 0.5, 0.5]
        mock_build_embedding.assert_called_once_with(mock_couple)


class TestBuildCoupleQueryEmbeddingRefactored:
    """Tests verifying build_couple_query_embedding produces same output after refactor."""

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    @patch("core.services.onboarding._get_liked_vectors_for_couple")
    def test_uses_taste_vectors_midpoint_when_no_mutual_likes(
        self, mock_couple_vectors, mock_user_vectors, mock_couple
    ):
        """Should use _compute_taste_vectors midpoint when no mutual likes exist."""
        mock_couple_vectors.return_value = []  # No mutual likes

        a_vectors = [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]
        b_vectors = [[2.0, 3.0, 4.0], [4.0, 5.0, 6.0]]
        mock_user_vectors.side_effect = [a_vectors, b_vectors]

        from core.services.onboarding import build_couple_query_embedding

        result = build_couple_query_embedding(mock_couple)

        # a_avg = [2, 3, 4], b_avg = [3, 4, 5], midpoint = [2.5, 3.5, 4.5]
        assert result == [2.5, 3.5, 4.5]

    @patch("core.services.onboarding._get_liked_vectors_for_couple")
    def test_uses_mutual_likes_when_available(self, mock_couple_vectors, mock_couple):
        """Should use averaged mutual likes when they exist (Phase 2 mutual)."""
        mock_couple_vectors.return_value = [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]

        from core.services.onboarding import build_couple_query_embedding

        result = build_couple_query_embedding(mock_couple)

        # average of [1,2,3] and [3,4,5] = [2,3,4]
        assert result == [2.0, 3.0, 4.0]

    @patch("core.services.onboarding.generate_embedding", create=True)
    @patch("core.services.onboarding._get_liked_vectors_for_user")
    @patch("core.services.onboarding._get_liked_vectors_for_couple")
    def test_falls_back_to_onboarding_embedding_when_no_likes(
        self, mock_couple_vectors, mock_user_vectors, mock_generate, mock_couple
    ):
        """Should fall back to onboarding text embedding when no likes exist."""
        mock_couple_vectors.return_value = []
        mock_user_vectors.return_value = []

        mock_generate.return_value = [0.1, 0.2, 0.3]

        from core.services.onboarding import build_couple_query_embedding

        with patch("core.services.onboarding.build_couple_retrieval_profile") as mock_profile, \
             patch("core.services.onboarding.build_couple_profile_text") as mock_text, \
             patch("core.services.embeddings.generate_embedding", return_value=[0.1, 0.2, 0.3]):
            mock_profile.return_value = {"preferred_backgrounds": []}
            mock_text.return_value = "test text"

            result = build_couple_query_embedding(mock_couple)

        # Falls through to Phase 1
        assert result == [0.1, 0.2, 0.3]


class TestBothFunctionsProduceSameOutput:
    """
    Verify that both compute_bridge_centroid and build_couple_query_embedding
    produce the same midpoint output when taste vectors are available
    (i.e., the shared _compute_taste_vectors path).
    """

    @patch("core.services.onboarding._get_liked_vectors_for_user")
    @patch("core.services.onboarding._get_liked_vectors_for_couple")
    def test_both_produce_same_midpoint_with_taste_vectors(
        self, mock_couple_vectors, mock_user_vectors, mock_couple
    ):
        """Both functions should produce identical midpoint when taste vectors exist."""
        a_vectors = [[1.0, 0.0, 4.0], [3.0, 2.0, 6.0]]
        b_vectors = [[0.0, 1.0, 2.0], [2.0, 3.0, 4.0]]

        # For build_couple_query_embedding: no mutual likes, then taste vectors
        mock_couple_vectors.return_value = []

        # _get_liked_vectors_for_user will be called twice per function call
        # (once for user_a, once for user_b)
        mock_user_vectors.side_effect = [
            a_vectors, b_vectors,  # First call (build_couple_query_embedding)
            a_vectors, b_vectors,  # Second call (compute_bridge_centroid)
        ]

        from core.services.onboarding import (
            build_couple_query_embedding,
            compute_bridge_centroid,
        )

        result_query = build_couple_query_embedding(mock_couple)
        result_bridge = compute_bridge_centroid(mock_couple)

        # Both should produce the same midpoint
        # a_avg = [2, 1, 5], b_avg = [1, 2, 3], midpoint = [1.5, 1.5, 4.0]
        expected = [1.5, 1.5, 4.0]
        assert result_query == expected
        assert result_bridge == expected
        assert result_query == result_bridge
