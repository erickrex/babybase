"""Couple management service for BabyBase."""

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When

from core.models import Couple, CoupleStatus, OnboardingResponse

User = get_user_model()
logger = logging.getLogger(__name__)


class CoupleExistsError(Exception):
    """Raised when a user already has an active couple."""

    pass


def _lock_users(*user_ids) -> dict:
    """Lock user rows involved in couple creation/activation."""
    ids = sorted({user_id for user_id in user_ids if user_id is not None}, key=str)
    locked_users = User.objects.select_for_update().filter(id__in=ids)
    return {locked_user.id: locked_user for locked_user in locked_users}


def create_couple(user: "User", partner_email: str) -> Couple:
    """
    Create a couple for the given user with the specified partner.

    If the partner already exists in the system, connect immediately (status=active).
    If the partner doesn't exist, create a pending invite record.

    Raises CoupleExistsError if the user is already in an active couple or
    already has a pending invite to a different email.
    Returns the existing pending couple if the same partner email is provided.
    """
    normalized_email = partner_email.lower()

    with transaction.atomic():
        partner = User.objects.filter(email=normalized_email).first()
        locked_users = _lock_users(user.id, partner.id if partner else None)
        user = locked_users.get(user.id, user)
        if partner is not None:
            partner = locked_users.get(partner.id, partner)

        if partner and partner.id == user.id:
            raise CoupleExistsError("You cannot invite yourself.")

        # A solo user who already started swiping has an active couple with no
        # partner yet (user_b is None). Inviting a partner should attach to that
        # existing couple so their swipe history carries over, not be rejected.
        solo_couple = (
            Couple.objects.select_for_update()
            .filter(user_a=user, status=CoupleStatus.ACTIVE, user_b__isnull=True)
            .first()
        )

        # Enforce couple singleton: reject only if the user is in a real
        # two-person active couple.
        if has_active_couple(user) and not solo_couple:
            raise CoupleExistsError("User is already in an active couple.")

        # Check for existing pending couple
        existing_pending = Couple.objects.select_for_update().filter(
            user_a=user, status=CoupleStatus.PENDING
        ).first()

        if existing_pending:
            if existing_pending.invite_email == normalized_email:
                return existing_pending  # Return existing, don't duplicate
            raise CoupleExistsError("User already has a pending invite.")

        if solo_couple:
            return _attach_partner_to_solo_couple(solo_couple, user, partner, normalized_email)

        if partner:
            # Partner exists — check whether they already swiped solo.
            partner_solo_couple = (
                Couple.objects.select_for_update()
                .filter(user_a=partner, status=CoupleStatus.ACTIVE, user_b__isnull=True)
                .first()
            )
            if has_active_couple(partner) and not partner_solo_couple:
                raise CoupleExistsError("Partner is already in an active couple.")

            # Connect immediately
            couple = Couple.objects.create(
                user_a=user,
                user_b=partner,
                status=CoupleStatus.ACTIVE,
                invite_email=normalized_email,
            )
            logger.info(
                "Couple connected immediately: id=%s user_a=%s user_b=%s",
                couple.id,
                user.email,
                partner.email,
            )

            # Associate the inviter's solo onboarding with the new couple
            updated_user_a = OnboardingResponse.objects.filter(user=user, couple=None).update(couple=couple)
            if updated_user_a:
                logger.info(
                    "Associated %s solo onboarding response(s) for user_a=%s with couple=%s",
                    updated_user_a,
                    user.email,
                    couple.id,
                )

            # Bring over the partner's solo swipes/onboarding if they swiped alone,
            # otherwise just link their solo onboarding response.
            if partner_solo_couple:
                _merge_solo_couple_into(partner_solo_couple, couple, partner)
            else:
                updated_user_b = OnboardingResponse.objects.filter(user=partner, couple=None).update(
                    couple=couple
                )
                if updated_user_b:
                    logger.info(
                        "Associated %s solo onboarding response(s) for user_b=%s with couple=%s",
                        updated_user_b,
                        partner.email,
                        couple.id,
                    )
        else:
            # Partner doesn't exist — create pending invite
            couple = Couple.objects.create(
                user_a=user,
                user_b=None,
                status=CoupleStatus.PENDING,
                invite_email=normalized_email,
            )
            logger.info(
                "Couple invite created (pending): id=%s user_a=%s invite=%s",
                couple.id,
                user.email,
                normalized_email,
            )

        return couple


def _attach_partner_to_solo_couple(
    solo_couple: Couple,
    user: "User",
    partner: "User | None",
    normalized_email: str,
) -> Couple:
    """Attach a partner to an existing solo active couple (user_b is None).

    Preserves the inviting user's existing swipe history and onboarding.
    - Partner has their own solo active couple (also swiped alone): merge the
      partner's swipes and onboarding into this couple, then archive the
      partner's solo couple.
    - Partner has an account but no couple: attach immediately as user_b.
    - Partner already in a real two-person active couple: reject.
    - Partner has no account yet: keep this couple ACTIVE and record the invite
      so they connect automatically when they register.
    """
    if partner:
        partner_solo_couple = (
            Couple.objects.select_for_update()
            .filter(user_a=partner, status=CoupleStatus.ACTIVE, user_b__isnull=True)
            .first()
        )

        if has_active_couple(partner) and not partner_solo_couple:
            raise CoupleExistsError("Partner is already in an active couple.")

        solo_couple.user_b = partner
        solo_couple.invite_email = normalized_email
        solo_couple.save(update_fields=["user_b", "invite_email", "updated_at"])
        logger.info(
            "Partner attached to solo couple: id=%s user_a=%s user_b=%s",
            solo_couple.id,
            user.email,
            partner.email,
        )

        if partner_solo_couple:
            _merge_solo_couple_into(partner_solo_couple, solo_couple, partner)
        else:
            updated_partner = OnboardingResponse.objects.filter(user=partner, couple=None).update(
                couple=solo_couple
            )
            if updated_partner:
                logger.info(
                    "Associated %s solo onboarding response(s) for partner=%s with couple=%s",
                    updated_partner,
                    partner.email,
                    solo_couple.id,
                )
    else:
        # Partner has no account yet. Keep the couple ACTIVE so the solo user
        # can keep swiping, but record invite_email so the partner is connected
        # automatically when they register.
        solo_couple.invite_email = normalized_email
        solo_couple.save(update_fields=["invite_email", "updated_at"])
        logger.info(
            "Solo couple recorded pending invite (stays active): id=%s user_a=%s invite=%s",
            solo_couple.id,
            user.email,
            normalized_email,
        )

    return solo_couple


def _merge_solo_couple_into(source_couple: Couple, target_couple: Couple, partner: "User") -> None:
    """Merge a partner's solo couple into the target couple, then archive the source.

    Moves the partner's swipes and onboarding response from their own solo
    couple into the newly formed two-person couple so their likes contribute to
    mutual-match detection. Swipes that would collide with an existing row in
    the target couple (same user+name) are dropped, since the target already
    records that preference.
    """
    existing_name_ids = set(
        target_couple.swipes.filter(user=partner).values_list("name_id", flat=True)
    )

    moved = 0
    for swipe in source_couple.swipes.filter(user=partner):
        if swipe.name_id in existing_name_ids:
            continue
        swipe.couple = target_couple
        swipe.save(update_fields=["couple", "updated_at"])
        moved += 1

    # Move the partner's solo onboarding response if the target lacks one.
    target_has_onboarding = OnboardingResponse.objects.filter(
        couple=target_couple, user=partner
    ).exists()
    if not target_has_onboarding:
        OnboardingResponse.objects.filter(couple=source_couple, user=partner).update(
            couple=target_couple
        )
        OnboardingResponse.objects.filter(user=partner, couple=None).update(couple=target_couple)

    source_couple.status = CoupleStatus.ARCHIVED
    source_couple.save(update_fields=["status", "updated_at"])
    logger.info(
        "Merged solo couple %s into %s for partner=%s (moved %s swipes, archived source)",
        source_couple.id,
        target_couple.id,
        partner.email,
        moved,
    )


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
        .order_by(
            Case(
                When(status=CoupleStatus.ACTIVE, then=Value(0)),
                When(status=CoupleStatus.PENDING, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
            "-created_at",
        )
        .select_related("user_a", "user_b")
        .first()
    )


def connect_pending_invite(new_user: "User") -> Couple | None:
    """
    Check for pending invites matching the new user's email.
    If found, connect user_b and set status='active'.

    After connecting:
    1. Find any OnboardingResponse for new_user with couple=None
    2. Associate it with the newly formed couple
    3. Find any OnboardingResponse for user_a with couple=None
    4. Associate it with the newly formed couple

    Called during registration flow.
    """
    with transaction.atomic():
        locked_users = _lock_users(new_user.id)
        new_user = locked_users.get(new_user.id, new_user)

        pending_couple = (
            Couple.objects.select_for_update()
            .select_related("user_a")
            .filter(
                invite_email=new_user.email.lower(),
                status__in=[CoupleStatus.PENDING, CoupleStatus.ACTIVE],
                user_b__isnull=True,
            )
            .order_by(
                Case(
                    When(status=CoupleStatus.PENDING, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .first()
        )

        if not pending_couple:
            return None

        locked_users = _lock_users(new_user.id, pending_couple.user_a_id)
        new_user = locked_users.get(new_user.id, new_user)
        pending_couple.user_a = locked_users.get(pending_couple.user_a_id, pending_couple.user_a)

        active_couple_for_inviter = get_active_couple(pending_couple.user_a)
        if active_couple_for_inviter and active_couple_for_inviter.id != pending_couple.id:
            logger.warning(
                "Pending invite not connected because inviter already has an active couple: inviter=%s",
                pending_couple.user_a.email,
            )
            return None

        if has_active_couple(new_user):
            logger.warning(
                "Pending invite not connected because new user is already in an active couple: user=%s",
                new_user.email,
            )
            return None

        pending_couple.user_b = new_user
        pending_couple.status = CoupleStatus.ACTIVE
        pending_couple.save(update_fields=["user_b", "status", "updated_at"])
        logger.info("Pending invite connected: couple=%s new_user=%s", pending_couple.id, new_user.email)

        # Associate solo onboarding responses with the newly formed couple
        updated_new_user = OnboardingResponse.objects.filter(
            user=new_user, couple=None
        ).update(couple=pending_couple)
        if updated_new_user:
            logger.info(
                "Associated %s solo onboarding response(s) for new_user=%s with couple=%s",
                updated_new_user, new_user.email, pending_couple.id,
            )

        updated_user_a = OnboardingResponse.objects.filter(
            user=pending_couple.user_a, couple=None
        ).update(couple=pending_couple)
        if updated_user_a:
            logger.info(
                "Associated %s solo onboarding response(s) for user_a=%s with couple=%s",
                updated_user_a, pending_couple.user_a.email, pending_couple.id,
            )

        return pending_couple


def get_couple_status(user: "User") -> dict:
    """Return couple info, partner status, and onboarding completeness."""
    couple = get_couple_for_user(user)

    if not couple:
        from core.models import OnboardingResponse

        user_onboarded_solo = OnboardingResponse.objects.filter(user=user, couple=None).exists()
        return {
            "has_couple": False,
            "couple": None,
            "partner": None,
            "onboarding_complete": {"user": user_onboarded_solo, "partner": False},
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
