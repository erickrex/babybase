"""Phonetic profile generation service backed by Amazon Bedrock Nova.

Generates a structured phonetic profile (IPA, rhyme/ending, syllable count,
stress pattern, plain-language "sounds like" hint) for a name using the Bedrock
Runtime Converse API. The parsed profile is cached on ``Name.phonetic_profile``
so the LLM is only ever called once per name.

This service follows the project rules: business logic lives in ``core/services``,
it never returns DRF ``Response`` objects, all external calls are wrapped in
specific exception handling, logging uses ``%s`` interpolation, and credentials
and full request bodies are never logged.
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import DatabaseError

logger = logging.getLogger(__name__)

# Pinned Nova generation model id (default "amazon.nova-lite-v1:0").
NOVA_MODEL = settings.NOVA_MODEL_ID

# JSON-only instruction so Nova returns a parseable structured profile.
_SYSTEM_PROMPT = (
    "You are a phonetics expert. Respond with ONLY a JSON object with keys "
    "ipa, rhyme, syllables, stress, sounds_like. "
    "ipa is the IPA transcription of the name. rhyme is the rhyming ending or "
    "cluster. syllables is an integer count. stress describes the stress "
    "pattern. sounds_like is a short plain-language hint about how the name "
    "sounds. Do not include any text outside the JSON object."
)

# Required profile keys requested from Nova.
_PROFILE_KEYS = ("ipa", "rhyme", "syllables", "stress", "sounds_like")

# Inference configuration kept small: the structured profile is short.
_MAX_TOKENS = 512
_TEMPERATURE = 0.2


class PhoneticProfileError(Exception):
    """Raised when Nova output cannot be parsed into a valid phonetic profile."""


@dataclass
class EnrichmentStats:
    """Outcome counts for a single ``enrich_names`` run.

    ``processed`` counts names whose profile was generated and persisted this
    run, ``skipped`` counts names left untouched because they already had a
    cached profile (and ``force`` was not set), and ``failed`` counts names that
    hit a parse, storage, or Bedrock error and were left for a later run.
    """

    processed: int = 0
    skipped: int = 0
    failed: int = 0


def _get_bedrock_client():
    """Return a boto3 Bedrock Runtime client configured from Django settings.

    Mirrors ``embeddings._get_bedrock_client`` so Nova and Titan share the same
    region/credential resolution approach.
    """
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.AWS_BEDROCK_REGION,
    )


def _build_nova_request(name) -> dict:
    """Build the Bedrock Runtime Converse request for a single name.

    Uses a JSON-only system prompt and a user message that supplies the display
    name plus ``origin_backgrounds``/``languages`` as pronunciation context.
    Targets ``settings.NOVA_MODEL_ID``.
    """
    display_name = (getattr(name, "display_name", "") or getattr(name, "canonical_name", "") or "").strip()

    origins = getattr(name, "origin_backgrounds", None) or []
    languages = getattr(name, "languages", None) or []

    context_lines = [f'Provide a phonetic profile for the baby name "{display_name}".']
    if origins:
        context_lines.append(f"Origins: {', '.join(str(o) for o in origins)}.")
    if languages:
        context_lines.append(f"Languages: {', '.join(str(lang) for lang in languages)}.")
    user_text = " ".join(context_lines)

    return {
        "modelId": NOVA_MODEL,
        "system": [{"text": _SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": [{"text": user_text}]}],
        "inferenceConfig": {"maxTokens": _MAX_TOKENS, "temperature": _TEMPERATURE},
    }


def _extract_converse_text(response: dict) -> str:
    """Pull the assistant text out of a Converse API response.

    Returns the concatenated text blocks, or "" when the response has no text.
    """
    output = response.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    texts = [block["text"] for block in content if isinstance(block, dict) and block.get("text")]
    return "\n".join(texts).strip()


def _extract_json_object(raw_text: str) -> str:
    """Return the substring spanning the first ``{`` to the last ``}``.

    Tolerates models that wrap the JSON in prose or markdown code fences.
    Raises ``PhoneticProfileError`` when no object delimiters are present.
    """
    text = (raw_text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise PhoneticProfileError("Nova response did not contain a JSON object.")
    return text[start : end + 1]


def _coerce_syllables(value) -> int:
    """Coerce a syllable value to a non-negative int, defaulting to 0."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return count if count > 0 else 0


def _parse_nova_profile(raw_text: str) -> dict:
    """Extract and validate the phonetic profile JSON from Nova output.

    Coerces ``syllables`` to an int and requires non-empty ``ipa`` and
    ``sounds_like`` strings. Raises ``PhoneticProfileError`` on any malformed,
    non-object, or incomplete output rather than returning a partial profile.
    """
    json_blob = _extract_json_object(raw_text)
    try:
        parsed = json.loads(json_blob)
    except (ValueError, TypeError) as exc:
        raise PhoneticProfileError(f"Nova response was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise PhoneticProfileError("Nova response JSON was not an object.")

    ipa = str(parsed.get("ipa") or "").strip()
    sounds_like = str(parsed.get("sounds_like") or "").strip()
    if not ipa:
        raise PhoneticProfileError("Nova profile is missing a non-empty 'ipa'.")
    if not sounds_like:
        raise PhoneticProfileError("Nova profile is missing a non-empty 'sounds_like'.")

    return {
        "ipa": ipa,
        "rhyme": str(parsed.get("rhyme") or "").strip(),
        "syllables": _coerce_syllables(parsed.get("syllables")),
        "stress": str(parsed.get("stress") or "").strip(),
        "sounds_like": sounds_like,
    }


def generate_phonetic_profile(name) -> dict:
    """Invoke Nova for a single name and return a parsed, validated profile.

    Attaches ``model`` and ``generated_at`` to the parsed profile. Raises
    ``PhoneticProfileError`` on malformed/unparseable output and wraps Bedrock
    errors (``ClientError``/``BotoCoreError``) so the caller decides batch
    policy. Logs only the name parameter, never the request body or credentials.
    """
    request = _build_nova_request(name)
    client = _get_bedrock_client()

    try:
        response = client.converse(**request)
    except (ClientError, BotoCoreError):
        logger.warning("Nova invocation failed for name=%s", getattr(name, "display_name", ""))
        raise

    raw_text = _extract_converse_text(response)
    if not raw_text:
        raise PhoneticProfileError(
            f"Nova returned an empty response for name={getattr(name, 'display_name', '')!s}"
        )

    profile = _parse_nova_profile(raw_text)
    profile["model"] = NOVA_MODEL
    profile["generated_at"] = datetime.now(UTC).isoformat()
    return profile


def enrich_names(names: Iterable, *, force: bool = False) -> EnrichmentStats:
    """Generate and cache phonetic profiles for ``names`` with per-name isolation.

    For each ``Name``: skip it when it already has a non-empty ``phonetic_profile``
    and ``force`` is false (counted as skipped); otherwise call
    ``generate_phonetic_profile`` and persist the parsed profile to
    ``name.phonetic_profile``.

    Failures are isolated per name so a single bad name never aborts the batch:

    - A parse failure (``PhoneticProfileError``) is logged distinctly with ``%s``,
      the name's profile is left empty, and processing continues (Req 2.3, 11.1).
    - A storage failure while saving is logged distinctly from a parse failure
      with ``%s`` and processing continues (Req 2.4).
    - A Bedrock client/service error (``ClientError``/``BotoCoreError``) is caught
      specifically, logged with ``%s``, and processing continues (Req 2.5, 11.1).

    Returns an ``EnrichmentStats`` with processed/skipped/failed counts. This
    service returns data only and never returns DRF ``Response`` objects.
    """
    stats = EnrichmentStats()

    for name in names:
        if not force and getattr(name, "phonetic_profile", None):
            stats.skipped += 1
            continue

        display_name = getattr(name, "display_name", "") or getattr(name, "canonical_name", "")

        try:
            profile = generate_phonetic_profile(name)
        except PhoneticProfileError as exc:
            logger.warning("Phonetic profile parse failed for name=%s: %s", display_name, exc)
            stats.failed += 1
            continue
        except (ClientError, BotoCoreError) as exc:
            logger.warning("Nova invocation failed for name=%s: %s", display_name, exc)
            stats.failed += 1
            continue

        try:
            name.phonetic_profile = profile
            name.save(update_fields=["phonetic_profile"])
        except DatabaseError as exc:
            logger.warning("Phonetic profile storage failed for name=%s: %s", display_name, exc)
            stats.failed += 1
            continue

        stats.processed += 1

    return stats
