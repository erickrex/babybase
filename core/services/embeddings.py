"""Embedding generation service for name vectors."""

import logging

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"  # 1536 dimensions
MAX_BATCH_SIZE = 20


def _get_openai_client() -> OpenAI:
    """Return an OpenAI client configured from Django settings."""
    return OpenAI(api_key=settings.OPENAI_API_KEY)


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

    Template: "{canonical_name}. Variants: {variants}. Length: {length_category}."
    """
    variants = ", ".join(name.variants[:5]) if name.variants else name.canonical_name
    return f"{name.canonical_name}. Variants: {variants}. Length: {name.length_category}."


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
    """Generate a single embedding via OpenAI API."""
    client = _get_openai_client()
    try:
        response = client.embeddings.create(input=text, model=MODEL)
        return response.data[0].embedding
    except Exception:
        logger.exception("OpenAI embedding generation failed for text length=%d", len(text))
        raise


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in batches.

    Batches requests to OpenAI with max 20 texts per request for efficiency.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors in the same order as input texts.
    """
    client = _get_openai_client()
    all_embeddings: list[list[float]] = []

    logger.info(
        "Generating embeddings batch: %d texts in %d batches",
        len(texts), (len(texts) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE,
    )

    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i : i + MAX_BATCH_SIZE]
        try:
            response = client.embeddings.create(input=batch, model=MODEL)
            # Sort by index to maintain order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            all_embeddings.extend([item.embedding for item in sorted_data])
        except Exception:
            logger.exception("OpenAI batch embedding failed at offset=%d batch_size=%d", i, len(batch))
            raise

    return all_embeddings
