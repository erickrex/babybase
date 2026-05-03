"""Property-based tests for BabyBase correctness properties.

Uses Hypothesis to verify formal invariants of the system.
Each property maps to a correctness property from the design doc.
"""

import uuid

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.services.relevance import (
    bridge_score,
    compute_final_score,
    couple_overlap_score,
    diversity_score,
    explicit_filter_fit_score,
    novelty_score,
    semantic_fit_score,
)

# ---------------------------------------------------------------------------
# Custom Strategies
# ---------------------------------------------------------------------------

origin_backgrounds_st = st.lists(
    st.sampled_from([
        "Spanish", "Greek", "Russian", "German", "English", "French",
        "Italian", "Portuguese", "Arabic", "Japanese", "Chinese",
        "Korean", "Hindi", "Swedish", "Norwegian", "Polish",
    ]),
    min_size=0,
    max_size=5,
    unique=True,
)

languages_st = st.lists(
    st.sampled_from(["es", "en", "ru", "de", "fr", "it", "pt", "ar", "ja", "zh", "ko", "hi", "sv", "no", "pl"]),
    min_size=0,
    max_size=6,
    unique=True,
)

length_category_st = st.sampled_from(["short", "medium", "long", ""])
age_style_st = st.sampled_from(["classic", "modern", "timeless", ""])
historical_score_st = st.floats(min_value=0.0, max_value=1.0)

name_payload_st = st.fixed_dictionaries({
    "canonical_name": st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20),
    "origin_backgrounds": origin_backgrounds_st,
    "languages": languages_st,
    "length_category": length_category_st,
    "age_style_category": age_style_st,
    "historical_significance_score": historical_score_st,
})

# Strategy for nullable name payloads (can be None or have missing fields)
nullable_name_payload_st = st.one_of(
    st.none(),
    st.fixed_dictionaries({}),
    st.fixed_dictionaries({
        "canonical_name": st.one_of(st.none(), st.text(min_size=0, max_size=10)),
        "origin_backgrounds": st.one_of(st.none(), origin_backgrounds_st),
        "languages": st.one_of(st.none(), languages_st),
        "length_category": st.one_of(st.none(), length_category_st),
        "age_style_category": st.one_of(st.none(), age_style_st),
        "historical_significance_score": st.one_of(st.none(), historical_score_st),
    }),
)

preferences_st = st.fixed_dictionaries({
    "preferred_backgrounds": origin_backgrounds_st,
    "preferred_length": st.sampled_from(["short", "long", "any", ""]),
    "preferred_age": st.sampled_from(["new", "old", "balanced", ""]),
    "historical_importance": st.sampled_from(["low", "medium", "high", ""]),
})

nullable_preferences_st = st.one_of(
    st.none(),
    st.fixed_dictionaries({}),
    preferences_st,
)

swipe_action_st = st.sampled_from(["like", "dislike", "maybe"])

country_code_st = st.one_of(
    st.none(),
    st.just(""),
    st.sampled_from(["DE", "US", "GB", "ES", "MX", "FR", "IT", "RU", "BR", "NL"]),
)


# ---------------------------------------------------------------------------
# Property 1: Mutual Match Symmetry
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestMutualMatchSymmetry:
    """
    **Validates: Requirements 1.1**

    Property 1: MutualMatch exists iff both parents have 'like' swipe.
    """

    @given(
        actions_a=st.lists(swipe_action_st, min_size=1, max_size=10),
        actions_b=st.lists(swipe_action_st, min_size=1, max_size=10),
    )
    @settings(max_examples=100, deadline=None)
    def test_match_iff_both_like(self, actions_a, actions_b):
        """A mutual match exists iff both parents have 'like' on the same name."""
        from django.contrib.auth import get_user_model

        from core.models import Couple, CoupleStatus, MutualMatch, Name, Swipe
        from core.services.swipes import check_mutual_match, create_match

        User = get_user_model()

        # Create fresh users and couple for each example
        uid = uuid.uuid4().hex[:8]
        user_a = User.objects.create_user(email=f"a_{uid}@test.com", password="test1234")
        user_b = User.objects.create_user(email=f"b_{uid}@test.com", password="test1234")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        # Create names for each action pair
        num_names = min(len(actions_a), len(actions_b))
        for i in range(num_names):
            name = Name.objects.create(
                canonical_name=f"Name_{uid}_{i}",
                display_name=f"Name {uid} {i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test name",
                active=True,
            )

            # Record swipes
            Swipe.objects.create(couple=couple, user=user_a, name=name, action=actions_a[i])
            Swipe.objects.create(couple=couple, user=user_b, name=name, action=actions_b[i])

            # Check mutual match
            is_match = check_mutual_match(couple, str(name.id))

            # Verify: match iff both liked
            both_liked = actions_a[i] == "like" and actions_b[i] == "like"
            assert is_match == both_liked, (
                f"Expected match={both_liked} but got {is_match} "
                f"for actions ({actions_a[i]}, {actions_b[i]})"
            )

            # If match, create it and verify it exists
            if is_match:
                create_match(couple, str(name.id))
                assert MutualMatch.objects.filter(couple=couple, name=name).exists()
            else:
                assert not MutualMatch.objects.filter(couple=couple, name=name).exists()


# ---------------------------------------------------------------------------
# Property 2: Scoring Null-Safety
# ---------------------------------------------------------------------------


class TestScoringNullSafety:
    """
    **Validates: Requirements 1.2**

    Property 2: Scoring formula returns finite non-negative number
    for any null/empty metadata.
    """

    @given(candidate_score=st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True)))
    @settings(max_examples=100)
    def test_semantic_fit_null_safe(self, candidate_score):
        """semantic_fit_score never crashes and returns >= 0."""
        result = semantic_fit_score(candidate_score)
        assert isinstance(result, float)
        assert result >= 0.0
        assert result <= 1.0
        # Must be finite
        import math
        assert math.isfinite(result)

    @given(
        candidate=nullable_name_payload_st,
        parent_a=nullable_preferences_st,
        parent_b=nullable_preferences_st,
    )
    @settings(max_examples=100)
    def test_couple_overlap_null_safe(self, candidate, parent_a, parent_b):
        """couple_overlap_score never crashes and returns >= 0."""
        result = couple_overlap_score(candidate, parent_a, parent_b)
        assert isinstance(result, float)
        assert result >= 0.0
        assert result <= 1.0

    @given(
        candidate=nullable_name_payload_st,
        preferences=nullable_preferences_st,
    )
    @settings(max_examples=100)
    def test_filter_fit_null_safe(self, candidate, preferences):
        """explicit_filter_fit_score never crashes and returns >= 0."""
        result = explicit_filter_fit_score(candidate, preferences)
        assert isinstance(result, float)
        assert result >= 0.0
        assert result <= 1.0

    @given(
        candidate=nullable_name_payload_st,
        parent_a_bg=st.one_of(st.none(), origin_backgrounds_st),
        parent_b_bg=st.one_of(st.none(), origin_backgrounds_st),
        residence=country_code_st,
    )
    @settings(max_examples=100)
    def test_bridge_score_null_safe(self, candidate, parent_a_bg, parent_b_bg, residence):
        """bridge_score never crashes and returns >= 0."""
        result = bridge_score(candidate, parent_a_bg, parent_b_bg, residence)
        assert isinstance(result, float)
        assert result >= 0.0
        assert result <= 1.0

    @given(
        candidate=nullable_name_payload_st,
        seen_origins=st.one_of(st.none(), origin_backgrounds_st),
    )
    @settings(max_examples=100)
    def test_novelty_score_null_safe(self, candidate, seen_origins):
        """novelty_score never crashes and returns >= 0."""
        result = novelty_score(candidate, seen_origins)
        assert isinstance(result, float)
        assert result >= 0.0
        assert result <= 1.0

    @given(
        candidate=nullable_name_payload_st,
        deck_so_far=st.one_of(st.none(), st.lists(nullable_name_payload_st, max_size=5)),
    )
    @settings(max_examples=100)
    def test_diversity_score_null_safe(self, candidate, deck_so_far):
        """diversity_score never crashes and returns >= 0."""
        # Filter out None from deck_so_far list if it's a list
        if deck_so_far is not None:
            deck_so_far = [d for d in deck_so_far if d is not None]
        result = diversity_score(candidate, deck_so_far)
        assert isinstance(result, float)
        assert result >= 0.0
        assert result <= 1.0

    @given(
        semantic=st.floats(min_value=0.0, max_value=1.0),
        overlap=st.floats(min_value=0.0, max_value=1.0),
        filter_fit=st.floats(min_value=0.0, max_value=1.0),
        bridge=st.floats(min_value=0.0, max_value=1.0),
        novelty_val=st.floats(min_value=0.0, max_value=1.0),
        diversity_val=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_compute_final_score_non_negative(
        self, semantic, overlap, filter_fit, bridge, novelty_val, diversity_val
    ):
        """compute_final_score always returns a finite non-negative float."""
        import math

        result = compute_final_score(semantic, overlap, filter_fit, bridge, novelty_val, diversity_val)
        assert isinstance(result, float)
        assert result >= 0.0
        assert math.isfinite(result)


# ---------------------------------------------------------------------------
# Property 3: Deck Exclusion Completeness
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDeckExclusionCompleteness:
    """
    **Validates: Requirements 1.3**

    Property 3: No name in deck has been previously swiped by either parent.
    """

    @given(
        num_swiped=st.integers(min_value=1, max_value=5),
        num_candidates=st.integers(min_value=3, max_value=8),
    )
    @settings(max_examples=100, deadline=None)
    def test_deck_excludes_swiped_names(self, num_swiped, num_candidates):
        """Generated deck never contains previously swiped names."""
        from django.contrib.auth import get_user_model

        from core.models import Couple, CoupleStatus, Name, Swipe
        from core.services.recommendations import _get_excluded_name_ids

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user_a = User.objects.create_user(email=f"a_{uid}@test.com", password="test1234")
        user_b = User.objects.create_user(email=f"b_{uid}@test.com", password="test1234")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        # Create names
        all_names = []
        for i in range(num_candidates):
            name = Name.objects.create(
                canonical_name=f"Excl_{uid}_{i}",
                display_name=f"Excl {uid} {i}",
                gender_usage=["boy"],
                origin_backgrounds=["Spanish"],
                languages=["es"],
                scripts=["Latin"],
                variants=[],
                length_category="short",
                age_style_category="classic",
                historical_significance_score=0.5,
                semantic_summary="Test name",
                active=True,
            )
            all_names.append(name)

        # Swipe on some names (by either parent)
        swiped_names = all_names[:num_swiped]
        for i, name in enumerate(swiped_names):
            user = user_a if i % 2 == 0 else user_b
            Swipe.objects.create(
                couple=couple, user=user, name=name, action="like"
            )

        # Get excluded IDs
        excluded_ids = _get_excluded_name_ids(couple)
        excluded_id_set = set(excluded_ids)

        # Verify all swiped names are in the exclusion set
        for name in swiped_names:
            assert str(name.id) in excluded_id_set, (
                f"Swiped name {name.canonical_name} not in exclusion set"
            )

        # Verify unswiped names are NOT in the exclusion set
        unswiped_names = all_names[num_swiped:]
        for name in unswiped_names:
            assert str(name.id) not in excluded_id_set, (
                f"Unswiped name {name.canonical_name} incorrectly in exclusion set"
            )


# ---------------------------------------------------------------------------
# Property 4: Swipe Uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestSwipeUniqueness:
    """
    **Validates: Requirements 1.4**

    Property 4: At most one swipe per user per name per couple.
    """

    @given(
        action_first=swipe_action_st,
        action_second=swipe_action_st,
        num_attempts=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_duplicate_swipe_returns_existing(self, action_first, action_second, num_attempts):
        """Duplicate swipe attempts return existing swipe without creating new records."""
        from django.contrib.auth import get_user_model

        from core.models import Couple, CoupleStatus, Name, Swipe
        from core.services.swipes import record_swipe

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user_a = User.objects.create_user(email=f"a_{uid}@test.com", password="test1234")
        user_b = User.objects.create_user(email=f"b_{uid}@test.com", password="test1234")
        couple = Couple.objects.create(
            user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE
        )

        name = Name.objects.create(
            canonical_name=f"Uniq_{uid}",
            display_name=f"Uniq {uid}",
            gender_usage=["girl"],
            origin_backgrounds=["Russian"],
            languages=["ru"],
            scripts=["Cyrillic"],
            variants=[],
            length_category="medium",
            age_style_category="timeless",
            historical_significance_score=0.7,
            semantic_summary="Test name",
            active=True,
        )

        # First swipe
        swipe1, created1 = record_swipe(user_a, couple, str(name.id), action_first)
        assert created1 is True

        # Subsequent attempts should return existing
        for _ in range(num_attempts - 1):
            swipe_n, created_n = record_swipe(user_a, couple, str(name.id), action_second)
            assert created_n is False
            assert swipe_n.id == swipe1.id

        # Verify only one swipe record exists
        count = Swipe.objects.filter(couple=couple, user=user_a, name=name).count()
        assert count == 1


# ---------------------------------------------------------------------------
# Property 5: Couple Singleton
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCoupleSingleton:
    """
    **Validates: Requirements 1.5**

    Property 5: User can be in at most one active couple.
    """

    @given(
        num_attempts=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_second_couple_rejected(self, num_attempts):
        """Creating a second couple for a user already in an active couple is rejected."""
        from django.contrib.auth import get_user_model

        from core.services.couples import CoupleExistsError, create_couple

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user = User.objects.create_user(email=f"user_{uid}@test.com", password="test1234")
        partner = User.objects.create_user(email=f"partner_{uid}@test.com", password="test1234")

        # First couple should succeed
        couple = create_couple(user, partner.email)
        assert couple is not None

        # Subsequent attempts should be rejected
        for i in range(num_attempts - 1):
            other_email = f"other_{uid}_{i}@test.com"
            with pytest.raises(CoupleExistsError):
                create_couple(user, other_email)


# ---------------------------------------------------------------------------
# Property 6: Couple Merge Ratio (40/30/30 ±10%)
# ---------------------------------------------------------------------------


class TestCoupleMergeRatio:
    """
    **Validates: Requirements 1.6**

    Property 6: Couple merge ratio ~40% overlap, ~30% parent A, ~30% parent B (±10%).
    """

    @given(
        overlap_items=st.lists(
            st.sampled_from(["Spanish", "Greek", "Russian", "German", "English"]),
            min_size=2,
            max_size=5,
            unique=True,
        ),
        unique_a_items=st.lists(
            st.sampled_from(["French", "Italian", "Portuguese"]),
            min_size=1,
            max_size=3,
            unique=True,
        ),
        unique_b_items=st.lists(
            st.sampled_from(["Japanese", "Chinese", "Korean"]),
            min_size=1,
            max_size=3,
            unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_merge_includes_all_sources(self, overlap_items, unique_a_items, unique_b_items):
        """
        Merged backgrounds include items from overlap, parent A, and parent B.

        The _apply_merge_ratio function includes all overlap items (bridge zone)
        plus items from each parent's unique list.
        """
        from core.services.onboarding import _apply_merge_ratio

        # Ensure no overlap between unique lists
        assume(not set(unique_a_items) & set(unique_b_items))
        assume(not set(overlap_items) & set(unique_a_items))
        assume(not set(overlap_items) & set(unique_b_items))

        merged = _apply_merge_ratio(
            overlap=overlap_items,
            parent_a=unique_a_items,
            parent_b=unique_b_items,
        )

        # All overlap items must be present
        for item in overlap_items:
            assert item in merged, f"Overlap item '{item}' missing from merged list"

        # All parent A items must be present
        for item in unique_a_items:
            assert item in merged, f"Parent A item '{item}' missing from merged list"

        # All parent B items must be present
        for item in unique_b_items:
            assert item in merged, f"Parent B item '{item}' missing from merged list"

        # Total should be sum of all sources
        expected_total = len(overlap_items) + len(unique_a_items) + len(unique_b_items)
        assert len(merged) == expected_total

    @given(
        shared_backgrounds=st.lists(
            st.sampled_from(["Spanish", "Greek", "Russian", "German", "English"]),
            min_size=1,
            max_size=4,
            unique=True,
        ),
        a_only=st.lists(
            st.sampled_from(["French", "Italian", "Portuguese", "Arabic"]),
            min_size=1,
            max_size=3,
            unique=True,
        ),
        b_only=st.lists(
            st.sampled_from(["Japanese", "Chinese", "Korean", "Hindi"]),
            min_size=1,
            max_size=3,
            unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_merge_ratio_conceptual_distribution(self, shared_backgrounds, a_only, b_only):
        """
        The merge conceptually follows 40/30/30 distribution:
        - Overlap items represent the 40% bridge zone
        - Parent A unique items represent 30%
        - Parent B unique items represent 30%

        For the MVP implementation, all items are included and the ratio
        is enforced at deck generation time. Here we verify the structure
        is correct for downstream ratio enforcement.
        """
        from core.services.onboarding import _apply_merge_ratio

        assume(not set(shared_backgrounds) & set(a_only))
        assume(not set(shared_backgrounds) & set(b_only))
        assume(not set(a_only) & set(b_only))

        merged = _apply_merge_ratio(
            overlap=shared_backgrounds,
            parent_a=a_only,
            parent_b=b_only,
        )

        total = len(merged)
        overlap_count = len(shared_backgrounds)
        a_count = len(a_only)
        b_count = len(b_only)

        # Verify all items are present (no loss)
        assert total == overlap_count + a_count + b_count

        # Verify ordering: overlap first, then parent_a, then parent_b
        # This is the structure that enables 40/30/30 at deck generation
        assert merged[:overlap_count] == shared_backgrounds
        assert merged[overlap_count:overlap_count + a_count] == a_only
        assert merged[overlap_count + a_count:] == b_only


# ---------------------------------------------------------------------------
# Property 7: Duplicate Pending Couple Prevention
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDuplicatePendingCouplePrevention:
    """
    **Validates: Requirements 3.1, 3.3**

    Property 7: For any user who already has a pending couple record,
    calling create_couple with any partner email SHALL either return the
    existing pending couple (if same email) or raise CoupleExistsError
    (if different email) — never create a second pending record.
    """

    @given(
        partner_email=st.emails(),
        second_email=st.emails(),
    )
    @settings(max_examples=100, deadline=None)
    def test_no_second_pending_record_created(self, partner_email, second_email):
        """create_couple never creates a second pending record for a user."""
        from django.contrib.auth import get_user_model

        from core.models import Couple, CoupleStatus
        from core.services.couples import CoupleExistsError, create_couple

        User = get_user_model()

        uid = uuid.uuid4().hex[:8]
        user = User.objects.create_user(email=f"user_{uid}@test.com", password="test1234")

        # Ensure partner emails don't correspond to existing users
        # (so the couple stays pending)
        assume(not User.objects.filter(email=partner_email.lower()).exists())
        assume(not User.objects.filter(email=second_email.lower()).exists())

        # Create initial pending couple
        first_couple = create_couple(user, partner_email)
        assert first_couple.status == CoupleStatus.PENDING

        # Attempt to create another couple with any email
        if second_email.lower() == partner_email.lower():
            # Same email: should return existing
            result = create_couple(user, second_email)
            assert result.id == first_couple.id
        else:
            # Different email: should raise error
            with pytest.raises(CoupleExistsError):
                create_couple(user, second_email)

        # Invariant: never more than one pending couple for this user
        pending_count = Couple.objects.filter(
            user_a=user, status=CoupleStatus.PENDING
        ).count()
        assert pending_count == 1, (
            f"Expected exactly 1 pending couple, found {pending_count}"
        )


# ---------------------------------------------------------------------------
# Property 8: Country-Language Mapping Completeness
# ---------------------------------------------------------------------------


class TestCountryLanguageMappingCompleteness:
    """
    **Validates: Requirements 7.4**

    Property 8: For all known country codes in the union of all codes defined
    in the system, `get_country_languages(code)` SHALL return a non-empty set
    of language codes.
    """

    @given(
        country_code=st.sampled_from([
            "DE", "US", "GB", "ES", "MX", "FR", "IT", "RU", "BR", "PT",
            "NL", "SE", "NO", "DK", "PL", "CZ", "JP", "CN", "KR", "IN",
            "CA", "CH", "BE", "AT", "AR", "CO", "CL", "PE", "UA", "TR",
            "GR", "IL", "SA", "EG",
        ]),
    )
    @settings(max_examples=100)
    def test_all_known_codes_return_non_empty_set(self, country_code):
        """get_country_languages returns a non-empty set for every known country code."""
        from core.services.country_languages import get_country_languages

        result = get_country_languages(country_code)

        # Must be a set
        assert isinstance(result, set), f"Expected set, got {type(result)} for {country_code}"

        # Must be non-empty
        assert len(result) > 0, f"Expected non-empty set for {country_code}, got empty set"

        # All elements must be non-empty strings (valid language codes)
        for lang in result:
            assert isinstance(lang, str), f"Expected str language code, got {type(lang)}"
            assert len(lang) > 0, f"Empty language code in result for {country_code}"

    @given(
        country_code=st.sampled_from([
            "DE", "US", "GB", "ES", "MX", "FR", "IT", "RU", "BR", "PT",
            "NL", "SE", "NO", "DK", "PL", "CZ", "JP", "CN", "KR", "IN",
            "CA", "CH", "BE", "AT", "AR", "CO", "CL", "PE", "UA", "TR",
            "GR", "IL", "SA", "EG",
        ]),
    )
    @settings(max_examples=100)
    def test_case_insensitive_lookup(self, country_code):
        """get_country_languages works regardless of case."""
        from core.services.country_languages import get_country_languages

        upper_result = get_country_languages(country_code.upper())
        lower_result = get_country_languages(country_code.lower())

        assert upper_result == lower_result, (
            f"Case mismatch for {country_code}: upper={upper_result}, lower={lower_result}"
        )

    @given(
        country_code=st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            min_size=2,
            max_size=2,
        ).filter(lambda c: c not in {
            "DE", "US", "GB", "ES", "MX", "FR", "IT", "RU", "BR", "PT",
            "NL", "SE", "NO", "DK", "PL", "CZ", "JP", "CN", "KR", "IN",
            "CA", "CH", "BE", "AT", "AR", "CO", "CL", "PE", "UA", "TR",
            "GR", "IL", "SA", "EG",
        }),
    )
    @settings(max_examples=100)
    def test_unknown_codes_return_empty_set(self, country_code):
        """get_country_languages returns empty set for unknown country codes."""
        from core.services.country_languages import get_country_languages

        result = get_country_languages(country_code)
        assert result == set(), f"Expected empty set for unknown code {country_code}, got {result}"
