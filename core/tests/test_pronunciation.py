"""Unit and property-based tests for the pronunciation audio service.

Covers ``core/services/pronunciation.py`` (the Pronunciation_Audio_Service):

- ``_build_ssml`` builds an IPA ``<phoneme>`` hint when a profile has IPA, plain
  SSML otherwise, and XML-escapes arbitrary name/IPA content.
- ``synthesize_pronunciation`` calls Polly with the neural engine/configured
  voice and returns the audio bytes; Polly errors propagate.
- ``store_audio``/``presign_audio_url`` round-trip (Property 5): a stored
  reference presigns to a non-empty URL; an empty reference yields ``None``.
- ``generate_pronunciations`` skip/force/per-name-error-isolation/critical-abort.

Amazon Polly and S3 are never called for real: the boto3 client factories
``_get_polly_client`` and ``_get_s3_client`` are patched to return ``MagicMock``s.
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings as django_settings
from django.db import DatabaseError
from django.test import override_settings
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import Name
from core.services.pronunciation import (
    AudioStats,
    _build_ssml,
    generate_pronunciations,
    presign_audio_url,
    store_audio,
    synthesize_pronunciation,
)

TEST_BUCKET = "babybase-pronunciation-audio-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_error(code: str = "AccessDenied", operation: str = "SynthesizeSpeech") -> ClientError:
    """Build a representative botocore ``ClientError`` for the given operation."""
    return ClientError(
        {"Error": {"Code": code, "Message": f"{code} for {operation}"}},
        operation,
    )


def _polly_response(audio: bytes = b"\x00\x01mp3") -> dict:
    """Build a Polly ``synthesize_speech`` response whose stream yields ``audio``."""
    stream = MagicMock()
    stream.read.return_value = audio
    return {"AudioStream": stream}


def _memory_name(*, display_name="Aiden", canonical_name="Aiden", phonetic_profile=None,
                 pronunciation_audio=None) -> Name:
    """Construct an unsaved in-memory ``Name`` carrying only the fields under test."""
    return Name(
        canonical_name=canonical_name,
        display_name=display_name,
        phonetic_profile=phonetic_profile if phonetic_profile is not None else {},
        pronunciation_audio=pronunciation_audio if pronunciation_audio is not None else {},
    )


def _create_name(canonical_name: str, *, pronunciation_audio: dict | None = None) -> Name:
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
        pronunciation_audio=pronunciation_audio if pronunciation_audio is not None else {},
    )


# ===========================================================================
# _build_ssml
# ===========================================================================


def test_build_ssml_with_ipa_wraps_phoneme():
    """A non-empty IPA produces an IPA ``<phoneme>`` wrapping the display name."""
    name = _memory_name(display_name="Aiden", phonetic_profile={"ipa": "ˈeɪdən"})

    ssml = _build_ssml(name)

    assert ssml == '<speak><phoneme alphabet="ipa" ph="ˈeɪdən">Aiden</phoneme></speak>'
    assert "ˈeɪdən" in ssml
    assert "Aiden" in ssml
    # Well-formed XML.
    ET.fromstring(ssml)


def test_build_ssml_without_profile_is_plain():
    """An empty/missing profile produces plain SSML with no ``<phoneme>``."""
    name = _memory_name(display_name="Sofia", phonetic_profile={})

    ssml = _build_ssml(name)

    assert ssml == "<speak>Sofia</speak>"
    assert "<phoneme" not in ssml
    ET.fromstring(ssml)


def test_build_ssml_with_profile_but_blank_ipa_is_plain():
    """A profile present but with a blank IPA falls back to plain SSML."""
    name = _memory_name(display_name="Mia", phonetic_profile={"ipa": "   ", "sounds_like": "soft"})

    ssml = _build_ssml(name)

    assert ssml == "<speak>Mia</speak>"
    assert "<phoneme" not in ssml


def test_build_ssml_escapes_special_characters_in_name():
    """A display name with ``&``/``<`` is XML-escaped, keeping the SSML well-formed."""
    name = _memory_name(display_name="Tom & <Jerry>", phonetic_profile={})

    ssml = _build_ssml(name)

    assert "&amp;" in ssml
    assert "&lt;" in ssml
    # The raw ampersand/angle bracket must not appear unescaped.
    assert "& " not in ssml
    assert "<Jerry" not in ssml
    # Still parseable.
    root = ET.fromstring(ssml)
    assert root.text == "Tom & <Jerry>"


def test_build_ssml_escapes_special_characters_in_ipa():
    """An IPA value containing markup characters is escaped in both attr and body."""
    name = _memory_name(display_name="A&B", phonetic_profile={"ipa": 'eɪ"&<'})

    ssml = _build_ssml(name)

    # Well-formed despite quotes/ampersands/angle brackets in the IPA and name.
    root = ET.fromstring(ssml)
    assert root.tag == "speak"
    phoneme = root[0]
    assert phoneme.tag == "phoneme"
    assert phoneme.attrib["alphabet"] == "ipa"
    assert phoneme.attrib["ph"] == 'eɪ"&<'
    assert phoneme.text == "A&B"


# ===========================================================================
# synthesize_pronunciation
# ===========================================================================


@patch("core.services.pronunciation._get_polly_client")
def test_synthesize_returns_audio_bytes_and_calls_polly_correctly(mock_get_polly):
    """Returns the AudioStream bytes and calls Polly with the expected parameters."""
    client = MagicMock()
    client.synthesize_speech.return_value = _polly_response(b"mp3-bytes")
    mock_get_polly.return_value = client

    name = _memory_name(display_name="Aiden", phonetic_profile={"ipa": "ˈeɪdən"})

    audio = synthesize_pronunciation(name)

    assert audio == b"mp3-bytes"
    client.synthesize_speech.assert_called_once()
    kwargs = client.synthesize_speech.call_args.kwargs
    assert kwargs["Engine"] == "neural"
    assert kwargs["VoiceId"] == django_settings.PRONUNCIATION_VOICE
    assert kwargs["OutputFormat"] == "mp3"
    assert kwargs["TextType"] == "ssml"
    assert kwargs["Text"] == _build_ssml(name)


@patch("core.services.pronunciation._get_polly_client")
def test_synthesize_reraises_client_error(mock_get_polly):
    """A Polly ``ClientError`` propagates out of ``synthesize_pronunciation``."""
    client = MagicMock()
    client.synthesize_speech.side_effect = _client_error()
    mock_get_polly.return_value = client

    with pytest.raises(ClientError):
        synthesize_pronunciation(_memory_name())


@patch("core.services.pronunciation._get_polly_client")
def test_synthesize_reraises_botocore_error(mock_get_polly):
    """A Polly ``BotoCoreError`` propagates out of ``synthesize_pronunciation``."""
    client = MagicMock()
    client.synthesize_speech.side_effect = BotoCoreError()
    mock_get_polly.return_value = client

    with pytest.raises(BotoCoreError):
        synthesize_pronunciation(_memory_name())


# ===========================================================================
# store_audio
# ===========================================================================


@pytest.mark.django_db
@override_settings(PRONUNCIATION_AUDIO_BUCKET=TEST_BUCKET)
@patch("core.services.pronunciation._get_s3_client")
def test_store_audio_puts_object_without_acl_and_returns_reference(mock_get_s3):
    """Puts an mp3 at the expected key without requiring object ACL permissions."""
    client = MagicMock()
    mock_get_s3.return_value = client

    name = _create_name("Aiden")
    audio = b"the-mp3-bytes"

    reference = store_audio(name, audio, "Joanna")

    expected_key = f"pronunciations/{name.pk}.mp3"
    client.put_object.assert_called_once()
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == TEST_BUCKET
    assert kwargs["Key"] == expected_key
    assert kwargs["Body"] == audio
    assert kwargs["ContentType"] == "audio/mpeg"
    assert "ACL" not in kwargs

    assert reference["bucket"] == TEST_BUCKET
    assert reference["key"] == expected_key
    assert reference["voice"] == "Joanna"
    assert reference["content_type"] == "audio/mpeg"
    assert reference["generated_at"]


@pytest.mark.django_db
@override_settings(PRONUNCIATION_AUDIO_BUCKET=TEST_BUCKET)
@patch("core.services.pronunciation._get_s3_client")
def test_store_audio_reraises_client_error(mock_get_s3):
    """An S3 ``ClientError`` propagates out of ``store_audio``."""
    client = MagicMock()
    client.put_object.side_effect = _client_error(operation="PutObject")
    mock_get_s3.return_value = client

    name = _create_name("Sofia")

    with pytest.raises(ClientError):
        store_audio(name, b"bytes", "Joanna")


# ===========================================================================
# Property 5: Audio reference round-trip
#
# For any stored pronunciation_audio reference, presign_audio_url returns a
# non-empty URL; for an empty reference it returns None without raising.
# ===========================================================================

# Non-empty bucket/key strings used to vary the stored reference contents.
_ref_str = st.text(min_size=1, max_size=60)

_reference_st = st.builds(
    lambda bucket, key, voice: {
        "bucket": bucket,
        "key": key,
        "voice": voice,
        "content_type": "audio/mpeg",
    },
    bucket=_ref_str,
    key=_ref_str,
    voice=st.text(max_size=20),
)


# Feature: phonetic-name-search, Property 5
@settings(max_examples=200)
@given(reference=_reference_st)
@patch("core.services.pronunciation._get_s3_client")
def test_presign_round_trip_returns_non_empty_url(mock_get_s3, reference):
    """
    Property 5 (non-empty reference): For any stored pronunciation_audio
    reference with a bucket and key, ``presign_audio_url`` returns the
    (non-empty) presigned URL produced by S3 without raising.

    Validates: Requirements 6.3, 7.1, 7.2
    """
    sentinel_url = "https://signed.example.com/pronunciations/object.mp3?sig=abc"
    client = MagicMock()
    client.generate_presigned_url.return_value = sentinel_url
    mock_get_s3.return_value = client

    name = _memory_name(pronunciation_audio=reference)

    url = presign_audio_url(name)

    assert url == sentinel_url
    assert url  # non-empty
    client.generate_presigned_url.assert_called_once()


# Feature: phonetic-name-search, Property 5
@patch("core.services.pronunciation._get_s3_client")
def test_presign_empty_reference_returns_none(mock_get_s3):
    """
    Property 5 (empty reference): An empty pronunciation_audio reference yields
    ``None`` without raising, and S3 is never asked to presign.

    Validates: Requirements 6.3, 7.2
    """
    client = MagicMock()
    mock_get_s3.return_value = client

    name = _memory_name(pronunciation_audio={})

    assert presign_audio_url(name) is None
    client.generate_presigned_url.assert_not_called()


@patch("core.services.pronunciation._get_s3_client")
def test_presign_reference_missing_bucket_or_key_returns_none(mock_get_s3):
    """A reference missing bucket or key presigns to ``None`` without raising."""
    client = MagicMock()
    mock_get_s3.return_value = client

    no_key = _memory_name(pronunciation_audio={"bucket": TEST_BUCKET})
    no_bucket = _memory_name(pronunciation_audio={"key": "pronunciations/x.mp3"})

    assert presign_audio_url(no_key) is None
    assert presign_audio_url(no_bucket) is None
    client.generate_presigned_url.assert_not_called()


# ===========================================================================
# generate_pronunciations
# ===========================================================================


@pytest.mark.django_db
@override_settings(PRONUNCIATION_AUDIO_BUCKET=TEST_BUCKET)
@patch("core.services.pronunciation._get_s3_client")
@patch("core.services.pronunciation._get_polly_client")
def test_generate_skips_existing_audio_without_force(mock_get_polly, mock_get_s3):
    """A name that already has audio is skipped (no Polly call) when force=False."""
    polly = MagicMock()
    s3 = MagicMock()
    mock_get_polly.return_value = polly
    mock_get_s3.return_value = s3

    existing = {
        "bucket": TEST_BUCKET,
        "key": "pronunciations/existing.mp3",
        "voice": "Joanna",
        "content_type": "audio/mpeg",
    }
    name = _create_name("Aiden", pronunciation_audio=existing)

    stats = generate_pronunciations([name], force=False)

    assert stats == AudioStats(processed=0, skipped=1, failed=0)
    polly.synthesize_speech.assert_not_called()
    s3.put_object.assert_not_called()

    name.refresh_from_db()
    assert name.pronunciation_audio == existing


@pytest.mark.django_db
@override_settings(PRONUNCIATION_AUDIO_BUCKET=TEST_BUCKET)
@patch("core.services.pronunciation._get_s3_client")
@patch("core.services.pronunciation._get_polly_client")
def test_generate_force_regenerates_existing_audio(mock_get_polly, mock_get_s3):
    """force=True regenerates audio even when a reference already exists."""
    polly = MagicMock()
    polly.synthesize_speech.return_value = _polly_response(b"fresh-mp3")
    s3 = MagicMock()
    mock_get_polly.return_value = polly
    mock_get_s3.return_value = s3

    stale = {
        "bucket": TEST_BUCKET,
        "key": "pronunciations/stale.mp3",
        "voice": "Joanna",
        "content_type": "audio/mpeg",
    }
    name = _create_name("Sofia", pronunciation_audio=stale)

    stats = generate_pronunciations([name], force=True)

    assert stats == AudioStats(processed=1, skipped=0, failed=0)
    polly.synthesize_speech.assert_called_once()
    s3.put_object.assert_called_once()

    name.refresh_from_db()
    assert name.pronunciation_audio["key"] == f"pronunciations/{name.pk}.mp3"
    assert name.pronunciation_audio["bucket"] == TEST_BUCKET
    assert name.pronunciation_audio["voice"] == django_settings.PRONUNCIATION_VOICE


@pytest.mark.django_db
@override_settings(PRONUNCIATION_AUDIO_BUCKET=TEST_BUCKET)
@patch("core.services.pronunciation._get_s3_client")
@patch("core.services.pronunciation._get_polly_client")
def test_generate_isolates_per_name_failures(mock_get_polly, mock_get_s3):
    """
    A batch with one Polly error, one S3 store error, and successes counts the
    failures, persists the successes, and keeps processing to the end of the
    batch (per-name error isolation).

    Validates: Requirements 6.6, 11.2
    """
    polly_error = _create_name("Pollyfail")
    s3_error = _create_name("Storefail")
    success_a = _create_name("Successa")
    success_b = _create_name("Successb")

    polly = MagicMock()
    # One call per name (none are skipped): first raises, the rest return audio.
    polly.synthesize_speech.side_effect = [
        _client_error(operation="SynthesizeSpeech"),  # polly_error
        _polly_response(b"a-s3err"),  # s3_error (synth ok, store fails)
        _polly_response(b"a-success-a"),  # success_a
        _polly_response(b"a-success-b"),  # success_b
    ]
    s3 = MagicMock()
    # put_object is only reached when synth succeeds: s3_error, success_a, success_b.
    s3.put_object.side_effect = [
        _client_error(operation="PutObject"),  # s3_error
        None,  # success_a
        None,  # success_b
    ]
    mock_get_polly.return_value = polly
    mock_get_s3.return_value = s3

    names = [polly_error, s3_error, success_a, success_b]
    stats = generate_pronunciations(names, force=False)

    assert stats == AudioStats(processed=2, skipped=0, failed=2)
    assert polly.synthesize_speech.call_count == 4
    assert s3.put_object.call_count == 3

    # Successful names were persisted with their own reference.
    success_a.refresh_from_db()
    success_b.refresh_from_db()
    assert success_a.pronunciation_audio["key"] == f"pronunciations/{success_a.pk}.mp3"
    assert success_b.pronunciation_audio["key"] == f"pronunciations/{success_b.pk}.mp3"

    # Failed names were left without stored audio.
    polly_error.refresh_from_db()
    s3_error.refresh_from_db()
    assert polly_error.pronunciation_audio == {}
    assert s3_error.pronunciation_audio == {}


@pytest.mark.django_db
@override_settings(PRONUNCIATION_AUDIO_BUCKET=TEST_BUCKET)
@patch("core.services.pronunciation._get_s3_client")
@patch("core.services.pronunciation._get_polly_client")
def test_generate_aborts_run_on_database_error(mock_get_polly, mock_get_s3):
    """
    A critical error while persisting the reference (e.g. DB connectivity) is not
    isolated as a per-name skip: it propagates and aborts the run.

    Validates: Requirements 6.7
    """
    polly = MagicMock()
    polly.synthesize_speech.return_value = _polly_response(b"mp3")
    s3 = MagicMock()
    mock_get_polly.return_value = polly
    mock_get_s3.return_value = s3

    name = _create_name("Aiden")

    with patch.object(name, "save", side_effect=DatabaseError("db down")):
        with pytest.raises(DatabaseError):
            generate_pronunciations([name], force=False)

    # The synthesize/store happened, but the run aborted on the save failure.
    polly.synthesize_speech.assert_called_once()
    s3.put_object.assert_called_once()
