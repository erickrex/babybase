"""Unit tests for core.services.qdrant_client singleton behavior."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


class TestGetQdrantClientSingleton:
    """Tests for get_qdrant_client() singleton pattern."""

    @override_settings(QDRANT_URL="http://localhost:6333", QDRANT_API_KEY="test-key")
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
        mock_qdrant_class.assert_called_once_with(url="http://localhost:6333", api_key="test-key")

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
        mock_client.search.return_value = []

        search_names(
            embedding=[0.0] * 1024,
            filters={"active": True},
            limit=10,
            exclude_ids=["point-a", "point-b"],
        )

        query_filter = mock_client.search.call_args.kwargs["query_filter"]
        assert query_filter.must_not is not None
        assert query_filter.must_not[0].has_id == ["point-a", "point-b"]

    @patch("core.services.qdrant_client.get_qdrant_client")
    def test_rejects_wrong_dimension_query_embedding(self, mock_get_client):
        """Search should fail before Qdrant when a stale non-Titan vector is used."""
        from core.services.qdrant_client import search_names

        with pytest.raises(ValueError, match="Qdrant query embedding must be 1024 dimensions"):
            search_names(embedding=[0.0] * 1536)

        mock_get_client.assert_not_called()
