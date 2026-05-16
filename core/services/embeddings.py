"""Embedding generation service for name vectors."""

import json
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

MODEL = "amazon.nova-embed-text-v1"
EMBEDDING_DIM = 1024
MAX_BATCH_SIZE = 20


def _get_bedrock_client():
    """Return a boto3 Bedrock Runtime client configured from Django settings."""
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.AWS_BEDROCK_REGION,
    )


def validate_embedding_dimension(embedding: list[float], *, context: str = "embedding") -> list[float]:
    """Validate that an embedding matches the configured Nova Embed dimension."""
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
    """Generate a single 1024-dim embedding via Bedrock Nova Embed."""
    client = _get_bedrock_client()
    request_body = json.dumps({"inputText": text})
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
            request_body = json.dumps({"inputText": text})
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
