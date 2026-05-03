"""Management command to seed demo data for BabyBase.

Creates a demo couple (Mexican father + Russian mother, residence: Germany)
with pre-filled onboarding and some pre-swiped names to show matches and taste drift.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Couple,
    CoupleStatus,
    MatchStatus,
    MutualMatch,
    Name,
    OnboardingResponse,
    Swipe,
    SwipeAction,
)

User = get_user_model()

# Demo user credentials
DEMO_FATHER_EMAIL = "carlos@demo.babybase.app"
DEMO_MOTHER_EMAIL = "natasha@demo.babybase.app"
DEMO_PASSWORD = "demo1234!"


class Command(BaseCommand):
    help = "Seed demo data: Mexican father + Russian mother in Germany with pre-swiped names."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self._cleanup()

        # Step 1: Create demo users
        father, mother = self._create_users()

        # Step 2: Create couple
        couple = self._create_couple(father, mother)

        # Step 3: Fill onboarding for both parents
        self._create_onboarding(father, mother, couple)

        # Step 4: Pre-swipe names to show matches and taste drift
        self._create_swipes(father, mother, couple)

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully!"))
        self.stdout.write(f"  Father: {DEMO_FATHER_EMAIL} / {DEMO_PASSWORD}")
        self.stdout.write(f"  Mother: {DEMO_MOTHER_EMAIL} / {DEMO_PASSWORD}")

    def _cleanup(self):
        """Remove existing demo data."""
        demo_emails = [DEMO_FATHER_EMAIL, DEMO_MOTHER_EMAIL]
        users = User.objects.filter(email__in=demo_emails)
        if users.exists():
            # Delete couples (cascades to swipes, matches, decks)
            from django.db.models import Q

            Couple.objects.filter(
                Q(user_a__email__in=demo_emails) | Q(user_b__email__in=demo_emails)
            ).delete()
            users.delete()
            self.stdout.write("  Cleaned up existing demo data.")

    def _create_users(self) -> tuple:
        """Create demo father and mother users."""
        father, created = User.objects.get_or_create(
            email=DEMO_FATHER_EMAIL,
            defaults={
                "first_name": "Carlos",
                "role_in_pregnancy": "father",
                "age": 32,
                "gender": "male",
                "nationality": "Mexican",
            },
        )
        if created:
            father.set_password(DEMO_PASSWORD)
            father.save()
            self.stdout.write(f"  Created father: {father.email}")
        else:
            self.stdout.write(f"  Father already exists: {father.email}")

        mother, created = User.objects.get_or_create(
            email=DEMO_MOTHER_EMAIL,
            defaults={
                "first_name": "Natasha",
                "role_in_pregnancy": "mother",
                "age": 29,
                "gender": "female",
                "nationality": "Russian",
            },
        )
        if created:
            mother.set_password(DEMO_PASSWORD)
            mother.save()
            self.stdout.write(f"  Created mother: {mother.email}")
        else:
            self.stdout.write(f"  Mother already exists: {mother.email}")

        return father, mother

    def _create_couple(self, father, mother) -> Couple:
        """Create the demo couple."""
        couple, created = Couple.objects.get_or_create(
            user_a=father,
            user_b=mother,
            defaults={
                "status": CoupleStatus.ACTIVE,
                "invite_email": DEMO_MOTHER_EMAIL,
                "residence_country": "DE",
            },
        )
        if created:
            self.stdout.write("  Created couple (residence: Germany)")
        else:
            self.stdout.write("  Couple already exists")
        return couple

    def _create_onboarding(self, father, mother, couple):
        """Pre-fill onboarding for both parents."""
        # Father's preferences (Mexican background)
        OnboardingResponse.objects.get_or_create(
            user=father,
            couple=couple,
            defaults={
                "preferred_name_backgrounds": ["Spanish", "German", "International"],
                "preferred_name_age": "balanced",
                "baby_gender_preference": "boy",
                "preferred_name_length": "short",
                "historical_importance": "medium",
            },
        )

        # Mother's preferences (Russian background)
        OnboardingResponse.objects.get_or_create(
            user=mother,
            couple=couple,
            defaults={
                "preferred_name_backgrounds": ["Russian", "German", "Greek"],
                "preferred_name_age": "old",
                "baby_gender_preference": "boy",
                "preferred_name_length": "any",
                "historical_importance": "high",
            },
        )
        self.stdout.write("  Onboarding responses created for both parents")

    def _create_swipes(self, father, mother, couple):
        """Create pre-swiped names to demonstrate matches and taste drift."""
        # Get available names from the database
        names = list(Name.objects.filter(active=True).order_by("canonical_name"))

        if not names:
            self.stdout.write(
                self.style.WARNING(
                    "  No names in database. Run 'seed_names' first, then re-run 'seed_demo'."
                )
            )
            return

        # Strategy: Create a mix of matches, near-misses, and divergent swipes
        # to show taste drift and the matching algorithm in action.

        swipe_count = 0
        match_count = 0

        # Find names by origin for targeted swipes
        spanish_names = [n for n in names if "Spanish" in (n.origin_backgrounds or [])]
        russian_names = [n for n in names if "Russian" in (n.origin_backgrounds or [])]
        german_names = [n for n in names if "German" in (n.origin_backgrounds or [])]
        bridge_names = [
            n for n in names
            if set(n.origin_backgrounds or []) & {"Spanish", "Russian"}
            and len(n.origin_backgrounds or []) > 1
        ]

        # Both like bridge names (creates matches)
        for name in bridge_names[:5]:
            self._swipe(couple, father, name, SwipeAction.LIKE)
            self._swipe(couple, mother, name, SwipeAction.LIKE)
            # Create the match
            MutualMatch.objects.get_or_create(
                couple=couple,
                name=name,
                defaults={
                    "match_strength_score": 0.8,
                    "status": MatchStatus.ACTIVE,
                },
            )
            swipe_count += 2
            match_count += 1

        # Father likes Spanish names, mother is mixed
        for name in spanish_names[:4]:
            if name in bridge_names[:5]:
                continue
            self._swipe(couple, father, name, SwipeAction.LIKE)
            # Mother likes some, dislikes others (shows divergence)
            action = SwipeAction.LIKE if name.historical_significance_score > 0.5 else SwipeAction.DISLIKE
            self._swipe(couple, mother, name, action)
            swipe_count += 2

            if action == SwipeAction.LIKE:
                MutualMatch.objects.get_or_create(
                    couple=couple,
                    name=name,
                    defaults={
                        "match_strength_score": 0.6,
                        "status": MatchStatus.ACTIVE,
                    },
                )
                match_count += 1

        # Mother likes Russian names, father is mixed
        for name in russian_names[:4]:
            if name in bridge_names[:5]:
                continue
            self._swipe(couple, mother, name, SwipeAction.LIKE)
            action = SwipeAction.MAYBE if name.historical_significance_score > 0.6 else SwipeAction.DISLIKE
            self._swipe(couple, father, name, action)
            swipe_count += 2

        # Both like German-friendly names (residence country fit)
        for name in german_names[:3]:
            if name in bridge_names[:5] or name in spanish_names[:4] or name in russian_names[:4]:
                continue
            self._swipe(couple, father, name, SwipeAction.LIKE)
            self._swipe(couple, mother, name, SwipeAction.LIKE)
            MutualMatch.objects.get_or_create(
                couple=couple,
                name=name,
                defaults={
                    "match_strength_score": 0.7,
                    "status": MatchStatus.ACTIVE,
                },
            )
            swipe_count += 2
            match_count += 1

        # Shortlist the top 2 matches
        top_matches = MutualMatch.objects.filter(couple=couple).order_by("-match_strength_score")[:2]
        for match in top_matches:
            match.status = MatchStatus.SHORTLISTED
            match.save()

        self.stdout.write(
            f"  Created {swipe_count} swipes, {match_count} matches, "
            f"{top_matches.count()} shortlisted"
        )

    def _swipe(self, couple, user, name, action):
        """Create a swipe if it doesn't already exist."""
        Swipe.objects.get_or_create(
            couple=couple,
            user=user,
            name=name,
            defaults={"action": action},
        )
