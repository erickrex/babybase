"""Pronunciation audio service backed by Amazon Polly and S3.

Synthesizes spoken pronunciation audio for a name with Amazon Polly (neural
voice), stores the resulting mp3 privately in S3, and produces a time-limited
presigned GET URL for serving the audio to the frontend.

The phonetic profile cached on ``Name.phonetic_profile`` is used to build SSML
with an IPA ``<phoneme>`` hint when available so Polly pronounces the name more
accurately; otherwise plain SSML is used.

This service follows the project rules: business logic lives in ``core/services``,
it never returns DRF ``Response`` objects, all external calls are wrapped in
specific exception handling, logging uses ``%s`` interpolation, and credentials
and full request bodies are never logged.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

# Polly output format and the content type recorded for the stored object.
_OUTPUT_FORMAT = "mp3"
_CONTENT_TYPE = "audio/mpeg"

# S3 key prefix for stored pronunciation audio objects.
_KEY_PREFIX = "pronunciations"


@dataclass
class AudioStats:
    """Outcome counts for a single ``generate_pronunciations`` run.

    ``processed`` counts names whose audio was synthesized, stored, and persisted
    this run, ``skipped`` counts names left untouched because they already had
    stored audio (and ``force`` was not set), and ``failed`` counts names that hit
    a per-name Polly/S3 error and were skipped for a later run. Mirrors
    ``phonetics.EnrichmentStats``.
    """

    processed: int = 0
    skipped: int = 0
    failed: int = 0


def _get_polly_client():
    """Return a boto3 Polly client configured from Django settings.

    Mirrors ``embeddings._get_bedrock_client`` so Polly shares the same
    region/credential resolution approach as the other AWS integrations.
    """
    return boto3.client(
        "polly",
        region_name=settings.AWS_BEDROCK_REGION,
    )


def _get_s3_client():
    """Return a boto3 S3 client configured from Django settings.

    Mirrors ``embeddings._get_bedrock_client`` for consistent region/credential
    resolution.
    """
    return boto3.client(
        "s3",
        region_name=settings.AWS_BEDROCK_REGION,
    )


def _spoken_name(name) -> str:
    """Return the human-spoken name text, preferring ``display_name``.

    Falls back to ``canonical_name`` and finally to a non-empty placeholder so
    SSML construction always has something to speak.
    """
    spoken = (getattr(name, "display_name", "") or getattr(name, "canonical_name", "") or "").strip()
    return spoken or "name"


def _build_ssml(name) -> str:
    """Build SSML for Polly from the cached phonetic profile when possible.

    When the name's ``phonetic_profile`` contains a non-empty ``ipa`` value the
    SSML wraps the spoken name in an IPA ``<phoneme>`` element::

        <speak><phoneme alphabet="ipa" ph="ˈeɪdən">Aiden</phoneme></speak>

    Otherwise it returns plain SSML::

        <speak>Aiden</speak>

    Both the spoken text and the ``ph`` attribute value are XML-escaped so the
    SSML stays well-formed for arbitrary name/IPA content.
    """
    spoken = escape(_spoken_name(name))

    profile = getattr(name, "phonetic_profile", None)
    ipa = ""
    if isinstance(profile, dict):
        ipa = str(profile.get("ipa") or "").strip()

    if ipa:
        ph = escape(ipa, {'"': "&quot;"})
        return f'<speak><phoneme alphabet="ipa" ph="{ph}">{spoken}</phoneme></speak>'
    return f"<speak>{spoken}</speak>"


def synthesize_pronunciation(name) -> bytes:
    """Synthesize pronunciation audio for ``name`` via Amazon Polly.

    Calls Polly ``synthesize_speech`` with the neural engine, the configured
    ``settings.PRONUNCIATION_VOICE`` voice, mp3 output, and SSML built from the
    name's phonetic profile (IPA ``<phoneme>`` hint when present, else plain).
    Returns the raw mp3 bytes.

    Wraps Polly ``ClientError``/``BotoCoreError`` so the caller decides batch
    policy. Logs only the name parameter, never the request body or credentials.
    """
    ssml = _build_ssml(name)
    client = _get_polly_client()

    try:
        response = client.synthesize_speech(
            Engine="neural",
            VoiceId=settings.PRONUNCIATION_VOICE,
            OutputFormat=_OUTPUT_FORMAT,
            TextType="ssml",
            Text=ssml,
        )
        audio_stream = response["AudioStream"]
        return audio_stream.read()
    except (ClientError, BotoCoreError):
        logger.warning("Polly synthesis failed for name=%s", _spoken_name(name))
        raise


def store_audio(name, audio: bytes, voice: str) -> dict:
    """Store pronunciation ``audio`` for ``name`` privately in S3.

    Puts the mp3 bytes to ``settings.PRONUNCIATION_AUDIO_BUCKET`` at key
    ``pronunciations/<name_id>.mp3`` with an ``audio/mpeg`` content type. The
    bucket blocks public access; audio is served via a presigned URL, never made
    public.

    Returns the reference dict persisted to ``Name.pronunciation_audio``::

        {
            "bucket": "...",
            "key": "pronunciations/<name_id>.mp3",
            "voice": "Joanna",
            "content_type": "audio/mpeg",
            "generated_at": "<UTC ISO timestamp>",
        }

    Wraps S3 ``ClientError``/``BotoCoreError`` so the caller decides batch policy.
    Logs only the name parameter, never the audio body or credentials.
    """
    bucket = settings.PRONUNCIATION_AUDIO_BUCKET
    key = f"{_KEY_PREFIX}/{name.pk}.mp3"
    client = _get_s3_client()

    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=audio,
            ContentType=_CONTENT_TYPE,
        )
    except (ClientError, BotoCoreError):
        logger.warning("S3 audio storage failed for name=%s", _spoken_name(name))
        raise

    return {
        "bucket": bucket,
        "key": key,
        "voice": voice,
        "content_type": _CONTENT_TYPE,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def presign_audio_url(name) -> str | None:
    """Return a time-limited presigned GET URL for ``name``'s stored audio.

    Returns ``None`` (without raising) when the name has no stored
    ``pronunciation_audio`` reference. Otherwise generates a presigned
    ``get_object`` URL valid for ``settings.PRONUNCIATION_URL_TTL_SECONDS``
    using the stored bucket/key.

    S3 errors are caught and logged with ``%s`` and ``None`` is returned so
    serializers never crash when audio cannot be presigned. Never logs
    credentials.
    """
    reference = getattr(name, "pronunciation_audio", None)
    if not isinstance(reference, dict) or not reference:
        return None

    bucket = reference.get("bucket")
    key = reference.get("key")
    if not bucket or not key:
        return None

    client = _get_s3_client()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=settings.PRONUNCIATION_URL_TTL_SECONDS,
        )
    except (ClientError, BotoCoreError):
        logger.warning("Presigning audio URL failed for name=%s", _spoken_name(name))
        return None


def generate_pronunciations(names: Iterable, *, force: bool = False) -> AudioStats:
    """Synthesize, store, and cache pronunciation audio for ``names``.

    For each ``Name``: skip it when it already has a non-empty
    ``pronunciation_audio`` reference and ``force`` is false (counted as
    skipped); otherwise synthesize audio via Polly, store it privately in S3,
    and persist the returned reference to ``name.pronunciation_audio``.

    Failure handling distinguishes per-name AWS failures from critical run
    failures:

    - Per-name Polly/S3 errors (``ClientError``/``BotoCoreError``) are caught,
      logged with ``%s`` (only the name and error), the name is skipped, and
      processing continues (Req 6.6, 11.2).
    - A critical error such as a database failure while persisting the reference
      is NOT swallowed as a per-name skip; it propagates out of this function and
      aborts the run rather than continuing (Req 6.7).

    Uses ``settings.PRONUNCIATION_VOICE`` as the voice. Never logs credentials,
    audio bytes, or request/response bodies. Returns an ``AudioStats`` with
    processed/skipped/failed counts; never returns a DRF ``Response``.
    """
    stats = AudioStats()
    voice = settings.PRONUNCIATION_VOICE

    for name in names:
        if not force and getattr(name, "pronunciation_audio", None):
            stats.skipped += 1
            continue

        spoken = _spoken_name(name)

        try:
            audio = synthesize_pronunciation(name)
            reference = store_audio(name, audio, voice)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Pronunciation generation failed for name=%s: %s", spoken, exc)
            stats.failed += 1
            continue

        # A persistence failure (e.g. DB connectivity) is a critical error: do
        # not isolate it as a per-name skip. Letting DatabaseError propagate
        # aborts the run rather than silently continuing (Req 6.7).
        name.pronunciation_audio = reference
        name.save(update_fields=["pronunciation_audio"])
        stats.processed += 1

    return stats
