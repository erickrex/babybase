"""Unit tests for relevance scoring service.

Tests each scoring signal independently with known inputs.
"""


from core.services.relevance import (
    bridge_score,
    compute_final_score,
    couple_overlap_score,
    diversity_score,
    explicit_filter_fit_score,
    novelty_score,
    semantic_fit_score,
)


class TestSemanticFitScore:
    """Tests for semantic_fit_score signal."""

    def test_normal_score_passthrough(self):
        """Normal score in [0, 1] passes through."""
        assert semantic_fit_score(0.85) == 0.85

    def test_none_returns_zero(self):
        """None input returns 0.0."""
        assert semantic_fit_score(None) == 0.0

    def test_negative_clamped_to_zero(self):
        """Negative score clamped to 0.0."""
        assert semantic_fit_score(-0.5) == 0.0

    def test_above_one_clamped(self):
        """Score > 1.0 clamped to 1.0."""
        assert semantic_fit_score(1.5) == 1.0

    def test_zero_score(self):
        """Zero score returns 0.0."""
        assert semantic_fit_score(0.0) == 0.0

    def test_invalid_type_returns_zero(self):
        """Non-numeric type returns 0.0."""
        assert semantic_fit_score("invalid") == 0.0


class TestCoupleOverlapScore:
    """Tests for couple_overlap_score signal."""

    def test_full_overlap_both_parents(self):
        """Name origins fully overlap with both parents' preferences."""
        candidate = {"origin_backgrounds": ["Spanish", "Russian"]}
        parent_a = {"preferred_backgrounds": ["Spanish"]}
        parent_b = {"preferred_backgrounds": ["Russian"]}

        score = couple_overlap_score(candidate, parent_a, parent_b)
        assert score == 1.0

    def test_partial_overlap(self):
        """Name origins partially overlap with parents."""
        candidate = {"origin_backgrounds": ["Spanish", "Greek"]}
        parent_a = {"preferred_backgrounds": ["Spanish", "German"]}
        parent_b = {"preferred_backgrounds": ["Russian"]}

        score = couple_overlap_score(candidate, parent_a, parent_b)
        # A overlap: 1/2 = 0.5, B overlap: 0/1 = 0.0, avg = 0.25
        assert score == 0.25

    def test_no_overlap(self):
        """No overlap between name and parents."""
        candidate = {"origin_backgrounds": ["Japanese"]}
        parent_a = {"preferred_backgrounds": ["Spanish"]}
        parent_b = {"preferred_backgrounds": ["Russian"]}

        score = couple_overlap_score(candidate, parent_a, parent_b)
        assert score == 0.0

    def test_null_candidate(self):
        """None candidate returns 0.0."""
        parent_a = {"preferred_backgrounds": ["Spanish"]}
        parent_b = {"preferred_backgrounds": ["Russian"]}
        assert couple_overlap_score(None, parent_a, parent_b) == 0.0

    def test_null_parents(self):
        """None parent profiles return 0.0."""
        candidate = {"origin_backgrounds": ["Spanish"]}
        assert couple_overlap_score(candidate, None, None) == 0.0

    def test_empty_origins(self):
        """Empty origin_backgrounds returns 0.0."""
        candidate = {"origin_backgrounds": []}
        parent_a = {"preferred_backgrounds": ["Spanish"]}
        parent_b = {"preferred_backgrounds": ["Russian"]}

        assert couple_overlap_score(candidate, parent_a, parent_b) == 0.0


class TestExplicitFilterFitScore:
    """Tests for explicit_filter_fit_score signal."""

    def test_all_match(self):
        """All preferences match perfectly."""
        candidate = {
            "length_category": "short",
            "age_style_category": "classic",
            "historical_significance_score": 0.9,
        }
        preferences = {
            "preferred_length": "short",
            "preferred_age": "old",
            "historical_importance": "high",
        }

        score = explicit_filter_fit_score(candidate, preferences)
        assert score == 1.0

    def test_length_any_always_matches(self):
        """preferred_length='any' always matches."""
        candidate = {"length_category": "long"}
        preferences = {"preferred_length": "any"}

        score = explicit_filter_fit_score(candidate, preferences)
        assert score == 1.0

    def test_null_candidate(self):
        """None candidate returns 0.0."""
        assert explicit_filter_fit_score(None, {"preferred_length": "short"}) == 0.0

    def test_null_preferences(self):
        """None preferences returns 0.0."""
        assert explicit_filter_fit_score({"length_category": "short"}, None) == 0.0

    def test_empty_dicts(self):
        """Empty dicts return 0.0."""
        assert explicit_filter_fit_score({}, {}) == 0.0


class TestBridgeScore:
    """Tests for bridge_score signal."""

    def test_perfect_bridge(self):
        """Name bridges both parents' backgrounds."""
        candidate = {
            "origin_backgrounds": ["Spanish", "Russian"],
            "languages": ["es", "ru", "de"],
        }
        parent_a_bg = ["Spanish"]
        parent_b_bg = ["Russian"]

        score = bridge_score(candidate, parent_a_bg, parent_b_bg, "DE")
        assert score == 1.0  # Perfect bridge + residence language match

    def test_partial_bridge(self):
        """Name matches only one parent."""
        candidate = {
            "origin_backgrounds": ["Spanish"],
            "languages": ["es"],
        }
        parent_a_bg = ["Spanish"]
        parent_b_bg = ["Russian"]

        score = bridge_score(candidate, parent_a_bg, parent_b_bg, None)
        assert 0.0 < score < 1.0

    def test_no_bridge(self):
        """Name doesn't match either parent."""
        candidate = {
            "origin_backgrounds": ["Japanese"],
            "languages": ["ja"],
        }
        parent_a_bg = ["Spanish"]
        parent_b_bg = ["Russian"]

        score = bridge_score(candidate, parent_a_bg, parent_b_bg, None)
        assert score == 0.0

    def test_null_candidate(self):
        """None candidate returns 0.0."""
        assert bridge_score(None, ["Spanish"], ["Russian"], "DE") == 0.0

    def test_empty_origins(self):
        """Empty origin_backgrounds returns 0.0."""
        candidate = {"origin_backgrounds": [], "languages": ["de"]}
        assert bridge_score(candidate, ["Spanish"], ["Russian"], "DE") == 0.0

    def test_residence_country_fit(self):
        """Name with residence country language gets bonus."""
        candidate = {
            "origin_backgrounds": ["German"],
            "languages": ["de", "en"],
        }
        # No parent backgrounds to test bridge, just residence
        score = bridge_score(candidate, [], [], "DE")
        # With empty parent backgrounds, only residence component counts
        assert score >= 0.0


class TestNoveltyScore:
    """Tests for novelty_score signal."""

    def test_all_new_origins(self):
        """Name with entirely new origins gets full novelty."""
        candidate = {"origin_backgrounds": ["Japanese", "Korean"]}
        seen = ["Spanish", "Russian"]

        score = novelty_score(candidate, seen)
        assert score == 1.0

    def test_all_seen_origins(self):
        """Name with all previously seen origins gets zero novelty."""
        candidate = {"origin_backgrounds": ["Spanish", "Russian"]}
        seen = ["Spanish", "Russian", "German"]

        score = novelty_score(candidate, seen)
        assert score == 0.0

    def test_partial_novelty(self):
        """Name with mix of new and seen origins gets partial score."""
        candidate = {"origin_backgrounds": ["Spanish", "Japanese"]}
        seen = ["Spanish", "Russian"]

        score = novelty_score(candidate, seen)
        assert score == 0.5  # 1 new out of 2

    def test_empty_seen_full_novelty(self):
        """First name in deck always gets full novelty."""
        candidate = {"origin_backgrounds": ["Spanish"]}
        score = novelty_score(candidate, [])
        assert score == 1.0

    def test_null_candidate(self):
        """None candidate returns 0.0."""
        assert novelty_score(None, ["Spanish"]) == 0.0

    def test_null_seen(self):
        """None seen origins = full novelty."""
        candidate = {"origin_backgrounds": ["Spanish"]}
        assert novelty_score(candidate, None) == 1.0


class TestDiversityScore:
    """Tests for diversity_score signal."""

    def test_first_name_full_diversity(self):
        """First name in deck gets full diversity score."""
        candidate = {
            "canonical_name": "Sofia",
            "origin_backgrounds": ["Spanish"],
            "age_style_category": "classic",
        }
        score = diversity_score(candidate, [])
        assert score == 1.0

    def test_same_letter_reduces_diversity(self):
        """Name with same first letter as existing deck gets lower score."""
        candidate = {
            "canonical_name": "Sofia",
            "origin_backgrounds": ["Spanish"],
            "age_style_category": "classic",
        }
        deck = [
            {
                "canonical_name": "Santiago",
                "origin_backgrounds": ["Spanish"],
                "age_style_category": "classic",
            }
        ]
        score = diversity_score(candidate, deck)
        assert score < 1.0

    def test_different_everything_high_diversity(self):
        """Name differing in letter, origin, and style gets high score."""
        candidate = {
            "canonical_name": "Kai",
            "origin_backgrounds": ["Japanese"],
            "age_style_category": "modern",
        }
        deck = [
            {
                "canonical_name": "Sofia",
                "origin_backgrounds": ["Spanish"],
                "age_style_category": "classic",
            }
        ]
        score = diversity_score(candidate, deck)
        assert score == 1.0

    def test_null_candidate(self):
        """None candidate returns 0.0."""
        assert diversity_score(None, [{"canonical_name": "Test"}]) == 0.0

    def test_null_deck(self):
        """None deck = full diversity."""
        candidate = {"canonical_name": "Test", "origin_backgrounds": ["Spanish"]}
        assert diversity_score(candidate, None) == 1.0

    def test_empty_existing_name_is_ignored_safely(self):
        """Empty canonical names in prior deck items do not raise."""
        candidate = {
            "canonical_name": "Nova",
            "origin_backgrounds": None,
            "age_style_category": None,
        }
        deck = [
            {"canonical_name": "", "origin_backgrounds": None, "age_style_category": None},
            {"canonical_name": "Nova", "origin_backgrounds": None, "age_style_category": None},
        ]

        score = diversity_score(candidate, deck)

        assert score == 0.5


class TestComputeFinalScore:
    """Tests for compute_final_score."""

    def test_all_zeros(self):
        """All zero signals = zero final score."""
        assert compute_final_score(0.0, 0.0, 0.0, 0.0, 0.0, 0.0) == 0.0

    def test_all_ones(self):
        """All max signals = 1.0 (weights sum to 1.0)."""
        result = compute_final_score(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        assert abs(result - 1.0) < 0.001

    def test_semantic_dominates(self):
        """Semantic signal has highest weight (0.35)."""
        # Only semantic = 1.0
        semantic_only = compute_final_score(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        # Only overlap = 1.0
        overlap_only = compute_final_score(0.0, 1.0, 0.0, 0.0, 0.0, 0.0)

        assert semantic_only > overlap_only

    def test_weights_sum_to_one(self):
        """Verify weights sum to 1.0."""
        from core.services.relevance import (
            W_BRIDGE,
            W_COUPLE_OVERLAP,
            W_DIVERSITY,
            W_FILTER_FIT,
            W_NOVELTY,
            W_SEMANTIC,
        )

        total = W_SEMANTIC + W_COUPLE_OVERLAP + W_FILTER_FIT + W_BRIDGE + W_NOVELTY + W_DIVERSITY
        assert abs(total - 1.0) < 0.001
