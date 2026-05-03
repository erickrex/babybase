"""Unit tests for structured error logging in vector helpers (Task 2)."""

import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from qdrant_client.http.exceptions import UnexpectedResponse


@pytest.fixture
def mock_couple():
    """Create a mock couple object with an ID."""
    couple = MagicMock()
    couple.id = uuid.uuid4()
    return couple


@pytest.fixture
def mock_user():
    """Create a mock user object with an ID."""
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


def _setup_couple_swipes_mock(mock_couple, name_ids=None):
    """Configure mock couple to return swipe data that reaches the Qdrant call."""
    if name_ids is None:
        name_ids = [uuid.uuid4()]
    mock_swipe_qs = MagicMock()
    mock_swipe_qs.filter.return_value = mock_swipe_qs
    mock_swipe_qs.values_list.return_value.distinct.return_value = name_ids
    mock_couple.swipes.filter.return_value = mock_swipe_qs


def _setup_user_swipes_mock(mock_couple, name_ids=None):
    """Configure mock couple to return user-specific swipe data."""
    if name_ids is None:
        name_ids = [uuid.uuid4()]
    mock_swipe_qs = MagicMock()
    mock_swipe_qs.filter.return_value.values_list.return_value = name_ids
    mock_couple.swipes = mock_swipe_qs


class TestGetLikedVectorsForCoupleLogging:
    """Tests for error logging in _get_liked_vectors_for_couple."""

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_logs_error_with_couple_id_on_unexpected_response(
        self, mock_nvir_objects, mock_get_client, mock_couple, caplog
    ):
        """Logger.error should include couple ID when UnexpectedResponse occurs."""
        _setup_couple_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = UnexpectedResponse(
            status_code=500, reason_phrase="Internal Server Error", content=b"error",
            headers=MagicMock(),
        )
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_couple

        with caplog.at_level(logging.ERROR, logger="core.services.onboarding"):
            result = _get_liked_vectors_for_couple(mock_couple)

        assert result == []
        assert str(mock_couple.id) in caplog.text
        assert "Failed to fetch liked vectors for couple" in caplog.text

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_logs_error_with_couple_id_on_connection_error(
        self, mock_nvir_objects, mock_get_client, mock_couple, caplog
    ):
        """Logger.error should include couple ID when ConnectionError occurs."""
        _setup_couple_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = ConnectionError("Connection refused")
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_couple

        with caplog.at_level(logging.ERROR, logger="core.services.onboarding"):
            result = _get_liked_vectors_for_couple(mock_couple)

        assert result == []
        assert str(mock_couple.id) in caplog.text
        assert "Connection refused" in caplog.text

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_logs_error_with_couple_id_on_timeout(
        self, mock_nvir_objects, mock_get_client, mock_couple, caplog
    ):
        """Logger.error should include couple ID when TimeoutError occurs."""
        _setup_couple_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = TimeoutError("Request timed out")
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_couple

        with caplog.at_level(logging.ERROR, logger="core.services.onboarding"):
            result = _get_liked_vectors_for_couple(mock_couple)

        assert result == []
        assert str(mock_couple.id) in caplog.text
        assert "Request timed out" in caplog.text

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_logs_mutual_only_flag(
        self, mock_nvir_objects, mock_get_client, mock_couple, caplog
    ):
        """Logger.error should include mutual_only flag value."""
        _setup_couple_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = ConnectionError("fail")
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_couple

        with caplog.at_level(logging.ERROR, logger="core.services.onboarding"):
            result = _get_liked_vectors_for_couple(mock_couple, mutual_only=False)

        assert result == []
        assert "mutual_only=False" in caplog.text


class TestGetLikedVectorsForUserLogging:
    """Tests for error logging in _get_liked_vectors_for_user."""

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_logs_error_with_user_and_couple_id_on_unexpected_response(
        self, mock_nvir_objects, mock_get_client, mock_couple, mock_user, caplog
    ):
        """Logger.error should include user ID and couple ID when UnexpectedResponse occurs."""
        _setup_user_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = UnexpectedResponse(
            status_code=500, reason_phrase="Internal Server Error", content=b"error",
            headers=MagicMock(),
        )
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_user

        with caplog.at_level(logging.ERROR, logger="core.services.onboarding"):
            result = _get_liked_vectors_for_user(mock_couple, mock_user)

        assert result == []
        assert str(mock_user.id) in caplog.text
        assert str(mock_couple.id) in caplog.text
        assert "Failed to fetch liked vectors for user" in caplog.text

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_logs_error_with_user_and_couple_id_on_connection_error(
        self, mock_nvir_objects, mock_get_client, mock_couple, mock_user, caplog
    ):
        """Logger.error should include user ID and couple ID when ConnectionError occurs."""
        _setup_user_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = ConnectionError("Connection refused")
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_user

        with caplog.at_level(logging.ERROR, logger="core.services.onboarding"):
            result = _get_liked_vectors_for_user(mock_couple, mock_user)

        assert result == []
        assert str(mock_user.id) in caplog.text
        assert str(mock_couple.id) in caplog.text
        assert "Connection refused" in caplog.text


class TestUnexpectedExceptionsPropagateUncaught:
    """Tests verifying unexpected exception types propagate uncaught (Task 2.4)."""

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_couple_function_propagates_value_error(
        self, mock_nvir_objects, mock_get_client, mock_couple
    ):
        """ValueError should propagate uncaught from _get_liked_vectors_for_couple."""
        _setup_couple_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = ValueError("unexpected error")
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_couple

        with pytest.raises(ValueError, match="unexpected error"):
            _get_liked_vectors_for_couple(mock_couple)

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_user_function_propagates_runtime_error(
        self, mock_nvir_objects, mock_get_client, mock_couple, mock_user
    ):
        """RuntimeError should propagate uncaught from _get_liked_vectors_for_user."""
        _setup_user_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = RuntimeError("unexpected error")
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_user

        with pytest.raises(RuntimeError, match="unexpected error"):
            _get_liked_vectors_for_user(mock_couple, mock_user)

    @override_settings(QDRANT_COLLECTION="test_names")
    @patch("core.services.qdrant_client.get_qdrant_client")
    @patch("core.models.NameVectorIndexRef.objects")
    def test_couple_function_propagates_keyboard_interrupt(
        self, mock_nvir_objects, mock_get_client, mock_couple
    ):
        """KeyboardInterrupt should propagate uncaught from _get_liked_vectors_for_couple."""
        _setup_couple_swipes_mock(mock_couple)
        mock_nvir_objects.filter.return_value.values_list.return_value = [uuid.uuid4()]

        mock_client = MagicMock()
        mock_client.retrieve.side_effect = KeyboardInterrupt()
        mock_get_client.return_value = mock_client

        from core.services.onboarding import _get_liked_vectors_for_couple

        with pytest.raises(KeyboardInterrupt):
            _get_liked_vectors_for_couple(mock_couple)
