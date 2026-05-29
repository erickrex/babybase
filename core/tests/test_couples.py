"""Unit tests for couple management service."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.models import Couple, CoupleStatus, OnboardingResponse
from core.services.couples import (
    CoupleExistsError,
    connect_pending_invite,
    create_couple,
    get_active_couple,
    get_couple_for_user,
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


class TestSoloCoupleInvite:
    """Tests for inviting a partner from an existing solo active couple."""

    def _make_solo_couple(self, user):
        """Create an active couple with no partner (solo swiping user)."""
        return Couple.objects.create(
            user_a=user,
            user_b=None,
            status=CoupleStatus.ACTIVE,
        )

    def test_solo_user_invites_existing_partner_attaches_to_same_couple(self, user_a, user_b):
        """Inviting an existing user attaches them to the solo couple, preserving it."""
        solo = self._make_solo_couple(user_a)

        result = create_couple(user_a, user_b.email)

        assert result.id == solo.id  # same couple, swipe history preserved
        assert result.user_b == user_b
        assert result.status == CoupleStatus.ACTIVE
        assert result.invite_email == user_b.email

    def test_solo_user_invites_existing_partner_associates_partner_onboarding(self, user_a, user_b):
        """Partner's solo onboarding responses get linked to the couple."""
        solo = self._make_solo_couple(user_a)
        partner_response = OnboardingResponse.objects.create(
            user=user_b,
            couple=None,
            preferred_name_backgrounds=["Spanish"],
            preferred_name_age="balanced",
            baby_gender_preference="girl",
            preferred_name_length="any",
            historical_importance="medium",
        )

        create_couple(user_a, user_b.email)
        partner_response.refresh_from_db()

        assert partner_response.couple_id == solo.id

    def test_solo_user_invites_nonexistent_partner_stays_active_with_invite(self, user_a):
        """Inviting a not-yet-registered partner keeps the couple active and records the email."""
        solo = self._make_solo_couple(user_a)

        result = create_couple(user_a, "future-partner@example.com")

        assert result.id == solo.id
        assert result.status == CoupleStatus.ACTIVE  # solo user keeps swiping
        assert result.user_b is None
        assert result.invite_email == "future-partner@example.com"

    def test_pending_invite_connects_to_active_solo_couple_on_registration(self, user_a):
        """When the invited partner registers, they connect to the active solo couple."""
        solo = self._make_solo_couple(user_a)
        create_couple(user_a, "late@example.com")

        new_user = User.objects.create_user(email="late@example.com", password="testpass123")
        connected = connect_pending_invite(new_user)

        assert connected is not None
        assert connected.id == solo.id
        assert connected.user_b == new_user
        assert connected.status == CoupleStatus.ACTIVE

    def test_solo_user_cannot_invite_self(self, user_a):
        """Inviting your own email is rejected."""
        self._make_solo_couple(user_a)

        with pytest.raises(CoupleExistsError, match="cannot invite yourself"):
            create_couple(user_a, user_a.email)

    def test_real_two_person_couple_still_rejects_new_invite(self, user_a, user_b, user_c):
        """A user already paired with a partner cannot invite a third person."""
        create_couple(user_a, user_b.email)  # real active couple

        with pytest.raises(CoupleExistsError, match="already in an active couple"):
            create_couple(user_a, user_c.email)

    def test_two_solo_swipers_merge_when_one_invites_the_other(self, user_a, user_b):
        """Both partners swiped solo first; inviting merges them into one couple."""
        from core.models import Name, Swipe

        solo_a = self._make_solo_couple(user_a)
        solo_b = self._make_solo_couple(user_b)

        name = Name.objects.create(
            canonical_name="MergeName",
            display_name="Merge Name",
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="A test name.",
            active=True,
        )
        # Each partner liked the same name in their own solo couple
        Swipe.objects.create(couple=solo_a, user=user_a, name=name, action="like")
        Swipe.objects.create(couple=solo_b, user=user_b, name=name, action="like")

        result = create_couple(user_a, user_b.email)

        # They end up in user_a's couple, partner attached
        assert result.id == solo_a.id
        assert result.user_b == user_b
        assert result.status == CoupleStatus.ACTIVE

        # Partner's solo couple is archived
        solo_b.refresh_from_db()
        assert solo_b.status == CoupleStatus.ARCHIVED

        # Partner's swipe moved into the merged couple
        assert Swipe.objects.filter(couple=result, user=user_b, name=name).exists()
        assert not Swipe.objects.filter(couple=solo_b, user=user_b).exists()

    def test_merge_preserves_both_partners_swipes_for_mutual_match(self, user_a, user_b):
        """After merge, both partners' likes on the same name live in one couple."""
        from core.models import Name, Swipe
        from core.services.swipes import check_mutual_match

        solo_a = self._make_solo_couple(user_a)
        solo_b = self._make_solo_couple(user_b)

        name = Name.objects.create(
            canonical_name="MatchName",
            display_name="Match Name",
            gender_usage=["girl"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="A test name.",
            active=True,
        )
        Swipe.objects.create(couple=solo_a, user=user_a, name=name, action="like")
        Swipe.objects.create(couple=solo_b, user=user_b, name=name, action="like")

        merged = create_couple(user_a, user_b.email)

        # Both likes now in the same couple → mutual match detectable
        assert check_mutual_match(merged, str(name.id)) is True

    def test_invitee_with_solo_couple_when_inviter_has_none(self, user_a, user_b):
        """Inviter never swiped (no solo couple) but invitee did; still merges cleanly."""
        from core.models import Name, Swipe

        solo_b = self._make_solo_couple(user_b)
        name = Name.objects.create(
            canonical_name="OneSideName",
            display_name="One Side Name",
            gender_usage=["boy"],
            origin_backgrounds=["English"],
            languages=["en"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="A test name.",
            active=True,
        )
        Swipe.objects.create(couple=solo_b, user=user_b, name=name, action="like")

        result = create_couple(user_a, user_b.email)

        assert result.user_a == user_a
        assert result.user_b == user_b
        assert result.status == CoupleStatus.ACTIVE
        solo_b.refresh_from_db()
        assert solo_b.status == CoupleStatus.ARCHIVED
        assert Swipe.objects.filter(couple=result, user=user_b, name=name).exists()


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


class TestGetCoupleForUser:
    """Tests for get_couple_for_user ordering."""

    def test_prefers_active_couple_over_pending(self, user_a, user_b):
        """Active couples are preferred over pending records for the same user."""
        pending = Couple.objects.create(
            user_a=user_a,
            status=CoupleStatus.PENDING,
            invite_email="pending@example.com",
        )
        active = Couple.objects.create(
            user_a=user_b,
            user_b=user_a,
            status=CoupleStatus.ACTIVE,
            invite_email=user_a.email,
        )

        result = get_couple_for_user(user_a)

        assert result is not None
        assert result.id == active.id
        assert result.id != pending.id


class TestModelConstraints:
    """Database constraint tests for couples and onboarding responses."""

    def test_couple_users_must_differ(self, user_a):
        """A couple cannot reference the same user twice."""
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Couple.objects.create(
                    user_a=user_a,
                    user_b=user_a,
                    status=CoupleStatus.ACTIVE,
                    invite_email=user_a.email,
                )

    def test_single_solo_onboarding_response_per_user(self, user_a):
        """Only one solo onboarding response can exist per user."""
        OnboardingResponse.objects.create(
            user=user_a,
            couple=None,
            preferred_name_backgrounds=["German"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OnboardingResponse.objects.create(
                    user=user_a,
                    couple=None,
                    preferred_name_backgrounds=["Spanish"],
                    preferred_name_age="balanced",
                    baby_gender_preference="boy",
                    preferred_name_length="any",
                    historical_importance="medium",
                )

    def test_single_onboarding_response_per_user_and_couple(self, user_a, user_b):
        """Only one onboarding response can exist for a user within a couple."""
        couple = create_couple(user_a, user_b.email)
        OnboardingResponse.objects.create(
            user=user_a,
            couple=couple,
            preferred_name_backgrounds=["German"],
            preferred_name_age="balanced",
            baby_gender_preference="boy",
            preferred_name_length="any",
            historical_importance="medium",
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OnboardingResponse.objects.create(
                    user=user_a,
                    couple=couple,
                    preferred_name_backgrounds=["Spanish"],
                    preferred_name_age="balanced",
                    baby_gender_preference="boy",
                    preferred_name_length="any",
                    historical_importance="medium",
                )
