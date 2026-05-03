"""Unit tests for _fetch_vectors_for_name_ids helper (Task 12.4)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings


class TestFetchVectorsForNameIds:
    """Tests verifying _fetch_vectors_for_name_ids returns expected vectors."""

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_returns_semantic_vectors_for_valid_name_ids(
        self, mock_nvir_objects, mock_get_client
    ):
        """Should return semantic vectors for name IDs that have Qdrant points."""
        name_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        point_id_1 = uuid.uuid4()
        point_id_2 = uuid.uuid4()

        # Mock NameVectorIndexRef lookup
        mock_nvir_objects.filter.return_value.values_list.return_value = [
            point_id_1,
            point_id_2,
        ]

        # Mock Qdrant client retrieve
        mock_point_1 = MagicMock()
        mock_point_1.vector = {"semantic": [0.1, 0.2, 0.3]}
        mock_point_2 = MagicMock()
        mock_point_2.vector = {"semantic": [0.4, 0.5, 0.6]}

        mock_client = MagicMock()
        mock_client.retrieve.return_value = [mock_point_1, mock_point_2]
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _fetch_vectors_for_name_ids

        result = _fetch_vectors_for_name_ids(name_ids)

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.retrieve.assert_called_once_with(
            collection_name="test_names",
            ids=[str(point_id_1), str(point_id_2)],
            with_vectors=["semantic"],
        )

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_returns_empty_list_when_no_point_ids_found(
        self, mock_nvir_objects, mock_get_client
    ):
        """Should return empty list when no NameVectorIndexRef records match."""
        name_ids = [str(uuid.uuid4())]

        # No point IDs found
        mock_nvir_objects.filter.return_value.values_list.return_value = []

        from core.services.onboarding import _fetch_vectors_for_name_ids

        result = _fetch_vectors_for_name_ids(name_ids)

        assert result == []
        mock_get_client.assert_not_called()

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_returns_empty_list_when_name_ids_is_empty(
        self, mock_nvir_objects, mock_get_client
    ):
        """Should return empty list when given an empty name_ids list."""
        from core.services.onboarding import _fetch_vectors_for_name_ids

        result = _fetch_vectors_for_name_ids([])

        assert result == []
        mock_nvir_objects.filter.assert_called_once()

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_skips_points_without_semantic_vector(
        self, mock_nvir_objects, mock_get_client
    ):
        """Should skip points that don't have a 'semantic' key in their vector."""
        name_ids = [str(uuid.uuid4())]
        point_id = uuid.uuid4()

        mock_nvir_objects.filter.return_value.values_list.return_value = [point_id]

        # One point with semantic, one without, one with None vector
        mock_point_with = MagicMock()
        mock_point_with.vector = {"semantic": [0.7, 0.8, 0.9]}
        mock_point_without = MagicMock()
        mock_point_without.vector = {"other_vector": [1.0, 2.0, 3.0]}
        mock_point_none = MagicMock()
        mock_point_none.vector = None

        mock_client = MagicMock()
        mock_client.retrieve.return_value = [
            mock_point_with,
            mock_point_without,
            mock_point_none,
        ]
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _fetch_vectors_for_name_ids

        result = _fetch_vectors_for_name_ids(name_ids)

        assert result == [[0.7, 0.8, 0.9]]

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_passes_correct_collection_name_and_point_ids(
        self, mock_nvir_objects, mock_get_client
    ):
        """Should use settings.QDRANT_COLLECTION and stringify point IDs."""
        name_ids = [str(uuid.uuid4())]
        point_id = uuid.uuid4()

        mock_nvir_objects.filter.return_value.values_list.return_value = [point_id]

        mock_client = MagicMock()
        mock_client.retrieve.return_value = []
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _fetch_vectors_for_name_ids

        _fetch_vectors_for_name_ids(name_ids)

        mock_client.retrieve.assert_called_once_with(
            collection_name="test_names",
            ids=[str(point_id)],
            with_vectors=["semantic"],
        )
