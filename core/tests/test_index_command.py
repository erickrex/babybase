"""Unit tests for index_names_to_qdrant command dimension changes."""

import uuid
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from core.management.commands.index_names_to_qdrant import (
    COLLECTION_NAME,
    EMBEDDING_VERSION,
    VECTOR_DIM,
    Command,
)
from core.models import Name, NameVectorIndexRef


def test_vector_dim_constant_is_1024():
    """
    VECTOR_DIM must be 1024 to match Nova Embed output dimensions.

    Validates: Requirements 2.2
    """
    assert VECTOR_DIM == 1024
    assert EMBEDDING_VERSION == "titan-embed-text-v2"


@patch("core.management.commands.index_names_to_qdrant.get_qdrant_client")
def test_collection_creation_uses_1024_for_all_named_vectors(mock_get_client):
    """
    When creating a new collection, all three named vectors (semantic,
    phonetic_style, cross_cultural) must use size=1024.

    Validates: Requirements 2.1
    """
    from django.core.management import call_command

    # Set up mock client
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    # Mock get_collections to return empty list (collection doesn't exist)
    mock_collections_response = MagicMock()
    mock_collections_response.collections = []
    mock_client.get_collections.return_value = mock_collections_response

    # Mock Name.objects to return empty queryset (no names to index)
    with patch("core.management.commands.index_names_to_qdrant.Name") as mock_name_model:
        mock_qs = MagicMock()
        mock_qs.filter.return_value.exclude.return_value = []
        mock_name_model.objects = mock_qs

        with patch("core.management.commands.index_names_to_qdrant.NameVectorIndexRef") as mock_ref:
            mock_ref.objects.filter.return_value.values_list.return_value = []
            mock_ref.objects.filter.return_value.delete.return_value = (0, {})

            call_command("index_names_to_qdrant")

    # Verify create_collection was called
    mock_client.create_collection.assert_called_once()

    # Extract the vectors_config argument
    call_kwargs = mock_client.create_collection.call_args[1]
    assert call_kwargs["collection_name"] == COLLECTION_NAME

    vectors_config = call_kwargs["vectors_config"]

    # Verify all three named vectors use size=1024
    assert "semantic" in vectors_config
    assert vectors_config["semantic"].size == 1024

    assert "phonetic_style" in vectors_config
    assert vectors_config["phonetic_style"].size == 1024

    assert "cross_cultural" in vectors_config
    assert vectors_config["cross_cultural"].size == 1024


@override_settings(QDRANT_COLLECTION="custom_names_v2")
@patch("core.management.commands.index_names_to_qdrant.get_qdrant_client")
def test_collection_creation_uses_configured_collection_name(mock_get_client):
    """The command should index into settings.QDRANT_COLLECTION, not a hardcoded name."""
    from django.core.management import call_command

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_collections_response = MagicMock()
    mock_collections_response.collections = []
    mock_client.get_collections.return_value = mock_collections_response

    with patch("core.management.commands.index_names_to_qdrant.Name") as mock_name_model:
        mock_qs = MagicMock()
        mock_qs.filter.return_value.exclude.return_value = []
        mock_name_model.objects = mock_qs

        with patch("core.management.commands.index_names_to_qdrant.NameVectorIndexRef") as mock_ref:
            mock_ref.objects.filter.return_value.values_list.return_value = []
            call_command("index_names_to_qdrant")

    assert mock_client.create_collection.call_args.kwargs["collection_name"] == "custom_names_v2"


@patch("core.management.commands.index_names_to_qdrant.get_qdrant_client")
def test_existing_collection_with_wrong_dimensions_is_recreated(mock_get_client, db):
    """
    When the collection exists with wrong dimensions (e.g. 1536), the command
    must delete it and recreate with 1024-dimension vectors.

    Validates: Requirements 2.3
    """
    from django.core.management import call_command

    # Set up mock client
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    # Mock get_collections to return a collection with the expected name
    mock_collection_desc = MagicMock()
    mock_collection_desc.name = COLLECTION_NAME
    mock_collections_response = MagicMock()
    mock_collections_response.collections = [mock_collection_desc]
    mock_client.get_collections.return_value = mock_collections_response

    # Mock get_collection to return collection info with WRONG dimensions (1536)
    mock_collection_info = MagicMock()
    mock_semantic_config = MagicMock()
    mock_semantic_config.size = 1536  # Wrong dimension

    # Simulate dict-like vectors config with .get() method
    mock_vectors_config = MagicMock()
    mock_vectors_config.get.return_value = mock_semantic_config
    mock_collection_info.config.params.vectors = mock_vectors_config

    mock_client.get_collection.return_value = mock_collection_info

    # Mock Name.objects to return empty queryset (no names to index)
    with patch("core.management.commands.index_names_to_qdrant.Name") as mock_name_model:
        mock_qs = MagicMock()
        mock_qs.filter.return_value.exclude.return_value = []
        mock_name_model.objects = mock_qs

        with patch("core.management.commands.index_names_to_qdrant.NameVectorIndexRef") as mock_ref:
            mock_ref.objects.filter.return_value.values_list.return_value = []
            mock_ref.objects.filter.return_value.delete.return_value = (0, {})

            call_command("index_names_to_qdrant")

    # Verify the old collection was deleted
    mock_client.delete_collection.assert_called_once_with(collection_name=COLLECTION_NAME)
    mock_ref.objects.filter.return_value.delete.assert_called()

    # Verify a new collection was created with correct dimensions
    mock_client.create_collection.assert_called_once()
    call_kwargs = mock_client.create_collection.call_args[1]
    vectors_config = call_kwargs["vectors_config"]

    assert vectors_config["semantic"].size == 1024
    assert vectors_config["phonetic_style"].size == 1024
    assert vectors_config["cross_cultural"].size == 1024


@patch("core.management.commands.index_names_to_qdrant.generate_embeddings_batch")
def test_index_batch_replaces_stale_refs_and_points(mock_generate_embeddings, db):
    """Re-indexing should replace stale local refs and delete their old Qdrant points."""
    name = Name.objects.create(
        canonical_name="Ada",
        display_name="Ada",
        gender_usage=["girl"],
        origin_backgrounds=["German"],
        languages=["de"],
        scripts=["Latin"],
        variants=[],
        length_category="short",
        age_style_category="classic",
        historical_significance_score=0.7,
        semantic_summary="Classic name.",
        active=True,
    )
    old_point_id = uuid.uuid4()
    NameVectorIndexRef.objects.create(
        name=name,
        qdrant_collection=COLLECTION_NAME,
        qdrant_point_id=old_point_id,
        embedding_version="v1",
        indexed_at=timezone.now(),
    )

    mock_generate_embeddings.return_value = [[0.0] * VECTOR_DIM]
    mock_client = MagicMock()

    command = Command()
    command.collection_name = COLLECTION_NAME
    command._index_batch(mock_client, [name])

    mock_client.delete.assert_called_once()
    assert mock_client.delete.call_args.kwargs["points_selector"].points == [str(old_point_id)]

    ref = NameVectorIndexRef.objects.get(name=name)
    assert ref.embedding_version == EMBEDDING_VERSION
    assert ref.qdrant_collection == COLLECTION_NAME
