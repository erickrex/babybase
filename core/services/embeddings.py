"""Embedding generation service for name vectors."""

import json
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIM = 1024
MAX_BATCH_SIZE = 20


def _get_bedrock_client():
    """Return a boto3 Bedrock Runtime client configured from Django settings."""
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.AWS_BEDROCK_REGION,
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

    With an empty profile it falls back to a deterministic text derived from the
    name's available fields (``canonical_name`` + ``variants`` +
    ``length_category``), preserving the previous behavior.

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

    Preserves the previous behavior:
    "{canonical_name}. Variants: {variants}. Length: {length_category}."
    while guaranteeing a non-empty string even when field data is missing.
    """
    canonical_raw = getattr(name, "canonical_name", "") or ""
    base = canonical_raw if canonical_raw.strip() else "name"

    variants_list = getattr(name, "variants", None) or []
    variants = ", ".join(variants_list[:5]) if variants_list else base

    length_category = _phonetic_clean(getattr(name, "length_category", ""))

    return f"{base}. Variants: {variants}. Length: {length_category}."


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
