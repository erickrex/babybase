"""Unit tests for core.services.qdrant_client singleton behavior."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


class TestGetQdrantClientSingleton:
    """Tests for get_qdrant_client() singleton pattern."""

    @override_settings(
        QDRANT_URL="http://localhost:6333",
        QDRANT_API_KEY="test-key",
        QDRANT_TIMEOUT_SECONDS=42,
    )
    @patch("core.services.qdrant_client.QdrantClient")
    def test_returns_same_instance_on_repeated_calls(self, mock_qdrant_class):
        """get_qdrant_client() should return the same instance on repeated calls."""
        import core.services.qdrant_client as module

        # Reset the module-level singleton
        module._client = None

        first = module.get_qdrant_client()
        second = module.get_qdrant_client()

        assert first is second
        # QdrantClient constructor should only be called once
        mock_qdrant_class.assert_called_once_with(
            url="http://localhost:6333",
            api_key="test-key",
            timeout=42,
        )

        # Cleanup
        module._client = None

    @override_settings(QDRANT_URL="", QDRANT_API_KEY="")
    def test_raises_improperly_configured_when_url_missing(self):
        """get_qdrant_client() should raise ImproperlyConfigured when QDRANT_URL is empty."""
        import core.services.qdrant_client as module

        # Reset the module-level singleton
        module._client = None

        with pytest.raises(ImproperlyConfigured, match="QDRANT_URL must be set in Django settings."):
            module.get_qdrant_client()

        # Cleanup
        module._client = None

    @patch("core.services.qdrant_client.QdrantClient")
    def test_raises_improperly_configured_when_url_not_in_settings(self, mock_qdrant_class):
        """get_qdrant_client() should raise ImproperlyConfigured when QDRANT_URL attr is missing."""
        import core.services.qdrant_client as module

        # Reset the module-level singleton
        module._client = None

        with override_settings():
            from django.conf import settings

            # Remove QDRANT_URL from settings entirely
            if hasattr(settings, "QDRANT_URL"):
                delattr(settings, "QDRANT_URL")

            with pytest.raises(ImproperlyConfigured, match="QDRANT_URL must be set in Django settings."):
                module.get_qdrant_client()

        # Cleanup
        module._client = None


class TestSearchNames:
    """Tests for Qdrant search request construction."""

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    def test_exclude_ids_are_sent_to_qdrant_filter(self, mock_get_client):
        """Excluded point IDs should be pushed into Qdrant instead of only post-filtered."""
        from core.services.qdrant_client import search_names

        mock_client = mock_get_client.return_value
        mock_response = mock_client.query_points.return_value
        mock_response.points = []

        search_names(
            embedding=[0.0] * 1024,
            filters={"active": True},
            limit=10,
            exclude_ids=["point-a", "point-b"],
        )

        query_filter = mock_client.query_points.call_args.kwargs["query_filter"]
        assert query_filter.must_not is not None
        assert query_filter.must_not[0].has_id == ["point-a", "point-b"]

    @patch("core.services.qdrant_client.get_qdrant_client")
    def test_rejects_wrong_dimension_query_embedding(self, mock_get_client):
        """Search should fail before Qdrant when a stale non-Titan vector is used."""
        from core.services.qdrant_client import search_names

        with pytest.raises(ValueError, match="Qdrant query embedding must be 1024 dimensions"):
            search_names(embedding=[0.0] * 1536)

        mock_get_client.assert_not_called()

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    def test_uses_query_points_not_legacy_search(self, mock_get_client):
        """
        Regression: qdrant-client 1.17 removed the legacy client.search() method.
        search_names() must use the new query_points() API with the named vector
        passed via 'using=' rather than wrapping the embedding in NamedVector.
        """
        from core.services.qdrant_client import search_names

        mock_client = mock_get_client.return_value
        mock_client.query_points.return_value.points = []

        search_names(
            embedding=[0.0] * 1024,
            filters={"active": True, "gender_usage": "boy"},
            limit=5,
            vector_name="semantic",
        )

        # The new API must have been called
        mock_client.query_points.assert_called_once()
        call_kwargs = mock_client.query_points.call_args.kwargs

        # Embedding is passed as `query`, not `query_vector`
        assert call_kwargs["query"] == [0.0] * 1024
        # Named vector is selected via `using`, not wrapped in NamedVector
        assert call_kwargs["using"] == "semantic"
        assert call_kwargs["collection_name"] == "test_names"
        assert call_kwargs["limit"] == 5

        # The legacy method must NOT have been called
        mock_client.search.assert_not_called()


class TestGetNamesByFilter:
    """Tests for filter-only retrieval (degraded fallback when no embedding)."""

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    def test_uses_scroll_with_gender_filter_no_vector(self, mock_get_client):
        """Filter-only retrieval uses scroll(), pushes gender, and requests no vectors."""
        from core.services.qdrant_client import get_names_by_filter

        mock_client = mock_get_client.return_value
        mock_client.scroll.return_value = ([], None)

        get_names_by_filter(filters={"active": True, "gender_usage": "boy"}, limit=25)

        mock_client.scroll.assert_called_once()
        kwargs = mock_client.scroll.call_args.kwargs
        assert kwargs["collection_name"] == "test_names"
        assert kwargs["limit"] == 25
        assert kwargs["with_vectors"] is False
        gender_conditions = [c for c in kwargs["scroll_filter"].must if getattr(c, "key", None) == "gender_usage"]
        assert len(gender_conditions) == 1
        assert gender_conditions[0].match.value == "boy"

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    def test_excludes_ids_and_returns_zero_scores(self, mock_get_client):
        """Excluded IDs are filtered out and every returned candidate has score 0.0."""
        from core.services.qdrant_client import get_names_by_filter

        kept = SimpleNamespace(id="keep-1", payload={"name_id": "n1", "canonical_name": "Ivan", "active": True})
        mock_client = mock_get_client.return_value
        mock_client.scroll.return_value = ([kept], None)

        results = get_names_by_filter(filters={"active": True}, limit=10, exclude_ids=["drop-1"])

        kwargs = mock_client.scroll.call_args.kwargs
        assert kwargs["scroll_filter"].must_not[0].has_id == ["drop-1"]
        assert len(results) == 1
        assert results[0]["point_id"] == "keep-1"
        assert results[0]["score"] == 0.0
        assert results[0]["canonical_name"] == "Ivan"
