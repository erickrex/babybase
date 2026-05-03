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
