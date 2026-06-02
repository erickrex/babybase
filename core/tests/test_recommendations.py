"""Unit tests for recommendation service (mock Qdrant + Bedrock Titan)."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    Couple,
    CoupleStatus,
    DeckMode,
    Name,
    OnboardingResponse,
    RecommendationDeck,
    Swipe,
    SwipeAction,
)
from core.services.recommendations import (
    _apply_diversity_constraints,
    _apply_mode_score_adjustments,
    _build_explanation,
    _build_payload_filters,
    _get_excluded_name_ids,
    _interleave_by_first_letter,
    _rerank_candidates,
    _vector_name_for_mode,
    generate_deck,
    get_cached_deck,
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
        mock_embedding.return_value = [0.1] * 1024

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

        mock_centroid.return_value = [0.2] * 1024
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
        mock_embedding.return_value = [0.1] * 1024

        # First call returns empty, second returns results
        candidates = [_make_qdrant_candidate(n, 0.7) for n in sample_names]
        mock_search.side_effect = [[], candidates]

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        assert mock_search.call_count == 2


class TestEmbeddingUnavailableFallback:
    """When the embedding backend fails, deck falls back to filter-only retrieval."""

    @patch("core.services.recommendations.get_names_by_filter")
    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations._build_query_embedding_for_mode")
    def test_bedrock_failure_falls_back_to_filter_only(
        self, mock_embedding, mock_search, mock_filter, couple_with_onboarding, sample_names
    ):
        """A Bedrock failure yields a usable deck via filter-only retrieval, no crash."""
        from botocore.exceptions import BotoCoreError

        couple, _, _ = couple_with_onboarding
        mock_embedding.side_effect = BotoCoreError()
        # Filter-only retrieval returns candidates with score 0.0 (no vector).
        candidates = [_make_qdrant_candidate(n, 0.0) for n in sample_names]
        mock_filter.return_value = candidates

        deck = generate_deck(couple, mode="best_match")

        assert isinstance(deck, RecommendationDeck)
        assert deck.items.count() > 0
        # Vector search must NOT be used when the embedding is unavailable.
        mock_search.assert_not_called()
        mock_filter.assert_called()
        # The degraded path is recorded for observability.
        assert deck.retrieval_profile_json.get("fallback_reason") == "embedding_unavailable"

    @patch("core.services.recommendations.get_names_by_filter")
    @patch("core.services.recommendations._build_query_embedding_for_mode")
    def test_filter_only_retries_unfiltered_when_empty(
        self, mock_embedding, mock_filter, couple_with_onboarding, sample_names
    ):
        """Filter-only path retries without strict filters when the first pass is empty."""
        from botocore.exceptions import BotoCoreError

        couple, _, _ = couple_with_onboarding
        mock_embedding.side_effect = BotoCoreError()
        candidates = [_make_qdrant_candidate(n, 0.0) for n in sample_names]
        # First filtered scroll empty, second (relaxed) returns candidates.
        mock_filter.side_effect = [[], candidates]

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        assert mock_filter.call_count == 2


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

    def test_interleave_by_first_letter_breaks_runs_and_preserves_letter_order(self):
        """Deck display order cycles through first letters while preserving intra-letter order."""
        candidates = [
            {
                "rerank_score": 0.9 - i * 0.01,
                "retrieval_score": 0.9 - i * 0.01,
                "payload": {"canonical_name": name},
            }
            for i, name in enumerate(["Aaron", "Adam", "Andrew", "Benjamin", "Caleb", "Charles"])
        ]

        result = _interleave_by_first_letter(candidates)

        assert [candidate["payload"]["canonical_name"] for candidate in result[:4]] == [
            "Aaron",
            "Benjamin",
            "Caleb",
            "Adam",
        ]
        a_names = [
            candidate["payload"]["canonical_name"]
            for candidate in result
            if candidate["payload"]["canonical_name"].startswith("A")
        ]

        assert a_names == ["Aaron", "Adam", "Andrew"]


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


class TestDeckCaching:
    """Tests for reusable unexpired deck lookup."""

    def test_unexpired_deck_with_items_is_cached(self, couple_with_onboarding, sample_names):
        """An existing unexpired deck with items is reusable."""
        couple, _, _ = couple_with_onboarding

        existing_deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() + timezone.timedelta(days=3),
        )
        existing_deck.items.create(name=sample_names[0], rank=1)

        assert get_cached_deck(couple, mode="best_match") == existing_deck

    def test_unexpired_empty_deck_is_not_cached(self, couple_with_onboarding):
        """Empty decks are ignored so callers can regenerate usable recommendations."""
        couple, _, _ = couple_with_onboarding
        RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() + timezone.timedelta(days=3),
        )

        assert get_cached_deck(couple, mode="best_match") is None

    def test_fully_swiped_deck_is_not_cached(self, couple_with_onboarding, sample_names):
        """Cached decks are ignored after all of their items have been swiped."""
        couple, user_a, _ = couple_with_onboarding
        deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() + timezone.timedelta(days=3),
        )
        deck.items.create(name=sample_names[0], rank=1)
        Swipe.objects.create(couple=couple, user=user_a, name=sample_names[0], action=SwipeAction.LIKE)

        assert get_cached_deck(couple, mode="best_match") is None

    def test_partially_swiped_deck_is_cached(self, couple_with_onboarding, sample_names):
        """Cached decks remain usable while at least one item is unswiped."""
        couple, user_a, _ = couple_with_onboarding
        deck = RecommendationDeck.objects.create(
            couple=couple,
            mode="best_match",
            retrieval_profile_json={},
            expires_at=timezone.now() + timezone.timedelta(days=3),
        )
        deck.items.create(name=sample_names[0], rank=1)
        deck.items.create(name=sample_names[1], rank=2)
        Swipe.objects.create(couple=couple, user=user_a, name=sample_names[0], action=SwipeAction.LIKE)

        assert get_cached_deck(couple, mode="best_match") == deck

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
        mock_embedding.return_value = [0.1] * 1024
        candidates = [_make_qdrant_candidate(n, 0.9 - i * 0.1) for i, n in enumerate(sample_names)]
        mock_search.return_value = candidates

        result = generate_deck(couple, mode="best_match")

        # Should be a new deck, not the expired one
        assert result.id != expired_deck.id
        mock_embedding.assert_called_once()
        mock_search.assert_called()


class TestSparseRetrievalFallback:
    """Tests for sparse retrieval fallback when Phase D top score < 0.6."""

    @patch("core.services.recommendations.select_phase")
    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    @patch("core.services.recommendations.compute_confidence_weighted_midpoint")
    def test_phase_d_low_score_triggers_fallback(
        self,
        mock_midpoint,
        mock_embedding,
        mock_search,
        mock_select_phase,
        couple_with_onboarding,
        sample_names,
    ):
        """When Phase D top score < 0.6, results are discarded and Phase C is used."""
        couple, _, _ = couple_with_onboarding

        # select_phase returns phase_d (called twice: once in _build_query_embedding_for_mode,
        # once in generate_deck for tracking)
        mock_select_phase.return_value = (
            "phase_d",
            {"vec_a": [0.1] * 1024, "conf_a": 0.8, "vec_b": [0.2] * 1024, "conf_b": 0.7},
        )
        mock_midpoint.return_value = [0.15] * 1024
        mock_embedding.return_value = [0.3] * 1024  # Phase C embedding

        # First search (Phase D) returns low scores
        low_score_candidates = [_make_qdrant_candidate(n, 0.4 - i * 0.05) for i, n in enumerate(sample_names)]
        # Second search (Phase C fallback) returns good scores
        good_candidates = [_make_qdrant_candidate(n, 0.85 - i * 0.05) for i, n in enumerate(sample_names)]
        mock_search.side_effect = [low_score_candidates, good_candidates]

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        # Phase C embedding should have been called for the fallback
        mock_embedding.assert_called_once_with(couple)
        # search_names called twice: once with Phase D, once with Phase C
        assert mock_search.call_count == 2

    @patch("core.services.recommendations.select_phase")
    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    @patch("core.services.recommendations.compute_confidence_weighted_midpoint")
    def test_phase_d_high_score_no_fallback(
        self,
        mock_midpoint,
        mock_embedding,
        mock_search,
        mock_select_phase,
        couple_with_onboarding,
        sample_names,
    ):
        """When Phase D top score >= 0.6, no fallback occurs."""
        couple, _, _ = couple_with_onboarding

        mock_select_phase.return_value = (
            "phase_d",
            {"vec_a": [0.1] * 1024, "conf_a": 0.8, "vec_b": [0.2] * 1024, "conf_b": 0.7},
        )
        mock_midpoint.return_value = [0.15] * 1024

        # Search returns good scores (>= 0.6)
        good_candidates = [_make_qdrant_candidate(n, 0.85 - i * 0.05) for i, n in enumerate(sample_names)]
        mock_search.return_value = good_candidates

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        # Phase C embedding should NOT have been called
        mock_embedding.assert_not_called()
        # search_names called only once (Phase D was sufficient)
        assert mock_search.call_count == 1

    @patch("core.services.recommendations.select_phase")
    @patch("core.services.recommendations.search_names")
    @patch("core.services.recommendations.build_couple_query_embedding")
    def test_phase_c_no_fallback_check(
        self,
        mock_embedding,
        mock_search,
        mock_select_phase,
        couple_with_onboarding,
        sample_names,
    ):
        """When Phase C is used directly, no sparse retrieval fallback check occurs."""
        couple, _, _ = couple_with_onboarding

        # select_phase returns phase_c
        mock_select_phase.return_value = ("phase_c", {"reason": "user_a_swipe_count_below_threshold"})
        mock_embedding.return_value = [0.3] * 1024

        # Search returns low scores — but no fallback should trigger since Phase C was used
        low_score_candidates = [_make_qdrant_candidate(n, 0.4 - i * 0.05) for i, n in enumerate(sample_names)]
        mock_search.return_value = low_score_candidates

        deck = generate_deck(couple, mode="best_match")

        assert deck.items.count() > 0
        # search_names called only once (no fallback for Phase C)
        assert mock_search.call_count == 1


class TestRelaxedDiversityConstraints:
    """Tests for relaxed diversity constraints when pool is sparse (Requirement 9.2)."""

    def test_relaxed_allows_more_same_letter(self):
        """When relaxed=True, more candidates with the same first letter are accepted."""
        # Create candidates all starting with 'A' and low rerank_score (< 0.5)
        # With normal constraints (max_per_letter=5 for deck_size=50), only 5 would pass
        # With relaxed (max_per_letter=10), more should pass
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(uuid.uuid4()),
                "score": 0.7,
                "rerank_score": 0.3,  # Below 0.5, so diversity constraints apply
                "payload": {
                    "canonical_name": f"A_name_{i}",
                    "origin_backgrounds": [f"Origin{i}"],
                    "age_style_category": f"style{i}",
                },
            }
            for i in range(60)
        ]

        # Normal constraints: max_per_letter = max(3, 50//10) = 5
        normal_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=False)
        # Relaxed constraints: max_per_letter = 5 * 2 = 10
        relaxed_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=True)

        # Relaxed should allow more candidates through
        assert len(relaxed_result) >= len(normal_result)

    def test_relaxed_allows_more_same_origin(self):
        """When relaxed=True, more candidates with the same origin are accepted."""
        # All candidates share the same origin with low rerank_score
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(uuid.uuid4()),
                "score": 0.7,
                "rerank_score": 0.3,  # Below 0.5
                "payload": {
                    "canonical_name": f"{chr(65 + i % 26)}_name_{i}",
                    "origin_backgrounds": ["Spanish"],
                    "age_style_category": f"style{i % 5}",
                },
            }
            for i in range(60)
        ]

        normal_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=False)
        relaxed_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=True)

        # Count how many with "Spanish" origin got through
        normal_spanish = sum(
            1 for c in normal_result if "Spanish" in c["payload"]["origin_backgrounds"]
        )
        relaxed_spanish = sum(
            1 for c in relaxed_result if "Spanish" in c["payload"]["origin_backgrounds"]
        )

        assert relaxed_spanish >= normal_spanish

    def test_relaxed_false_is_default_behavior(self):
        """Default (relaxed=False) preserves existing diversity constraint behavior."""
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(uuid.uuid4()),
                "score": 0.9 - i * 0.01,
                "rerank_score": 0.8,
                "payload": {
                    "canonical_name": f"Name{i}",
                    "origin_backgrounds": ["Spanish"],
                    "age_style_category": "classic",
                },
            }
            for i in range(60)
        ]

        result_default = _apply_diversity_constraints(candidates, deck_size=50)
        result_explicit = _apply_diversity_constraints(candidates, deck_size=50, relaxed=False)

        assert len(result_default) == len(result_explicit)

    def test_sparse_pool_detection_triggers_relaxed(self):
        """Integration: fewer than 10 candidates above 0.5 triggers relaxed constraints."""
        # This tests the sparse pool detection logic indirectly via _apply_diversity_constraints
        # When all candidates score below 0.5, the pool is sparse
        candidates = [
            {
                "point_id": str(uuid.uuid4()),
                "name_id": str(uuid.uuid4()),
                "score": 0.7,
                "rerank_score": 0.3,  # All below 0.5
                "payload": {
                    "canonical_name": f"A_name_{i}",
                    "origin_backgrounds": ["Spanish"],
                    "age_style_category": "classic",
                },
            }
            for i in range(60)
        ]

        # Verify sparse pool detection logic
        above_threshold_count = sum(1 for c in candidates if c.get("rerank_score", 0) > 0.5)
        assert above_threshold_count < 10  # Confirms sparse pool

        # With relaxed=True, all 50 should be selected (high-score bypass + doubled limits)
        relaxed_result = _apply_diversity_constraints(candidates, deck_size=50, relaxed=True)
        assert len(relaxed_result) == 50


def _make_cross_cultural_candidate(
    name: Name, score: float = 0.8, international_score: float = 0.6
) -> dict:
    """Helper to build a Qdrant candidate carrying an international_score payload field."""
    candidate = _make_qdrant_candidate(name, score)
    candidate["payload"]["international_score"] = international_score
    return candidate


class TestCrossCulturalMode:
    """Tests for the cross-cultural deck mode (Feature B)."""

    def test_vector_name_for_mode_maps_cross_cultural_and_defaults(self):
        """cross_cultural maps to the cross_cultural vector; all other modes use semantic."""
        assert _vector_name_for_mode(DeckMode.CROSS_CULTURAL) == "cross_cultural"
        assert _vector_name_for_mode(DeckMode.BEST_MATCH) == "semantic"
        assert _vector_name_for_mode(DeckMode.BRIDGE_NAMES) == "semantic"
        assert _vector_name_for_mode(DeckMode.MORE_LIKE_THIS) == "semantic"
        assert _vector_name_for_mode(DeckMode.WILDCARD) == "semantic"

    @patch("core.services.recommendations.search_names")
    @patch("core.services.qdrant_client._average_vectors")
    @patch("core.services.onboarding._get_liked_cross_cultural_vectors")
    def test_generate_deck_cross_cultural_mutual_likes_averages_vectors(
        self,
        mock_liked,
        mock_average,
        mock_search,
        couple_with_onboarding,
        sample_names,
    ):
        """Mutual-likes path averages cross_cultural vectors and searches that named vector."""
        couple, _, _ = couple_with_onboarding

        mock_liked.return_value = [[0.1] * 1024, [0.2] * 1024]
        mock_average.return_value = [0.15] * 1024
        candidates = [
            _make_cross_cultural_candidate(n, 0.9 - i * 0.1)
            for i, n in enumerate(sample_names)
        ]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="cross_cultural")

        assert deck.mode == "cross_cultural"
        assert deck.items.count() > 0
        # Mutual cross_cultural likes are fetched and averaged for the query embedding.
        mock_liked.assert_called_once_with(couple, mutual_only=True)
        mock_average.assert_called_once_with([[0.1] * 1024, [0.2] * 1024])
        # Every Qdrant search uses the cross_cultural named vector.
        assert mock_search.call_args_list
        assert all(
            call.kwargs.get("vector_name") == "cross_cultural"
            for call in mock_search.call_args_list
        )

    @patch("core.services.recommendations.search_names")
    @patch("core.services.embeddings.generate_embedding")
    @patch("core.services.onboarding._get_liked_cross_cultural_vectors")
    def test_generate_deck_cross_cultural_fallback_embeds_profile_text(
        self,
        mock_liked,
        mock_generate_embedding,
        mock_search,
        couple_with_onboarding,
        sample_names,
    ):
        """With no mutual cross_cultural likes, the deck falls back to embedding profile text."""
        couple, _, _ = couple_with_onboarding

        mock_liked.return_value = []
        mock_generate_embedding.return_value = [0.05] * 1024
        candidates = [
            _make_cross_cultural_candidate(n, 0.85 - i * 0.1)
            for i, n in enumerate(sample_names)
        ]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="cross_cultural")

        assert deck.mode == "cross_cultural"
        assert deck.items.count() > 0
        # Fallback embeds the couple profile text via generate_embedding.
        mock_generate_embedding.assert_called_once()
        # Search still targets the cross_cultural named vector.
        assert mock_search.call_args_list
        assert all(
            call.kwargs.get("vector_name") == "cross_cultural"
            for call in mock_search.call_args_list
        )

    def test_cross_cultural_adjustment_is_monotonic_in_international_score(self):
        # Feature: constellation-and-cross-cultural-mode, Property 8: Cross-cultural adjustment is monotonic
        """Higher international_score yields a higher final score for equal base inputs."""
        base = dict(
            mode=DeckMode.CROSS_CULTURAL,
            final=0.5,
            semantic=0.6,
            couple_overlap=0.4,
            filter_fit=0.3,
            bridge=0.2,
            novelty=0.1,
            diversity=0.1,
        )

        low = _apply_mode_score_adjustments(**base, payload={"international_score": 0.2})
        high = _apply_mode_score_adjustments(**base, payload={"international_score": 0.8})

        assert high > low
        # The base weighted formula's inputs are untouched; only an additive bonus is applied.
        assert high > base["final"]
        assert low > base["final"]

    def test_cross_cultural_adjustment_missing_score_is_neutral(self):
        # Feature: constellation-and-cross-cultural-mode, Property 7: Missing international_score is neutral
        """A missing or non-numeric international_score adds 0.0 and never raises."""
        base = dict(
            mode=DeckMode.CROSS_CULTURAL,
            final=0.5,
            semantic=0.6,
            couple_overlap=0.4,
            filter_fit=0.3,
            bridge=0.2,
            novelty=0.1,
            diversity=0.1,
        )

        # Payload present but no international_score key.
        assert _apply_mode_score_adjustments(**base, payload={}) == 0.5
        # No payload at all.
        assert _apply_mode_score_adjustments(**base, payload=None) == 0.5
        # Default payload argument omitted entirely.
        assert _apply_mode_score_adjustments(**base) == 0.5
        # Non-numeric value is treated as neutral.
        assert _apply_mode_score_adjustments(**base, payload={"international_score": "high"}) == 0.5

    def test_build_explanation_cross_cultural_references_usability(self):
        """The cross-cultural explanation references how many languages a name travels across."""
        payload = {
            "languages": ["en", "es", "fr"],
            "international_score": 0.6,
            "origin_backgrounds": ["Spanish", "French"],
            "age_style_category": "classic",
        }

        explanation = _build_explanation(payload, DeckMode.CROSS_CULTURAL)

        assert "Travels well" in explanation
        assert "3 languages" in explanation

    def test_build_explanation_cross_cultural_omits_framing_without_signals(self):
        """Without languages or an international_score, the neutral default template is used."""
        payload = {
            "origin_backgrounds": ["Spanish"],
            "age_style_category": "classic",
        }

        explanation = _build_explanation(payload, DeckMode.CROSS_CULTURAL)

        assert "Travels well" not in explanation
        assert "used across" in explanation


class TestSoundsLikeDeckMode:
    """Tests for the optional "Sounds Like" deck mode (phonetic_style vector)."""

    def test_vector_name_for_mode_routes_sounds_like(self):
        # Feature: phonetic-name-search, Property 8
        """sounds_like maps to phonetic_style; cross_cultural and the rest are unchanged.

        Property 8 (Vector-name routing): for any mode, ``_vector_name_for_mode``
        returns "phonetic_style" iff mode == SOUNDS_LIKE, "cross_cultural" iff
        CROSS_CULTURAL, else "semantic".
        """
        assert _vector_name_for_mode(DeckMode.SOUNDS_LIKE) == "phonetic_style"
        assert _vector_name_for_mode(DeckMode.CROSS_CULTURAL) == "cross_cultural"
        assert _vector_name_for_mode(DeckMode.BEST_MATCH) == "semantic"
        assert _vector_name_for_mode(DeckMode.BRIDGE_NAMES) == "semantic"
        assert _vector_name_for_mode(DeckMode.MORE_LIKE_THIS) == "semantic"
        assert _vector_name_for_mode(DeckMode.WILDCARD) == "semantic"

    @patch("core.services.recommendations.search_names")
    @patch("core.services.qdrant_client._average_vectors")
    @patch("core.services.onboarding._get_liked_phonetic_vectors")
    def test_generate_deck_sounds_like_mutual_likes_averages_vectors(
        self,
        mock_liked,
        mock_average,
        mock_search,
        couple_with_onboarding,
        sample_names,
    ):
        """Mutual-likes path averages phonetic_style vectors and searches that named vector."""
        couple, _, _ = couple_with_onboarding

        mock_liked.return_value = [[0.1] * 1024, [0.2] * 1024]
        mock_average.return_value = [0.15] * 1024
        candidates = [_make_qdrant_candidate(n, 0.9 - i * 0.1) for i, n in enumerate(sample_names)]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="sounds_like")

        assert deck.mode == "sounds_like"
        assert deck.items.count() > 0
        # Mutual phonetic_style likes are fetched and averaged for the query embedding.
        mock_liked.assert_called_once_with(couple, mutual_only=True)
        mock_average.assert_called_once_with([[0.1] * 1024, [0.2] * 1024])
        # Every Qdrant search uses the phonetic_style named vector.
        assert mock_search.call_args_list
        assert all(
            call.kwargs.get("vector_name") == "phonetic_style"
            for call in mock_search.call_args_list
        )

    @patch("core.services.recommendations.search_names")
    @patch("core.services.embeddings.generate_embedding")
    @patch("core.services.onboarding._get_liked_phonetic_vectors")
    def test_generate_deck_sounds_like_fallback_embeds_profile_text(
        self,
        mock_liked,
        mock_generate_embedding,
        mock_search,
        couple_with_onboarding,
        sample_names,
    ):
        """With no mutual phonetic likes, the deck falls back to embedding profile text."""
        couple, _, _ = couple_with_onboarding

        mock_liked.return_value = []
        mock_generate_embedding.return_value = [0.05] * 1024
        candidates = [_make_qdrant_candidate(n, 0.85 - i * 0.1) for i, n in enumerate(sample_names)]
        mock_search.return_value = candidates

        deck = generate_deck(couple, mode="sounds_like")

        assert deck.mode == "sounds_like"
        assert deck.items.count() > 0
        # Fallback embeds the couple profile text via generate_embedding.
        mock_generate_embedding.assert_called_once()
        # Search still targets the phonetic_style named vector.
        assert mock_search.call_args_list
        assert all(
            call.kwargs.get("vector_name") == "phonetic_style"
            for call in mock_search.call_args_list
        )

    def test_sounds_like_does_not_change_base_weights(self):
        """SOUNDS_LIKE adds no rerank bonus — the base weighted score is returned unchanged (Req 9.6)."""
        base = dict(
            mode=DeckMode.SOUNDS_LIKE,
            final=0.5,
            semantic=0.6,
            couple_overlap=0.4,
            filter_fit=0.3,
            bridge=0.2,
            novelty=0.1,
            diversity=0.1,
        )

        # No payload, empty payload, and a payload carrying an international_score
        # must all leave the base final score untouched for sounds_like.
        assert _apply_mode_score_adjustments(**base) == 0.5
        assert _apply_mode_score_adjustments(**base, payload={}) == 0.5
        assert _apply_mode_score_adjustments(**base, payload={"international_score": 0.8}) == 0.5
