"""Unit and property-based tests for the phonetic embedding text builder.

Covers ``build_phonetic_text`` (the rewritten Phonetic_Embedding_Builder):
the text describes how a name *sounds*, built from the cached
``phonetic_profile`` when present, and falls back to a deterministic
sound-shape text when the profile is empty.

The function reads only ``Name`` attributes and performs no I/O, so these
tests construct in-memory (unsaved) ``Name`` instances and require no DB.
"""

import copy
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from django.db import DatabaseError
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import Name
from core.services.embeddings import (
    _build_phonetic_fallback_text,
    build_phonetic_text,
)
from core.services.phonetics import (
    NOVA_MODEL,
    PhoneticProfileError,
    _parse_nova_profile,
    enrich_names,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Text that is non-empty after trimming surrounding whitespace.
nonempty_text = st.text(min_size=1, max_size=40).filter(lambda t: t.strip())

length_category_st = st.sampled_from(["short", "medium", "long", ""])

variants_st = st.lists(st.text(min_size=1, max_size=20).filter(lambda t: t.strip()), max_size=8)

# Arbitrary (possibly malformed) values that can appear in a cached profile.
profile_value_st = st.one_of(
    st.none(),
    st.text(max_size=40),
    st.integers(),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
)

# Empty, partial, or malformed profiles (no guarantee of required keys).
partial_profile_st = st.dictionaries(
    keys=st.sampled_from(["ipa", "rhyme", "syllables", "stress", "sounds_like", "extra"]),
    values=profile_value_st,
    max_size=6,
)

# A well-formed profile with the required non-empty ``ipa`` and ``sounds_like``.
full_profile_st = st.fixed_dictionaries(
    {
        "ipa": nonempty_text,
        "sounds_like": nonempty_text,
        "rhyme": st.one_of(st.none(), nonempty_text),
        "syllables": st.one_of(st.none(), st.integers(min_value=0, max_value=8)),
        "stress": st.one_of(st.none(), nonempty_text),
    }
)

# Any profile shape: empty, partial/malformed, or full.
any_profile_st = st.one_of(st.just({}), partial_profile_st, full_profile_st)


def _make_name(canonical_name: str, variants, length_category: str, phonetic_profile: dict) -> Name:
    """Construct an unsaved in-memory ``Name`` with only the fields the builder reads."""
    return Name(
        canonical_name=canonical_name,
        display_name=canonical_name,
        variants=variants,
        length_category=length_category,
        phonetic_profile=phonetic_profile,
    )


def _name_strategy(profile_strategy):
    """Build an unsaved ``Name`` strategy using the given profile strategy."""
    return st.builds(
        _make_name,
        canonical_name=st.text(min_size=1, max_size=30).filter(lambda t: t.strip()),
        variants=variants_st,
        length_category=length_category_st,
        phonetic_profile=profile_strategy,
    )


# ---------------------------------------------------------------------------
# Property 1: Embedding text is always non-empty and offline
# ---------------------------------------------------------------------------


# Feature: phonetic-name-search, Property 1
@settings(max_examples=50)
@given(name=_name_strategy(any_profile_st))
@patch("core.services.embeddings._get_bedrock_client")
def test_phonetic_text_non_empty_and_offline(mock_get_client, name):
    """
    Property 1: For any Name (with or without a phonetic_profile, including
    empty/partial/malformed profiles), build_phonetic_text returns a non-empty
    string and performs no I/O (never reaches the Bedrock client).

    Validates: Requirements 4.2, 4.3, 4.4
    """
    result = build_phonetic_text(name)

    assert isinstance(result, str), "build_phonetic_text must return a string"
    assert len(result) > 0, "build_phonetic_text must return a non-empty string"
    assert result.strip(), "build_phonetic_text must return non-whitespace content"

    # No external/embedding I/O during text construction (Req 4.4).
    mock_get_client.assert_not_called()


# ---------------------------------------------------------------------------
# Property 2: Profile presence selects the source deterministically
# ---------------------------------------------------------------------------


# Feature: phonetic-name-search, Property 2
@settings(max_examples=50)
@given(name=_name_strategy(full_profile_st))
def test_profile_present_includes_ipa_and_sounds_like(name):
    """
    Property 2 (profile present): For any Name with a non-empty profile that
    contains the required keys, the text contains the IPA and sounds-like
    content, and the output is deterministic for the same input.

    Validates: Requirements 4.1, 4.2
    """
    result = build_phonetic_text(name)

    ipa = name.phonetic_profile["ipa"].strip()
    sounds_like = name.phonetic_profile["sounds_like"].strip()

    assert ipa in result, f"Expected IPA {ipa!r} in phonetic text"
    assert sounds_like in result, f"Expected sounds-like {sounds_like!r} in phonetic text"

    # Deterministic: same input -> same output.
    assert build_phonetic_text(name) == result


# Feature: phonetic-name-search, Property 2
@settings(max_examples=50)
@given(name=_name_strategy(st.just({})))
def test_empty_profile_equals_fallback(name):
    """
    Property 2 (empty profile): For any Name with an empty profile, the text
    equals the deterministic metadata fallback, and is deterministic for the
    same input.

    Validates: Requirements 4.1, 4.2
    """
    result = build_phonetic_text(name)
    expected = _build_phonetic_fallback_text(name)

    assert result == expected, "Empty profile must produce the deterministic fallback text"

    # Deterministic: same input -> same output.
    assert build_phonetic_text(name) == result


# ---------------------------------------------------------------------------
# Unit tests: concrete examples and edge cases
# ---------------------------------------------------------------------------


def test_full_profile_builds_sound_describing_text():
    """A complete profile produces the documented sound-describing text."""
    name = _make_name(
        canonical_name="Aiden",
        variants=["Aidan", "Ayden"],
        length_category="medium",
        phonetic_profile={
            "ipa": "ˈeɪdən",
            "rhyme": "-aden",
            "syllables": 2,
            "stress": "primary on first syllable",
            "sounds_like": "rhymes with Braden and Jayden; two beats, soft ending",
        },
    )

    text = build_phonetic_text(name)

    assert text == (
        "Aiden. Pronounced ˈeɪdən. Rhymes with -aden. 2 syllables. "
        "Stress: primary on first syllable. "
        "Sounds like: rhymes with Braden and Jayden; two beats, soft ending."
    )


def test_empty_profile_uses_metadata_fallback():
    """An empty profile falls back to sound-shape text without semantic variants."""
    name = _make_name(
        canonical_name="Sofia",
        variants=["Sofía", "Sofiya"],
        length_category="medium",
        phonetic_profile={},
    )

    text = build_phonetic_text(name)

    assert text == (
        "Sofia. Sound key: S100. Starts with: so. Ends with: fia. "
        "Vowel pattern: oia. Consonant pattern: sf. 2 syllables. Length: medium."
    )
    assert "Sofía" not in text
    assert "Sofiya" not in text


def test_fallback_does_not_embed_variant_family_names():
    """Fallback phonetic text must not pull semantic/etymological variants into sound search."""
    name = _make_name(
        canonical_name="Samuel",
        variants=["Samuele", "Samuël", "Samuil", "Shemuel", "Sam"],
        length_category="medium",
        phonetic_profile={},
    )

    text = build_phonetic_text(name)

    assert "Samuel" in text
    assert "Shemuel" not in text
    assert "Samuele" not in text
    assert "Variants" not in text
    assert "Sound key:" in text


def test_partial_profile_skips_missing_fields():
    """A partial profile renders only the fields that are present."""
    name = _make_name(
        canonical_name="Mia",
        variants=[],
        length_category="short",
        phonetic_profile={"ipa": "ˈmiːə", "sounds_like": "two soft beats"},
    )

    text = build_phonetic_text(name)

    assert text == "Mia. Pronounced ˈmiːə. Sounds like: two soft beats."
    assert "Rhymes with" not in text
    assert "Stress:" not in text


def test_single_syllable_is_singular():
    """A one-syllable count renders the singular noun."""
    name = _make_name(
        canonical_name="Max",
        variants=[],
        length_category="short",
        phonetic_profile={"ipa": "mæks", "syllables": 1, "sounds_like": "one sharp beat"},
    )

    text = build_phonetic_text(name)

    assert "1 syllable." in text
    assert "1 syllables." not in text


def test_missing_canonical_name_still_non_empty():
    """The fallback still returns a non-empty string with no field data."""
    name = _make_name(
        canonical_name="",
        variants=[],
        length_category="",
        phonetic_profile={},
    )

    text = build_phonetic_text(name)

    assert text == (
        "name. Sound key: N500. Starts with: na. Ends with: ame. "
        "Vowel pattern: ae. Consonant pattern: nm. 1 syllable. Length: ."
    )
    assert len(text) > 0


# ===========================================================================
# Phonetic enrichment service tests (Nova) — Properties 3 and 4
#
# These tests mock the Bedrock Runtime client so no real Nova calls are made.
# Property 4 covers `_parse_nova_profile` strictness; Property 3 covers
# `enrich_names` idempotency with force=False. Force regeneration and per-name
# failure isolation are covered by example-based tests.
# ===========================================================================

# Characters safe to embed inside a JSON string value without introducing
# object delimiters (`{`/`}`) that would confuse `_extract_json_object`, and
# without lone surrogates that break JSON round-tripping.
_no_brace_chars = st.characters(blacklist_characters="{}", blacklist_categories=("Cs",))
no_brace_text = st.text(alphabet=_no_brace_chars, max_size=40)
nonempty_no_brace_text = st.text(alphabet=_no_brace_chars, min_size=1, max_size=40).filter(
    lambda t: t.strip()
)

# A valid, parseable Nova profile payload (non-empty ipa + sounds_like).
VALID_PROFILE = {
    "ipa": "ˈeɪdən",
    "rhyme": "-aden",
    "syllables": 2,
    "stress": "primary on first syllable",
    "sounds_like": "rhymes with Braden and Jayden; two beats, soft ending",
}

# Sentinel used by the malformed-object strategy to mean "omit this key".
_OMIT = object()


# ---------------------------------------------------------------------------
# Bedrock Converse response helpers (shape consumed by _extract_converse_text)
# ---------------------------------------------------------------------------


def _nova_text_response(text: str) -> dict:
    """Build a Converse API response whose assistant message is ``text``."""
    return {"output": {"message": {"content": [{"text": text}]}}}


def _nova_response(profile: dict) -> dict:
    """Build a Converse API response whose assistant message is ``profile`` as JSON."""
    return _nova_text_response(json.dumps(profile))


def _client_error() -> ClientError:
    """A representative Bedrock ClientError (throttling)."""
    return ClientError(
        error_response={"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        operation_name="Converse",
    )


def _create_name(canonical_name: str, *, phonetic_profile: dict | None = None) -> Name:
    """Persist a minimal active Name following the existing test conventions."""
    return Name.objects.create(
        canonical_name=canonical_name,
        display_name=canonical_name,
        gender_usage=["girl"],
        origin_backgrounds=["Spanish"],
        languages=["es"],
        scripts=["Latin"],
        variants=[],
        length_category="short",
        age_style_category="classic",
        historical_significance_score=0.5,
        semantic_summary="A name.",
        active=True,
        phonetic_profile=phonetic_profile if phonetic_profile is not None else {},
    )


# ---------------------------------------------------------------------------
# Property 4 strategies: malformed (raise) vs. valid (parse) Nova outputs
# ---------------------------------------------------------------------------

# Strings that contain no extractable JSON object, or a JSON value that is not
# an object: all must be rejected by `_parse_nova_profile`.
_non_object_json = st.one_of(
    no_brace_text,  # arbitrary prose with no braces -> no extractable object
    st.builds(json.dumps, st.integers()),
    st.builds(json.dumps, st.floats(allow_nan=False, allow_infinity=False)),
    st.builds(json.dumps, st.booleans()),
    st.just("null"),
    st.builds(json.dumps, st.lists(st.one_of(st.integers(), st.booleans()), max_size=5)),
    st.builds(json.dumps, st.lists(nonempty_no_brace_text, max_size=5)),
    st.builds(json.dumps, nonempty_no_brace_text),
)


@st.composite
def _malformed_profile_json(draw):
    """A JSON object missing a non-empty ``ipa`` and/or ``sounds_like``.

    Optional keys (rhyme/stress/syllables) may be present; at least one of the
    two required fields is omitted or empty/whitespace-only, so the object must
    be rejected.
    """
    obj: dict = {}
    if draw(st.booleans()):
        obj["rhyme"] = draw(no_brace_text)
    if draw(st.booleans()):
        obj["stress"] = draw(no_brace_text)
    if draw(st.booleans()):
        obj["syllables"] = draw(st.integers(min_value=0, max_value=8))

    deficient = draw(st.sets(st.sampled_from(["ipa", "sounds_like"]), min_size=1, max_size=2))
    for key in ("ipa", "sounds_like"):
        if key in deficient:
            val = draw(st.sampled_from([_OMIT, "", "   ", "\t\n "]))
            if val is not _OMIT:
                obj[key] = val
        else:
            obj[key] = draw(nonempty_no_brace_text)

    return json.dumps(obj)


_malformed_or_non_object = st.one_of(_non_object_json, _malformed_profile_json())


@st.composite
def _valid_profile_obj(draw):
    """A profile object that must parse: non-empty ``ipa`` and ``sounds_like``."""
    obj = {
        "ipa": draw(nonempty_no_brace_text),
        "sounds_like": draw(nonempty_no_brace_text),
    }
    if draw(st.booleans()):
        obj["rhyme"] = draw(no_brace_text)
    if draw(st.booleans()):
        obj["stress"] = draw(no_brace_text)
    if draw(st.booleans()):
        obj["syllables"] = draw(
            st.one_of(
                st.integers(min_value=-3, max_value=12),
                st.integers(min_value=1, max_value=12).map(str),
                st.just("not-a-number"),
                st.none(),
            )
        )
    return obj


# ---------------------------------------------------------------------------
# Property 4: Parse strictness
# ---------------------------------------------------------------------------


# Feature: phonetic-name-search, Property 4
@settings(max_examples=50)
@given(raw=_malformed_or_non_object)
def test_parse_nova_profile_rejects_malformed_output(raw):
    """
    Property 4: For any Nova output string that is not a JSON object with
    non-empty ``ipa`` and ``sounds_like``, ``_parse_nova_profile`` raises
    ``PhoneticProfileError`` (it never silently returns a partial/empty profile).

    Validates: Requirements 2.3
    """
    with pytest.raises(PhoneticProfileError):
        _parse_nova_profile(raw)


# Feature: phonetic-name-search, Property 4
@settings(max_examples=50)
@given(obj=_valid_profile_obj())
def test_parse_nova_profile_accepts_valid_and_coerces_syllables(obj):
    """
    Property 4 (positive): Any JSON object with non-empty ``ipa`` and
    ``sounds_like`` parses successfully, with ``syllables`` always coerced to a
    non-negative int and the required fields preserved (stripped).

    Validates: Requirements 2.3
    """
    profile = _parse_nova_profile(json.dumps(obj))

    assert profile["ipa"] == str(obj["ipa"]).strip()
    assert profile["sounds_like"] == str(obj["sounds_like"]).strip()
    assert isinstance(profile["syllables"], int)
    assert profile["syllables"] >= 0
    # The strict parser only emits the five profile fields (no model/generated_at).
    assert set(profile) == {"ipa", "rhyme", "syllables", "stress", "sounds_like"}


# ---------------------------------------------------------------------------
# Property 4: example-based edge cases
# ---------------------------------------------------------------------------


def test_parse_nova_profile_tolerates_prose_and_code_fences():
    """The parser extracts the JSON object even when wrapped in prose/fences."""
    raw = "Sure! Here is the profile:\n```json\n" + json.dumps(VALID_PROFILE) + "\n```\nDone."

    profile = _parse_nova_profile(raw)

    assert profile["ipa"] == VALID_PROFILE["ipa"]
    assert profile["sounds_like"] == VALID_PROFILE["sounds_like"]
    assert profile["syllables"] == 2


def test_parse_nova_profile_coerces_numeric_string_syllables():
    """A numeric string syllable count is coerced to an int."""
    profile = _parse_nova_profile(json.dumps({**VALID_PROFILE, "syllables": "3"}))
    assert profile["syllables"] == 3


def test_parse_nova_profile_coerces_uncountable_syllables_to_zero():
    """Non-numeric, missing, or non-positive syllable values coerce to 0."""
    assert _parse_nova_profile(json.dumps({**VALID_PROFILE, "syllables": "lots"}))["syllables"] == 0
    assert _parse_nova_profile(json.dumps({**VALID_PROFILE, "syllables": -2}))["syllables"] == 0

    without_syllables = {k: v for k, v in VALID_PROFILE.items() if k != "syllables"}
    assert _parse_nova_profile(json.dumps(without_syllables))["syllables"] == 0


def test_parse_nova_profile_rejects_non_json_string():
    """A response with no JSON object is rejected."""
    with pytest.raises(PhoneticProfileError):
        _parse_nova_profile("the name sounds nice")


def test_parse_nova_profile_rejects_json_array():
    """A JSON array (non-object) is rejected."""
    with pytest.raises(PhoneticProfileError):
        _parse_nova_profile(json.dumps(["ipa", "sounds_like"]))


def test_parse_nova_profile_rejects_missing_ipa():
    """An object without ``ipa`` is rejected."""
    payload = {k: v for k, v in VALID_PROFILE.items() if k != "ipa"}
    with pytest.raises(PhoneticProfileError):
        _parse_nova_profile(json.dumps(payload))


def test_parse_nova_profile_rejects_empty_sounds_like():
    """An object with a blank ``sounds_like`` is rejected."""
    with pytest.raises(PhoneticProfileError):
        _parse_nova_profile(json.dumps({**VALID_PROFILE, "sounds_like": "   "}))


# ---------------------------------------------------------------------------
# Property 3: Enrichment idempotency
# ---------------------------------------------------------------------------


def _make_profiled_name(canonical_name: str, profile: dict) -> Name:
    """Construct an unsaved Name carrying a non-empty cached profile."""
    return Name(
        canonical_name=canonical_name,
        display_name=canonical_name,
        phonetic_profile=profile,
    )


_profiled_name_st = st.builds(
    _make_profiled_name,
    canonical_name=st.text(min_size=1, max_size=30).filter(lambda t: t.strip()),
    profile=full_profile_st,
)


# Feature: phonetic-name-search, Property 3
@settings(max_examples=25)
@given(names=st.lists(_profiled_name_st, min_size=1, max_size=8))
@patch("core.services.phonetics._get_bedrock_client")
def test_enrich_names_idempotent_with_existing_profiles(mock_get_client, names):
    """
    Property 3: For any set of names that already have non-empty profiles,
    ``enrich_names(..., force=False)`` performs zero Nova invocations and changes
    no profile. Every such name is reported as skipped.

    Validates: Requirements 3.2, 3.4, 5.5
    """
    before = [copy.deepcopy(n.phonetic_profile) for n in names]

    stats = enrich_names(names, force=False)

    # Zero Nova work: the Bedrock client is never even constructed.
    mock_get_client.assert_not_called()

    assert stats.processed == 0
    assert stats.failed == 0
    assert stats.skipped == len(names)

    # No profile was mutated.
    for name, original in zip(names, before, strict=True):
        assert name.phonetic_profile == original


# ---------------------------------------------------------------------------
# Force regeneration and per-name failure isolation (example-based, DB-backed)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("core.services.phonetics._get_bedrock_client")
def test_enrich_names_force_regenerates_existing_profile(mock_get_client):
    """``force=True`` regenerates and persists a profile even when one exists."""
    stale = {"ipa": "stale", "sounds_like": "stale hint", "syllables": 9}
    name = _create_name("Aiden", phonetic_profile=stale)

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.converse.return_value = _nova_response(VALID_PROFILE)

    stats = enrich_names([name], force=True)

    mock_client.converse.assert_called_once()
    assert stats.processed == 1
    assert stats.skipped == 0
    assert stats.failed == 0

    name.refresh_from_db()
    assert name.phonetic_profile["ipa"] == VALID_PROFILE["ipa"]
    assert name.phonetic_profile["sounds_like"] == VALID_PROFILE["sounds_like"]
    assert name.phonetic_profile["syllables"] == 2
    assert name.phonetic_profile["model"] == NOVA_MODEL
    assert "generated_at" in name.phonetic_profile


@pytest.mark.django_db
@patch("core.services.phonetics._get_bedrock_client")
def test_enrich_names_isolates_per_name_failures(mock_get_client):
    """
    A parse failure, a storage failure, and a Bedrock error each fail in
    isolation: the successful names are still generated and persisted, failures
    are counted, and processing continues to the end of the batch.

    Validates: Requirements 2.3, 2.4, 2.5, 11.1
    """
    parse_fail = _create_name("Parsefail")
    storage_fail = _create_name("Storagefail")
    bedrock_fail = _create_name("Bedrockfail")
    success_a = _create_name("Successa")
    success_b = _create_name("Successb")

    success_profile_a = {**VALID_PROFILE, "ipa": "suc-a", "sounds_like": "hint a"}
    success_profile_b = {**VALID_PROFILE, "ipa": "suc-b", "sounds_like": "hint b"}

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    # Processing order matches the list passed to enrich_names below.
    mock_client.converse.side_effect = [
        _nova_text_response("this is not json"),  # parse failure
        _nova_response(VALID_PROFILE),  # parses, but save will fail
        _client_error(),  # Bedrock client error
        _nova_response(success_profile_a),  # success
        _nova_response(success_profile_b),  # success
    ]

    names = [parse_fail, storage_fail, bedrock_fail, success_a, success_b]

    with patch.object(storage_fail, "save", side_effect=DatabaseError("db down")):
        stats = enrich_names(names, force=False)

    # Every name reached the Nova call (none were skipped).
    assert mock_client.converse.call_count == 5
    assert stats.processed == 2
    assert stats.failed == 3
    assert stats.skipped == 0

    # Successful names were persisted.
    success_a.refresh_from_db()
    success_b.refresh_from_db()
    assert success_a.phonetic_profile["ipa"] == "suc-a"
    assert success_b.phonetic_profile["ipa"] == "suc-b"

    # Failed names were left with an empty profile in the database.
    for failed in (parse_fail, storage_fail, bedrock_fail):
        failed.refresh_from_db()
        assert failed.phonetic_profile == {}


@pytest.mark.django_db
@patch("core.services.phonetics._get_bedrock_client")
def test_enrich_names_isolates_botocore_error(mock_get_client):
    """A ``BotoCoreError`` for one name does not stop the rest of the batch."""
    bad = _create_name("Boterr")
    good = _create_name("Goodname")

    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.converse.side_effect = [BotoCoreError(), _nova_response(VALID_PROFILE)]

    stats = enrich_names([bad, good], force=False)

    assert stats.processed == 1
    assert stats.failed == 1
    assert stats.skipped == 0

    good.refresh_from_db()
    assert good.phonetic_profile["ipa"] == VALID_PROFILE["ipa"]
    bad.refresh_from_db()
    assert bad.phonetic_profile == {}
