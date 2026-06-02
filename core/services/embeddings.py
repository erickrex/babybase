"""Embedding generation service for name vectors."""

import json
import logging
import unicodedata

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIM = 1024
MAX_BATCH_SIZE = 20

# Fail fast instead of hanging under the frontend's 30s request deadline.
# A stalled cold-start embedding call was surfacing to users as a generic
# "Failed to load deck"; bounded timeouts + a few retries make transient
# Bedrock hiccups recover quickly rather than blocking the new-user path.
_BEDROCK_TIMEOUT_CONFIG = Config(
    connect_timeout=getattr(settings, "BEDROCK_CONNECT_TIMEOUT_SECONDS", 5),
    read_timeout=getattr(settings, "BEDROCK_READ_TIMEOUT_SECONDS", 8),
    retries={"max_attempts": 3, "mode": "adaptive"},
)


def _get_bedrock_client():
    """Return a boto3 Bedrock Runtime client configured from Django settings."""
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.AWS_BEDROCK_REGION,
        config=_BEDROCK_TIMEOUT_CONFIG,
    )


def validate_embedding_dimension(embedding: list[float], *, context: str = "embedding") -> list[float]:
    """Validate that an embedding matches the configured Titan Embed V2 dimension."""
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"{context} must be {EMBEDDING_DIM} dimensions, got {len(embedding)}.")
    return embedding


def build_semantic_text(name) -> str:
    """
    Build text input for the `semantic` named vector.

    Template: "{canonical_name}. {semantic_summary}. Origin: {origins}. Style: {age_style_category}.
    Historical significance: {level}."
    """
    significance = (
        "high"
        if name.historical_significance_score > 0.7
        else ("moderate" if name.historical_significance_score > 0.3 else "low")
    )
    origins = ", ".join(name.origin_backgrounds) if name.origin_backgrounds else "unknown"
    return (
        f"{name.canonical_name}. {name.semantic_summary}. "
        f"Origin: {origins}. Style: {name.age_style_category}. "
        f"Historical significance: {significance}."
    )


def build_phonetic_text(name) -> str:
    """
    Build text input for the `phonetic_style` named vector.

    The text describes how the name *sounds* so Titan clusters names by sound
    rather than by metadata.

    With a non-empty ``phonetic_profile`` the text is built from the cached
    profile fields (``ipa``, ``rhyme``, ``syllables``, ``stress``,
    ``sounds_like``), e.g.::

        "Aiden. Pronounced ˈeɪdən. Rhymes with -aden. 2 syllables. "
        "Stress: primary on first syllable. Sounds like: rhymes with Braden..."

    With an empty profile it falls back to a deterministic sound-shape text
    derived only from the written name (no origins, meanings, or variants), so
    the phonetic vector does not collapse back toward semantic family clusters.

    Pure and offline: reads only ``name`` attributes, never invokes Nova or any
    external service, never raises, and always returns a non-empty string.
    """
    profile = getattr(name, "phonetic_profile", None)
    if isinstance(profile, dict) and profile:
        text = _build_phonetic_text_from_profile(name, profile)
        if text:
            return text
    return _build_phonetic_fallback_text(name)


def _phonetic_clean(value) -> str:
    """Coerce an arbitrary profile value to a trimmed string (``None`` -> "")."""
    if value is None:
        return ""
    return str(value).strip()


def _format_syllables(value) -> str:
    """Render the syllable count as a phrase, or "" when not a positive int."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return ""
    if count <= 0:
        return ""
    unit = "syllable" if count == 1 else "syllables"
    return f"{count} {unit}."


def _build_phonetic_text_from_profile(name, profile: dict) -> str:
    """Build sound-describing text from a cached phonetic profile.

    Tolerates missing or malformed fields by skipping them; partial profiles
    still produce useful text.
    """
    parts: list[str] = []

    # Embed the canonical name verbatim (matching the semantic/cross-cultural
    # builders) so the name always appears unaltered in the embedding text.
    canonical_raw = getattr(name, "canonical_name", "") or ""
    if canonical_raw.strip():
        parts.append(f"{canonical_raw}.")

    ipa = _phonetic_clean(profile.get("ipa"))
    if ipa:
        parts.append(f"Pronounced {ipa}.")

    rhyme = _phonetic_clean(profile.get("rhyme"))
    if rhyme:
        parts.append(f"Rhymes with {rhyme}.")

    syllable_text = _format_syllables(profile.get("syllables"))
    if syllable_text:
        parts.append(syllable_text)

    stress = _phonetic_clean(profile.get("stress"))
    if stress:
        parts.append(f"Stress: {stress}.")

    sounds_like = _phonetic_clean(profile.get("sounds_like"))
    if sounds_like:
        parts.append(f"Sounds like: {sounds_like}.")

    return " ".join(parts).strip()


def _build_phonetic_fallback_text(name) -> str:
    """Deterministic, offline fallback when no phonetic profile is cached.

    Uses spelling-derived sound-shape features rather than variants/origins.
    Variants often encode etymological families (for example Samuel/Shemuel),
    which makes the fallback behave like semantic search instead of phonetic
    search when Nova enrichment has not been run.
    """
    canonical_raw = getattr(name, "canonical_name", "") or ""
    base = canonical_raw if canonical_raw.strip() else "name"

    normalized = _normalize_name_for_sound(base)
    length_category = _phonetic_clean(getattr(name, "length_category", ""))
    syllables = _estimate_syllables(normalized)

    return (
        f"{base}. "
        f"Sound key: {_soundex_key(normalized)}. "
        f"Starts with: {_first_sound(normalized)}. "
        f"Ends with: {_ending_sound(normalized)}. "
        f"Vowel pattern: {_vowel_pattern(normalized)}. "
        f"Consonant pattern: {_consonant_pattern(normalized)}. "
        f"{syllables} {'syllable' if syllables == 1 else 'syllables'}. "
        f"Length: {length_category}."
    )


def _normalize_name_for_sound(value: str) -> str:
    """Return lowercase ASCII letters for deterministic spelling-derived features."""
    folded = unicodedata.normalize("NFKD", value)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    letters = [char.lower() for char in ascii_text if char.isalpha()]
    return "".join(letters) or "name"


def _first_sound(value: str) -> str:
    return value[:2] if len(value) >= 2 else value


def _ending_sound(value: str) -> str:
    if len(value) <= 3:
        return value
    return value[-3:]


def _vowel_pattern(value: str) -> str:
    vowels = [char for char in value if char in "aeiouy"]
    return "".join(vowels) or "none"


def _consonant_pattern(value: str) -> str:
    consonants = [char for char in value if char not in "aeiouy"]
    return "".join(consonants) or "none"


def _estimate_syllables(value: str) -> int:
    groups = 0
    previous_was_vowel = False
    for char in value:
        is_vowel = char in "aeiouy"
        if is_vowel and not previous_was_vowel:
            groups += 1
        previous_was_vowel = is_vowel

    if value.endswith("e") and groups > 1 and not value.endswith(("le", "ue")):
        groups -= 1
    return max(groups, 1)


def _soundex_key(value: str) -> str:
    """Small Soundex-style key to group rough English pronunciation shapes."""
    codes = {
        **dict.fromkeys("bfpv", "1"),
        **dict.fromkeys("cgjkqsxz", "2"),
        **dict.fromkeys("dt", "3"),
        "l": "4",
        **dict.fromkeys("mn", "5"),
        "r": "6",
    }
    first = value[0].upper()
    encoded = []
    previous = codes.get(value[0], "")
    for char in value[1:]:
        code = codes.get(char, "")
        if code and code != previous:
            encoded.append(code)
        previous = code
    return (first + "".join(encoded) + "000")[:4]


def build_cross_cultural_text(name) -> str:
    """
    Build text input for the `cross_cultural` named vector.

    Template: "{canonical_name}. Languages: {languages}. Scripts: {scripts}.
    Variants: {variants}. International usability: {level}."
    """
    languages = ", ".join(name.languages) if name.languages else "unknown"
    scripts = ", ".join(name.scripts) if name.scripts else "Latin"
    variants = ", ".join(name.variants[:5]) if name.variants else name.canonical_name
    usability = "high" if len(name.languages or []) > 2 else "moderate"
    return (
        f"{name.canonical_name}. "
        f"Languages: {languages}. Scripts: {scripts}. "
        f"Variants: {variants}. "
        f"International usability: {usability}."
    )


def generate_embedding(text: str) -> list[float]:
    """Generate a single 1024-dim embedding via Bedrock Titan Embed V2."""
    client = _get_bedrock_client()
    request_body = json.dumps({"inputText": text, "dimensions": EMBEDDING_DIM, "normalize": True})
    try:
        response = client.invoke_model(
            body=request_body,
            modelId=MODEL,
            accept="application/json",
            contentType="application/json",
        )
        result = json.loads(response["body"].read())
        return validate_embedding_dimension(result["embedding"], context="Bedrock embedding")
    except (ClientError, BotoCoreError, ValueError):
        logger.exception("Bedrock embedding failed for text length=%d", len(text))
        raise


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts, one invoke_model call per text.

    Processes texts in chunks of MAX_BATCH_SIZE (20) for logging and error isolation.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors in the same order as input texts.
    """
    client = _get_bedrock_client()
    all_embeddings: list[list[float]] = []

    num_batches = (len(texts) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
    logger.info(
        "Generating embeddings batch: %d texts in %d batches",
        len(texts), num_batches,
    )

    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i : i + MAX_BATCH_SIZE]
        for batch_offset, text in enumerate(batch):
            request_body = json.dumps({"inputText": text, "dimensions": EMBEDDING_DIM, "normalize": True})
            try:
                response = client.invoke_model(
                    body=request_body,
                    modelId=MODEL,
                    accept="application/json",
                    contentType="application/json",
                )
                result = json.loads(response["body"].read())
                all_embeddings.append(
                    validate_embedding_dimension(
                        result["embedding"],
                        context=f"Bedrock embedding at offset {i + batch_offset}",
                    )
                )
            except (ClientError, BotoCoreError, ValueError):
                logger.exception(
                    "Bedrock batch embedding failed at offset=%d batch_size=%d",
                    i, len(batch),
                )
                raise

    return all_embeddings
