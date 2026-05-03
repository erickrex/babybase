"""Couple management service for BabyBase."""

import logging

from django.contrib.auth import get_user_model
from django.db.models import Q

from core.models import Couple, CoupleStatus

User = get_user_model()
logger = logging.getLogger(__name__)


class CoupleExistsError(Exception):
    """Raised when a user already has an active couple."""

    pass


def create_couple(user: "User", partner_email: str) -> Couple:
    """
    Create a couple for the given user with the specified partner.

    If the partner already exists in the system, connect immediately (status=active).
    If the partner doesn't exist, create a pending invite record.

    Raises CoupleExistsError if the user is already in an active couple or
    already has a pending invite to a different email.
    Returns the existing pending couple if the same partner email is provided.
    """
    # Enforce couple singleton: user can only be in one active couple
    if has_active_couple(user):
        raise CoupleExistsError("User is already in an active couple.")

    # Check for existing pending couple
    existing_pending = Couple.objects.filter(
        user_a=user, status=CoupleStatus.PENDING
    ).first()

    if existing_pending:
        if existing_pending.invite_email == partner_email.lower():
            return existing_pending  # Return existing, don't duplicate
        raise CoupleExistsError("User already has a pending invite.")

    # Check if partner exists in the system
    partner = User.objects.filter(email=partner_email.lower()).first()

    if partner:
        # Partner exists — check they're not already in an active couple
        if has_active_couple(partner):
            raise CoupleExistsError("Partner is already in an active couple.")

        # Connect immediately
        couple = Couple.objects.create(
            user_a=user,
            user_b=partner,
            status=CoupleStatus.ACTIVE,
            invite_email=partner_email.lower(),
        )
        logger.info("Couple connected immediately: id=%s user_a=%s user_b=%s", couple.id, user.email, partner.email)
    else:
        # Partner doesn't exist — create pending invite
        couple = Couple.objects.create(
            user_a=user,
            user_b=None,
            status=CoupleStatus.PENDING,
            invite_email=partner_email.lower(),
        )
        logger.info("Couple invite created (pending): id=%s user_a=%s invite=%s", couple.id, user.email, partner_email)

    return couple


def has_active_couple(user: "User") -> bool:
    """Check if a user is already in an active couple."""
    return Couple.objects.filter(
        Q(user_a=user, status=CoupleStatus.ACTIVE)
        | Q(user_b=user, status=CoupleStatus.ACTIVE)
    ).exists()


def get_active_couple(user: "User") -> Couple | None:
    """Get the user's active couple, or None."""
    return (
        Couple.objects.filter(
            Q(user_a=user, status=CoupleStatus.ACTIVE)
            | Q(user_b=user, status=CoupleStatus.ACTIVE)
        )
        .select_related("user_a", "user_b")
        .first()
    )


def get_couple_for_user(user: "User") -> Couple | None:
    """Get any couple (active or pending) for the user."""
    return (
        Couple.objects.filter(
            Q(user_a=user) | Q(user_b=user)
        )
        .exclude(status=CoupleStatus.ARCHIVED)
        .select_related("user_a", "user_b")
        .first()
    )


def connect_pending_invite(new_user: "User") -> Couple | None:
    """
    Check for pending invites matching the new user's email.
    If found, connect user_b and set status='active'.

    Called during registration flow.
    """
    pending_couple = Couple.objects.filter(
        invite_email=new_user.email.lower(),
        status=CoupleStatus.PENDING,
        user_b__isnull=True,
    ).first()

    if pending_couple:
        pending_couple.user_b = new_user
        pending_couple.status = CoupleStatus.ACTIVE
        pending_couple.save(update_fields=["user_b", "status", "updated_at"])
        logger.info("Pending invite connected: couple=%s new_user=%s", pending_couple.id, new_user.email)
        return pending_couple

    return None


def get_couple_status(user: "User") -> dict:
    """Return couple info, partner status, and onboarding completeness."""
    couple = get_couple_for_user(user)

    if not couple:
        return {
            "has_couple": False,
            "couple": None,
            "partner": None,
            "onboarding_complete": {"user": False, "partner": False},
        }

    # Determine partner
    if couple.user_a == user:
        partner = couple.user_b
    else:
        partner = couple.user_a

    # Check onboarding completeness
    user_onboarded = couple.onboarding_responses.filter(user=user).exists()
    partner_onboarded = (
        couple.onboarding_responses.filter(user=partner).exists() if partner else False
    )

    partner_info = None
    if partner:
        partner_info = {
            "id": str(partner.id),
            "email": partner.email,
            "first_name": partner.first_name,
            "role_in_pregnancy": partner.role_in_pregnancy,
        }

    return {
        "has_couple": True,
        "couple": {
            "id": str(couple.id),
            "status": couple.status,
            "residence_country": couple.residence_country,
            "created_at": couple.created_at.isoformat(),
        },
        "partner": partner_info,
        "onboarding_complete": {
            "user": user_onboarded,
            "partner": partner_onboarded,
        },
    }
