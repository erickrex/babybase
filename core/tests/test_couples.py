"""Unit tests for couple management service."""

import pytest
from django.contrib.auth import get_user_model

from core.models import CoupleStatus
from core.services.couples import (
    CoupleExistsError,
    connect_pending_invite,
    create_couple,
    get_active_couple,
    has_active_couple,
)

User = get_user_model()


@pytest.fixture
def user_a(db):
    return User.objects.create_user(email="alice@example.com", password="testpass123")


@pytest.fixture
def user_b(db):
    return User.objects.create_user(email="bob@example.com", password="testpass123")


@pytest.fixture
def user_c(db):
    return User.objects.create_user(email="charlie@example.com", password="testpass123")


class TestCreateCouple:
    """Tests for create_couple service function."""

    def test_invite_existing_partner_connects_immediately(self, user_a, user_b):
        """When partner exists in system, couple is created with status=active."""
        couple = create_couple(user_a, user_b.email)

        assert couple.user_a == user_a
        assert couple.user_b == user_b
        assert couple.status == CoupleStatus.ACTIVE
        assert couple.invite_email == user_b.email

    def test_invite_nonexistent_partner_creates_pending(self, user_a):
        """When partner doesn't exist, couple is pending with invite_email set."""
        couple = create_couple(user_a, "unknown@example.com")

        assert couple.user_a == user_a
        assert couple.user_b is None
        assert couple.status == CoupleStatus.PENDING
        assert couple.invite_email == "unknown@example.com"

    def test_singleton_enforcement_rejects_second_couple(self, user_a, user_b, user_c):
        """User already in active couple cannot create another."""
        create_couple(user_a, user_b.email)

        with pytest.raises(CoupleExistsError):
            create_couple(user_a, user_c.email)

    def test_singleton_enforcement_for_partner(self, user_a, user_b, user_c):
        """Partner already in active couple cannot be connected to another."""
        create_couple(user_b, user_c.email)

        with pytest.raises(CoupleExistsError):
            create_couple(user_a, user_b.email)

    def test_email_normalized_to_lowercase(self, user_a, user_b):
        """Partner email is normalized to lowercase."""
        couple = create_couple(user_a, "BOB@EXAMPLE.COM")

        assert couple.invite_email == "bob@example.com"
        assert couple.user_b == user_b
        assert couple.status == CoupleStatus.ACTIVE


class TestDuplicatePendingPrevention:
    """Tests for preventing duplicate pending couple invites.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    def test_same_email_returns_existing_pending(self, user_a):
        """When user has pending invite to same email, return existing couple."""
        couple = create_couple(user_a, "partner@example.com")
        assert couple.status == CoupleStatus.PENDING

        # Same email should return the existing pending couple
        result = create_couple(user_a, "partner@example.com")
        assert result.id == couple.id
        assert result.status == CoupleStatus.PENDING

    def test_same_email_case_insensitive_returns_existing(self, user_a):
        """Same email with different casing returns existing pending couple."""
        couple = create_couple(user_a, "partner@example.com")

        result = create_couple(user_a, "PARTNER@EXAMPLE.COM")
        assert result.id == couple.id

    def test_different_email_raises_error(self, user_a):
        """When user has pending invite, different email raises CoupleExistsError."""
        create_couple(user_a, "first@example.com")

        with pytest.raises(CoupleExistsError, match="User already has a pending invite"):
            create_couple(user_a, "second@example.com")

    def test_no_second_pending_record_created(self, user_a):
        """Calling create_couple with same email does not create a second record."""
        from core.models import Couple

        create_couple(user_a, "partner@example.com")
        create_couple(user_a, "partner@example.com")

        count = Couple.objects.filter(user_a=user_a, status=CoupleStatus.PENDING).count()
        assert count == 1


class TestConnectPendingInvite:
    """Tests for auto-connect on registration."""

    def test_auto_connect_on_registration(self, user_a):
        """New user with pending invite gets auto-connected."""
        # Create pending invite
        couple = create_couple(user_a, "newuser@example.com")
        assert couple.status == CoupleStatus.PENDING
        assert couple.user_b is None

        # New user registers with matching email
        new_user = User.objects.create_user(
            email="newuser@example.com", password="testpass123"
        )
        connected_couple = connect_pending_invite(new_user)

        assert connected_couple is not None
        assert connected_couple.id == couple.id
        assert connected_couple.user_b == new_user
        assert connected_couple.status == CoupleStatus.ACTIVE

    def test_no_pending_invite_returns_none(self, db):
        """User with no pending invite gets None."""
        user = User.objects.create_user(email="nobody@example.com", password="testpass123")
        result = connect_pending_invite(user)
        assert result is None

    def test_already_connected_invite_not_matched(self, user_a, user_b):
        """Already-connected couple is not matched again."""
        create_couple(user_a, user_b.email)

        # Try to connect again with same email
        another_user = User.objects.create_user(
            email="another@example.com", password="testpass123"
        )
        result = connect_pending_invite(another_user)
        assert result is None


class TestHasActiveCouple:
    """Tests for has_active_couple helper."""

    def test_user_with_active_couple(self, user_a, user_b):
        """Returns True when user is in an active couple."""
        create_couple(user_a, user_b.email)
        assert has_active_couple(user_a) is True
        assert has_active_couple(user_b) is True

    def test_user_without_couple(self, user_a):
        """Returns False when user has no couple."""
        assert has_active_couple(user_a) is False

    def test_user_with_pending_couple(self, user_a):
        """Returns False when user only has a pending couple."""
        create_couple(user_a, "pending@example.com")
        assert has_active_couple(user_a) is False


class TestGetActiveCouple:
    """Tests for get_active_couple helper."""

    def test_returns_active_couple(self, user_a, user_b):
        """Returns the active couple for a user."""
        couple = create_couple(user_a, user_b.email)
        result = get_active_couple(user_a)
        assert result is not None
        assert result.id == couple.id

    def test_returns_none_when_no_active(self, user_a):
        """Returns None when user has no active couple."""
        result = get_active_couple(user_a)
        assert result is None
