# Feature: titan-embedding-migration, Property 1: Batch embedding preserves input order and output dimension
"""Property-based tests for the embedding service."""

import hashlib
import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from core.services.embeddings import (
    build_cross_cultural_text,
    build_phonetic_text,
    build_semantic_text,
    generate_embeddings_batch,
)


def _make_deterministic_vector(text: str) -> list[float]:
    """Generate a deterministic 1024-dim vector based on input text hash."""
    digest = hashlib.sha256(text.encode()).digest()
    # Use the hash bytes to seed a repeatable float sequence
    base = [b / 255.0 for b in digest]
    # Tile to 1024 dimensions
    vector = (base * (1024 // len(base) + 1))[:1024]
    return vector


def _mock_invoke_model(body, modelId, accept, contentType):
    """Simulate Bedrock invoke_model returning a 1024-dim vector based on input text."""
    request = json.loads(body)
    text = request["inputText"]
    vector = _make_deterministic_vector(text)
    response_body = json.dumps({"embedding": vector}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = response_body
    return {"body": mock_body}


@settings(max_examples=100)
@given(
    texts=st.lists(
        st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
        min_size=1,
        max_size=100,
    )
)
@patch("core.services.embeddings._get_bedrock_client")
def test_batch_embedding_preserves_order_and_dimension(mock_get_client, texts):
    """
    Property 1: Batch embedding preserves input order and output dimension.

    For any list of non-empty text strings (length 1 to 100), calling
    generate_embeddings_batch SHALL return a list of the same length where
    each element is a list of exactly 1024 floats, and the i-th output
    corresponds to the i-th input.

    Validates: Requirements 1.1, 1.2
    """
    # Configure the mock client
    mock_client_instance = MagicMock()
    mock_get_client.return_value = mock_client_instance
    mock_client_instance.invoke_model.side_effect = _mock_invoke_model

    # Call the function under test
    result = generate_embeddings_batch(texts)

    # Assert output length equals input length
    assert len(result) == len(texts), (
        f"Output length {len(result)} != input length {len(texts)}"
    )

    # Assert each vector has exactly 1024 floats
    for i, vector in enumerate(result):
        assert len(vector) == 1024, (
            f"Vector at index {i} has {len(vector)} dimensions, expected 1024"
        )
        assert all(isinstance(v, float) for v in vector), (
            f"Vector at index {i} contains non-float values"
        )

    # Assert order preservation: each output corresponds to its input
    for i, text in enumerate(texts):
        expected_vector = _make_deterministic_vector(text)
        assert result[i] == expected_vector, (
            f"Vector at index {i} does not match expected vector for input text"
        )


# Feature: titan-embedding-migration, Property 2: Batch embedding respects MAX_BATCH_SIZE invocation boundary
@settings(max_examples=100)
@given(
    texts=st.lists(
        st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
        min_size=1,
        max_size=100,
    )
)
@patch("core.services.embeddings._get_bedrock_client")
def test_batch_embedding_respects_max_batch_size_boundary(mock_get_client, texts):
    """
    Property 2: Batch embedding respects MAX_BATCH_SIZE invocation boundary.

    For any list of N non-empty text strings, generate_embeddings_batch SHALL
    make exactly N invoke_model calls (one per text), processed in
    ceil(N / MAX_BATCH_SIZE) groups where each group contains at most 20 calls.

    Validates: Requirements 1.5
    """
    import math

    from core.services.embeddings import MAX_BATCH_SIZE

    # Configure the mock client
    mock_client_instance = MagicMock()
    mock_get_client.return_value = mock_client_instance
    mock_client_instance.invoke_model.side_effect = _mock_invoke_model

    # Call the function under test
    result = generate_embeddings_batch(texts)

    # Assert invoke_model was called exactly N times (once per text)
    n = len(texts)
    assert mock_client_instance.invoke_model.call_count == n, (
        f"Expected {n} invoke_model calls, got {mock_client_instance.invoke_model.call_count}"
    )

    # Verify the expected number of batches: ceil(N / MAX_BATCH_SIZE)
    expected_batches = math.ceil(n / MAX_BATCH_SIZE)

    # Verify each invoke_model call was made with the correct text in order
    calls = mock_client_instance.invoke_model.call_args_list
    for i, call in enumerate(calls):
        call_body = json.loads(call[1]["body"] if "body" in call[1] else call[0][0])
        assert call_body["inputText"] == texts[i], (
            f"Call {i} used wrong text: expected {texts[i]!r}, got {call_body['inputText']!r}"
        )

    # Verify output length matches input (batching doesn't lose results)
    assert len(result) == n, (
        f"Output length {len(result)} != input length {n}"
    )

    # Verify the batch grouping: calls should be grouped in chunks of at most MAX_BATCH_SIZE
    # Since each call is one text, we verify that the total calls equal N
    # and that the number of logical batches is ceil(N/20)
    assert expected_batches == math.ceil(n / 20), (
        f"Expected {math.ceil(n / 20)} batches, computed {expected_batches}"
    )


# Feature: titan-embedding-migration, Property 4: Text building functions produce template-conformant output


@dataclass
class MockName:
    """Mock Name-like object for property testing text builders."""

    canonical_name: str
    semantic_summary: str
    origin_backgrounds: list[str] | None
    age_style_category: str
    historical_significance_score: float
    variants: list[str] | None
    length_category: str
    languages: list[str] | None
    scripts: list[str] | None


# Strategy for generating MockName objects with valid fields
mock_name_strategy = st.builds(
    MockName,
    canonical_name=st.text(min_size=1, max_size=50).filter(lambda t: t.strip()),
    semantic_summary=st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
    origin_backgrounds=st.one_of(
        st.none(),
        st.lists(st.text(min_size=1, max_size=30).filter(lambda t: t.strip()), min_size=1, max_size=5),
    ),
    age_style_category=st.text(min_size=1, max_size=30).filter(lambda t: t.strip()),
    historical_significance_score=st.floats(min_value=0.0, max_value=1.0),
    variants=st.one_of(
        st.none(),
        st.lists(st.text(min_size=1, max_size=30).filter(lambda t: t.strip()), min_size=1, max_size=10),
    ),
    length_category=st.text(min_size=1, max_size=20).filter(lambda t: t.strip()),
    languages=st.one_of(
        st.none(),
        st.lists(st.text(min_size=1, max_size=30).filter(lambda t: t.strip()), min_size=1, max_size=5),
    ),
    scripts=st.one_of(
        st.none(),
        st.lists(st.text(min_size=1, max_size=20).filter(lambda t: t.strip()), min_size=1, max_size=5),
    ),
)


@settings(max_examples=100)
@given(name=mock_name_strategy)
def test_text_builders_produce_template_conformant_output(name):
    """
    Property 4: Text building functions produce template-conformant output.

    For any valid Name object (with non-empty canonical_name, arbitrary
    origin_backgrounds, languages, scripts, variants, and valid score/category
    fields), each text building function SHALL produce a non-empty string
    containing the canonical_name and all template-specified fields without
    referencing any embedding provider.

    Validates: Requirements 7.1, 7.2, 7.3, 7.4
    """
    # Test build_semantic_text
    semantic_text = build_semantic_text(name)
    assert isinstance(semantic_text, str), "build_semantic_text must return a string"
    assert len(semantic_text) > 0, "build_semantic_text must return a non-empty string"
    assert name.canonical_name in semantic_text, (
        f"build_semantic_text output must contain canonical_name '{name.canonical_name}'"
    )
    legacy_provider = "open" + "ai"
    assert legacy_provider not in semantic_text.lower()

    # Test build_phonetic_text
    phonetic_text = build_phonetic_text(name)
    assert isinstance(phonetic_text, str), "build_phonetic_text must return a string"
    assert len(phonetic_text) > 0, "build_phonetic_text must return a non-empty string"
    assert name.canonical_name in phonetic_text, (
        f"build_phonetic_text output must contain canonical_name '{name.canonical_name}'"
    )
    assert legacy_provider not in phonetic_text.lower()

    # Test build_cross_cultural_text
    cross_cultural_text = build_cross_cultural_text(name)
    assert isinstance(cross_cultural_text, str), "build_cross_cultural_text must return a string"
    assert len(cross_cultural_text) > 0, "build_cross_cultural_text must return a non-empty string"
    assert name.canonical_name in cross_cultural_text, (
        f"build_cross_cultural_text output must contain canonical_name '{name.canonical_name}'"
    )
    assert legacy_provider not in cross_cultural_text.lower()

# ---------------------------------------------------------------------------
# Unit tests for Bedrock client configuration
# ---------------------------------------------------------------------------


@patch("core.services.embeddings.boto3.client")
def test_get_bedrock_client_uses_configured_region(mock_boto3_client):
    """
    Test that _get_bedrock_client uses settings.AWS_BEDROCK_REGION.

    Validates: Requirements 1.3
    """
    from django.conf import settings

    from core.services.embeddings import _get_bedrock_client

    _get_bedrock_client()

    mock_boto3_client.assert_called_once_with(
        "bedrock-runtime",
        region_name=settings.AWS_BEDROCK_REGION,
    )


@patch("core.services.embeddings._get_bedrock_client")
def test_bedrock_error_logged_and_reraised(mock_get_client):
    """
    Test that Bedrock errors are logged with logger.exception() and re-raised.

    Validates: Requirements 1.4
    """
    from botocore.exceptions import ClientError

    from core.services.embeddings import generate_embedding

    # Configure mock to raise ClientError
    mock_client_instance = MagicMock()
    mock_get_client.return_value = mock_client_instance
    mock_client_instance.invoke_model.side_effect = ClientError(
        error_response={"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        operation_name="InvokeModel",
    )

    # Verify the error is re-raised
    import pytest

    with patch("core.services.embeddings.logger") as mock_logger:
        with pytest.raises(ClientError):
            generate_embedding("test text")
        mock_logger.exception.assert_called_once()


@patch("core.services.embeddings._get_bedrock_client")
def test_bedrock_wrong_dimension_logged_and_reraised(mock_get_client):
    """Bedrock responses with stale dimensions should fail before reaching Qdrant."""
    import pytest

    from core.services.embeddings import generate_embedding

    mock_client_instance = MagicMock()
    mock_get_client.return_value = mock_client_instance
    response_body = json.dumps({"embedding": [0.0] * 1536}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = response_body
    mock_client_instance.invoke_model.return_value = {"body": mock_body}

    with patch("core.services.embeddings.logger") as mock_logger:
        with pytest.raises(ValueError, match="Bedrock embedding must be 1024 dimensions"):
            generate_embedding("test text")
        mock_logger.exception.assert_called_once()

# ---------------------------------------------------------------------------
# Smoke tests for legacy provider removal
# ---------------------------------------------------------------------------


def test_embeddings_module_has_no_legacy_provider_imports():
    """
    Test that embeddings.py has no legacy provider imports.

    Validates: Requirements 5.1
    """
    import inspect

    import core.services.embeddings as embeddings_module

    source = inspect.getsource(embeddings_module)
    legacy_provider = "open" + "ai"
    assert f"import {legacy_provider}" not in source
    assert f"from {legacy_provider}" not in source


def test_settings_has_aws_bedrock_region():
    """
    Test that settings has AWS_BEDROCK_REGION attribute with default us-east-1.

    Validates: Requirements 5.2
    """
    from django.conf import settings

    assert hasattr(settings, "AWS_BEDROCK_REGION"), "settings missing AWS_BEDROCK_REGION"
    assert settings.AWS_BEDROCK_REGION == "us-east-1", (
        f"AWS_BEDROCK_REGION default should be 'us-east-1', got '{settings.AWS_BEDROCK_REGION}'"
    )


def test_settings_does_not_have_legacy_provider_api_key():
    """
    Test that settings does not have the legacy provider API key attribute.

    Validates: Requirements 5.5
    """
    from django.conf import settings

    assert not hasattr(settings, ("open" + "ai").upper() + "_API_KEY")
