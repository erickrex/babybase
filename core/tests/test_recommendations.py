"""Unit tests for recommendation service (mock Qdrant + OpenAI)."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    Couple,
    CoupleStatus,
    Name,
    OnboardingResponse,
    RecommendationDeck,
    Swipe,
    SwipeAction,
)
from core.services.recommendations import (
    _apply_diversity_constraints,
    _build_payload_filters,
    _get_excluded_name_ids,
    _rerank_candidates,
    generate_deck,
)

User = get_user_model()


@pytest.fixture
def couple_with_onboarding(db):
    """Create a couple with completed onboarding."""
    user_a = User.objects.create_user(email="rec_a@test.com", password="testpass123")
    user_b = User.objects.create_user(email="rec_b@test.com", password="testpass123")
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
def sample_names(db):
    """Create a set of sample names for testing."""
    names = []
    name_data = [
        ("Sofia", ["Spanish", "Greek", "Russian"], ["es", "en", "ru", "de"], "classic", 0.8),
        ("Mateo", ["Spanish"], ["es", "en"], "modern", 0.4),
        ("Nadia", ["Russian", "Arabic"], ["ru", "ar", "en"], "timeless", 0.6),
        ("Leo", ["German", "Spanish"], ["de", "es", "en"], "classic", 0.5),
        ("Kai", ["Japanese", "German"], ["ja", "de", "en"], "modern", 0.3),
    ]
    for canonical, origins, langs, style, hist in name_data:
        name = Name.objects.create(
            canonical_name=canonical,
            display_name=canonical,
            gender_usage=["boy"],
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


def _make_qdrant_candidate(name: Name, score: float = 0.8) -> dict:
    """Helper to create a mock Qdrant candidate dict from a Name."""
    return {
        "point_id": str(uuid.uuid4()),
        "name_id": str(name.id),
        "score": score,
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
    }


class TestGenerateDeck:
    """Tests for generate_deck with mocked Qdrant responses."""

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_generate_deck_best_match(
        self, mock_embedding, mock_search, couple_with_onboarding, sample_names
    ):
        """Deck generation in best_match mode produces a persisted deck."""
        couple, _, _ = couple_with_onboarding

        # Mock embedding
        mock_embedding.return_value = [0.1] * 1536

        # Mock Qdrant search results
        candidates = [_make_qdrant_candidate(n, 0.9 - i * 0.1) for i, n in enumerate(sample_names)]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="best_match")

        assert isinstance(deck, RecommendationDeck)
        assert deck.couple == couple
        assert deck.mode == "best_match"
        assert deck.items.count() > 0
        assert deck.items.count() <= len(sample_names)

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.compute_bridge_centroid")
    def test_generate_deck_bridge_names(
        self, mock_centroid, mock_search, couple_with_onboarding, sample_names
    ):
        """Deck generation in bridge_names mode uses bridge centroid."""
        couple, _, _ = couple_with_onboarding

        mock_centroid.return_value = [0.2] * 1536
        candidates = [_make_qdrant_candidate(n, 0.85 - i * 0.1) for i, n in enumerate(sample_names)]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="bridge_names")

        assert deck.mode == "bridge_names"
        assert deck.items.count() > 0
        mock_centroid.assert_called_once_with(couple)

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_generate_deck_empty_results_relaxes_filters(
        self, mock_embedding, mock_search, couple_with_onboarding, sample_names
    ):
        """When strict filters return nothing, relaxed filters are tried."""
        couple, _, _ = couple_with_onboarding
        mock_embedding.return_value = [0.1] * 1536

        # First call returns empty, second returns results
        candidates = [_make_qdrant_candidate(n, 0.7) for n in sample_names]
        mock_search.side_effect = [[], candidates]

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        assert mock_search.call_count == 2


class TestExclusionLogic:
    """Tests for deck exclusion of previously swiped names."""

    def test_swiped_names_excluded(self, couple_with_onboarding, sample_names):
        """Previously swiped names appear in exclusion set."""
        couple, user_a, user_b = couple_with_onboarding

        # Swipe on first two names
        Swipe.objects.create(couple=couple, user=user_a, name=sample_names[0], action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=sample_names[1], action=SwipeAction.DISLIKE)

        excluded = _get_excluded_name_ids(couple)

        assert str(sample_names[0].id) in excluded
        assert str(sample_names[1].id) in excluded
        assert str(sample_names[2].id) not in excluded

    def test_all_actions_excluded(self, couple_with_onboarding, sample_names):
        """Like, dislike, and maybe swipes are all excluded."""
        couple, user_a, _ = couple_with_onboarding

        Swipe.objects.create(couple=couple, user=user_a, name=sample_names[0], action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_a, name=sample_names[1], action=SwipeAction.DISLIKE)
        Swipe.objects.create(couple=couple, user=user_a, name=sample_names[2], action=SwipeAction.MAYBE)

        excluded = _get_excluded_name_ids(couple)

        assert str(sample_names[0].id) in excluded
        assert str(sample_names[1].id) in excluded
        assert str(sample_names[2].id) in excluded

    def test_no_swipes_empty_exclusion(self, couple_with_onboarding):
        """No swipes = empty exclusion set."""
        couple, _, _ = couple_with_onboarding
        excluded = _get_excluded_name_ids(couple)
        assert excluded == []


class TestModeSelection:
    """Tests for recommendation mode behavior."""

    def test_payload_filters_include_gender(self):
        """Payload filters include gender from profile."""
        profile = {"baby_gender": "boy", "preferred_length": "short"}
        filters = _build_payload_filters(profile)

        assert filters["active"] is True
        assert filters["gender_usage"] == "boy"

    def test_payload_filters_non_binary_no_gender_filter(self):
        """Non-binary gender preference doesn't add gender filter."""
        profile = {"baby_gender": "non_binary"}
        filters = _build_payload_filters(profile)

        assert filters["active"] is True
        assert "gender_usage" not in filters

    def test_diversity_constraints_limit_deck_size(self):
        """Diversity constraints cap the deck at the specified size."""
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(uuid.uuid4()),
                "score": 0.9 - i * 0.05,
                "rerank_score": 0.8,
                "payload": {
                    "canonical_name": f"Name{i}",
                    "origin_backgrounds": ["Spanish"],
                    "age_style_category": "classic",
                },
            }
            for i in range(5)
        ]

        result = _apply_diversity_constraints(candidates, deck_size=3)
        assert len(result) == 3

    def test_diversity_constraints_pass_through_small_deck(self):
        """If candidates <= deck_size, all are returned."""
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(uuid.uuid4()),
                "score": 0.9,
                "rerank_score": 0.8,
                "payload": {
                    "canonical_name": f"Name{i}",
                    "origin_backgrounds": ["Spanish"],
                    "age_style_category": "classic",
                },
            }
            for i in range(2)
        ]

        result = _apply_diversity_constraints(candidates, deck_size=50)
        assert len(result) == 2


class TestRerankCandidates:
    """Tests for deterministic reranking behavior."""

    @staticmethod
    def _candidate(
        name_id: str,
        canonical_name: str,
        origins: list[str],
        score: float,
    ) -> dict:
        return {
            "point_id": str(uuid.uuid4()),
            "name_id": name_id,
            "score": score,
            "payload": {
                "name_id": name_id,
                "canonical_name": canonical_name,
                "origin_backgrounds": origins,
                "languages": [],
                "length_category": "short",
                "age_style_category": "classic",
                "historical_significance_score": 0.5,
                "gender_usage": ["boy"],
                "active": True,
            },
        }

    def test_reranking_is_independent_of_candidate_input_order(self):
        """Equivalent candidate sets produce the same ranked order."""
        couple = SimpleNamespace(residence_country=None)
        profile = {
            "preferred_length": "any",
            "preferred_age": "balanced",
            "historical_importance": "medium",
        }
        parent_a_profile = {"preferred_backgrounds": ["Spanish"]}
        parent_b_profile = {"preferred_backgrounds": ["Russian"]}

        candidates = [
            self._candidate("alpha", "Alpha", ["Spanish"], 0.8),
            self._candidate("beta", "Beta", ["Russian"], 0.8),
            self._candidate("gamma", "Gamma", ["Spanish", "Russian"], 0.8),
        ]

        ranked_a = _rerank_candidates(
            candidates=candidates,
            couple=couple,
            profile=profile,
            parent_a_profile=parent_a_profile,
            parent_b_profile=parent_b_profile,
            mode="best_match",
        )
        ranked_b = _rerank_candidates(
            candidates=list(reversed(candidates)),
            couple=couple,
            profile=profile,
            parent_a_profile=parent_a_profile,
            parent_b_profile=parent_b_profile,
            mode="best_match",
        )

        assert [c["name_id"] for c in ranked_a] == [c["name_id"] for c in ranked_b]
        assert ranked_a[0]["name_id"] == "gamma"

    def test_reranking_prefers_new_origin_after_first_selection(self):
        """Novelty and diversity are computed from the selected ranked deck."""
        couple = SimpleNamespace(residence_country=None)
        profile = {
            "preferred_length": "any",
            "preferred_age": "balanced",
            "historical_importance": "medium",
        }
        parent_a_profile = {"preferred_backgrounds": []}
        parent_b_profile = {"preferred_backgrounds": []}

        candidates = [
            self._candidate("aaron", "Aaron", ["Spanish"], 0.95),
            self._candidate("avery", "Avery", ["Spanish"], 0.8),
            self._candidate("blair", "Blair", ["Russian"], 0.8),
        ]

        ranked = _rerank_candidates(
            candidates=candidates,
            couple=couple,
            profile=profile,
            parent_a_profile=parent_a_profile,
            parent_b_profile=parent_b_profile,
            mode="best_match",
        )

        assert [candidate["name_id"] for candidate in ranked[:2]] == ["aaron", "blair"]


class TestUnexpiredDeckReuse:
    """Tests for unexpired deck reuse in generate_deck (Requirement 5.1)."""

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_unexpired_deck_is_reused(
        self, mock_embedding, mock_search, couple_with_onboarding, sample_names
    ):
        """When an unexpired deck of the same mode exists, it is returned without creating a new one."""
        couple, _, _ = couple_with_onboarding

        # Create an existing unexpired deck
        existing_deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() + timezone.timedelta(days=3),
        )

        # Call generate_deck — should return existing without calling Qdrant
        result = generate_deck(couple, mode="best_match")

        assert result.id == existing_deck.id
        mock_embedding.assert_not_called()
        mock_search.assert_not_called()

    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_expired_deck_triggers_new_generation(
        self, mock_embedding, mock_search, couple_with_onboarding, sample_names
    ):
        """When the existing deck is expired, a new deck is generated."""
        couple, _, _ = couple_with_onboarding

        # Create an expired deck
        expired_deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )

        # Mock embedding and search for new generation
        mock_embedding.return_value = [0.1] * 1536
        candidates = [_make_qdrant_candidate(n, 0.9 - i * 0.1) for i, n in enumerate(sample_names)]
        mock_search.return_value = candidates

        result = generate_deck(couple, mode="best_match")

        # Should be a new deck, not the expired one
        assert result.id != expired_deck.id
        mock_embedding.assert_called_once()
        mock_search.assert_called()
