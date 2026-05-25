"""Integration tests for BabyBase.

Tests full flows across multiple services.
"""

import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from core.models import (
    Couple,
    CoupleStatus,
    MatchStatus,
    MutualMatch,
    Name,
    OnboardingResponse,
    RecommendationDeck,
)
from core.services.couples import connect_pending_invite, create_couple
from core.services.swipes import (
    check_mutual_match,
    create_match,
    record_swipe,
    validate_swipe,
)

User = get_user_model()


@pytest.fixture
def active_couple(db):
    """Create an active couple with onboarding complete."""
    user_a = User.objects.create_user(email="int_a@test.com", password="testpass123")
    user_b = User.objects.create_user(email="int_b@test.com", password="testpass123")
    couple = Couple.objects.create(
        user_a=user_a,
        user_b=user_b,
        status=CoupleStatus.ACTIVE,
        residence_country="DE",
    )
    OnboardingResponse.objects.create(
        user=user_a,
        couple=couple,
        preferred_name_backgrounds=["Spanish", "German"],
        preferred_name_age="balanced",
        baby_gender_preference="boy",
        preferred_name_length="any",
        historical_importance="medium",
    )
    OnboardingResponse.objects.create(
        user=user_b,
        couple=couple,
        preferred_name_backgrounds=["Russian", "German"],
        preferred_name_age="old",
        baby_gender_preference="boy",
        preferred_name_length="short",
        historical_importance="high",
    )
    return couple, user_a, user_b


@pytest.fixture
def names_pool(db):
    """Create a pool of names for integration testing."""
    names = []
    data = [
        ("IntSofia", ["Spanish", "Greek", "Russian"], ["es", "en", "ru", "de"], "classic", 0.8),
        ("IntMateo", ["Spanish"], ["es", "en"], "modern", 0.4),
        ("IntNadia", ["Russian", "Arabic"], ["ru", "ar", "en"], "timeless", 0.6),
        ("IntLeo", ["German", "Spanish"], ["de", "es", "en"], "classic", 0.5),
        ("IntKai", ["Japanese", "German"], ["ja", "de", "en"], "modern", 0.3),
        ("IntElena", ["Spanish", "Russian", "Greek"], ["es", "ru", "el", "de"], "timeless", 0.7),
        ("IntMila", ["Russian", "Spanish"], ["ru", "es", "en"], "modern", 0.5),
    ]
    for canonical, origins, langs, style, hist in data:
        name = Name.objects.create(
            canonical_name=canonical,
            display_name=canonical,
            gender_usage=["boy"] if canonical in ("IntMateo", "IntLeo", "IntKai") else ["girl"],
            origin_backgrounds=origins,
            languages=langs,
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category=style,
            historical_significance_score=hist,
            semantic_summary=f"A {style} name from {', '.join(origins)} tradition.",
            active=True,
        )
        names.append(name)
    return names


class TestSwipeMatchShortlistFlow:
    """Integration test: Swipe → match → shortlist flow."""

    def test_full_swipe_to_shortlist(self, active_couple, names_pool):
        """Both parents like a name → match created → can be shortlisted."""
        couple, user_a, user_b = active_couple
        name = names_pool[0]  # IntSofia

        # Parent A swipes like
        validate_swipe(user_a, couple, str(name.id))
        swipe_a, created_a = record_swipe(user_a, couple, str(name.id), "like")
        assert created_a is True

        # No match yet (only one parent swiped)
        assert check_mutual_match(couple, str(name.id)) is False

        # Parent B swipes like
        validate_swipe(user_b, couple, str(name.id))
        swipe_b, created_b = record_swipe(user_b, couple, str(name.id), "like")
        assert created_b is True

        # Now it's a match
        assert check_mutual_match(couple, str(name.id)) is True

        # Create the match
        match = create_match(couple, str(name.id))
        assert match.status == MatchStatus.ACTIVE
        assert match.match_strength_score > 0.0

        # Promote to shortlist
        match.status = MatchStatus.SHORTLISTED
        match.save()

        shortlisted = MutualMatch.objects.filter(
            couple=couple, status=MatchStatus.SHORTLISTED
        )
        assert shortlisted.count() == 1
        assert shortlisted.first().name == name

    def test_dislike_prevents_match(self, active_couple, names_pool):
        """One parent disliking prevents a match even if other likes."""
        couple, user_a, user_b = active_couple
        name = names_pool[1]  # IntMateo

        record_swipe(user_a, couple, str(name.id), "like")
        record_swipe(user_b, couple, str(name.id), "dislike")

        assert check_mutual_match(couple, str(name.id)) is False
        assert not MutualMatch.objects.filter(couple=couple, name=name).exists()

    def test_multiple_matches_independent(self, active_couple, names_pool):
        """Multiple names can be matched independently."""
        couple, user_a, user_b = active_couple

        matched_names = []
        for name in names_pool[:3]:
            record_swipe(user_a, couple, str(name.id), "like")
            record_swipe(user_b, couple, str(name.id), "like")

            if check_mutual_match(couple, str(name.id)):
                create_match(couple, str(name.id))
                matched_names.append(name)

        assert len(matched_names) == 3
        assert MutualMatch.objects.filter(couple=couple).count() == 3


class TestPartnerInviteSignupFlow:
    """Integration test: Partner invite → signup → auto-connect."""

    def test_invite_then_signup_connects(self, db):
        """Full flow: user A invites → partner signs up → couple activates."""
        # Step 1: User A creates account and invites partner
        user_a = User.objects.create_user(email="inviter@test.com", password="testpass123")
        couple = create_couple(user_a, "invitee@test.com")

        assert couple.status == CoupleStatus.PENDING
        assert couple.user_b is None

        # Step 2: Partner signs up with the invited email
        user_b = User.objects.create_user(email="invitee@test.com", password="testpass123")

        # Step 3: Auto-connect triggers
        connected = connect_pending_invite(user_b)

        assert connected is not None
        assert connected.id == couple.id
        assert connected.user_b == user_b
        assert connected.status == CoupleStatus.ACTIVE

        # Step 4: Both can now swipe
        name = Name.objects.create(
            canonical_name="FlowTestName",
            display_name="Flow Test Name",
            gender_usage=["boy"],
            origin_backgrounds=["Spanish"],
            languages=["es"],
            scripts=["Latin"],
            variants=[],
            length_category="short",
            age_style_category="classic",
            historical_significance_score=0.5,
            semantic_summary="Test name for flow.",
            active=True,
        )

        # Both parents can swipe
        swipe_a, _ = record_swipe(user_a, connected, str(name.id), "like")
        swipe_b, _ = record_swipe(user_b, connected, str(name.id), "like")

        assert check_mutual_match(connected, str(name.id)) is True

    def test_invite_existing_user_immediate_connect(self, db):
        """Inviting an existing user connects immediately."""
        user_a = User.objects.create_user(email="existing_a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="existing_b@test.com", password="testpass123")

        couple = create_couple(user_a, user_b.email)

        assert couple.status == CoupleStatus.ACTIVE
        assert couple.user_b == user_b


class TestDeckGenerationPipeline:
    """Integration test: Full deck generation pipeline (mock Qdrant + Bedrock Titan)."""

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_full_pipeline_with_exclusions(
        self, mock_embedding, mock_search, active_couple, names_pool
    ):
        """Full pipeline: onboarding → query → re-rank → persist, with exclusions."""
        from core.services.recommendations import generate_deck

        couple, user_a, user_b = active_couple

        # Pre-swipe some names (should be excluded from deck)
        record_swipe(user_a, couple, str(names_pool[0].id), "like")
        record_swipe(user_b, couple, str(names_pool[1].id), "dislike")

        # Mock embedding
        mock_embedding.return_value = [0.1] * 1024

        # Mock Qdrant returns remaining names (not the swiped ones)
        remaining_names = names_pool[2:]  # Skip first two (swiped)
        candidates = []
        for i, name in enumerate(remaining_names):
            candidates.append({
                "point_id": str(uuid.uuid4()),
                "name_id": str(name.id),
                "score": 0.9 - i * 0.05,
                "payload": {
                    "name_id": str(name.id),
                    "canonical_name": name.canonical_name,
                    "origin_backgrounds": name.origin_backgrounds,
                    "languages": name.languages,
                    "length_category": name.length_category,
                    "age_style_category": name.age_style_category,
                    "historical_significance_score": name.historical_significance_score,
                    "gender_usage": name.gender_usage,
                    "active": True,
                },
            })
        mock_search.return_value = candidates

        # Generate deck
        deck = generate_deck(couple, mode="best_match")

        # Verify deck was created
        assert isinstance(deck, RecommendationDeck)
        assert deck.couple == couple
        assert deck.mode == "best_match"

        # Verify items were persisted
        items = deck.items.all()
        assert items.count() > 0

        # Verify swiped names are NOT in the deck
        deck_name_ids = set(str(item.name_id) for item in items)
        assert str(names_pool[0].id) not in deck_name_ids
        assert str(names_pool[1].id) not in deck_name_ids

        # Verify items have scores and explanations
        for item in items:
            assert item.rerank_score >= 0.0
            assert item.explanation_summary != ""
