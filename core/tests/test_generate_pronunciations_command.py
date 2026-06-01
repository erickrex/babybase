"""Tests for the ``generate_pronunciations`` management command (task 8.2).

These tests drive the command through ``django.core.management.call_command``
and mock the service layer (``generate_pronunciations``) so no real Amazon
Polly or S3 calls happen. They verify the command's *selection* and *reporting*
behavior:

- a clean re-run without ``--force`` selects zero names and makes zero Polly
  work (the service is never invoked) — Req 6.5;
- a resumed run without ``--force`` passes only the active names still missing
  stored audio, scoped to active names — Req 12.4;
- ``--force`` regenerates by passing every active name with ``force=True``;
- batching and per-batch progress reporting (processed/remaining) — Req 6.5
  progress / 12.4.

The command calls ``generate_pronunciations(batch, force=force)`` once per
batch, so the mock's call arguments reveal exactly which Name rows were
selected.
"""

import math
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from core.models import Name
from core.services.pronunciation import AudioStats

# Where the command looks up the service symbol (imported into the command
# module's namespace), so this is the correct patch target.
GENERATE_TARGET = "core.management.commands.generate_pronunciations.generate_pronunciations"


def _create_name(canonical_name: str, *, active: bool = True, pronunciation_audio: dict | None = None) -> Name:
    """Persist a minimal Name following the existing test conventions.

    Mirrors the ``_create_name`` helper in ``test_enrich_phonetics_command.py``.
    A name is considered to "already have audio" when ``pronunciation_audio`` is
    non-empty; names without audio default to an empty dict.
    """
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
        active=active,
        pronunciation_audio=pronunciation_audio if pronunciation_audio is not None else {},
    )


# A representative non-empty audio reference (marks a name as already done).
AUDIO = {
    "bucket": "b",
    "key": "pronunciations/x.mp3",
    "voice": "Joanna",
    "content_type": "audio/mpeg",
}


def _stats_for_batch(batch, *, force=False):
    """Service stand-in: report every name in the batch as processed.

    The real service synthesizes and stores audio; the command only reads its
    queryset once at the start, so returning a stats object is sufficient to
    exercise the command's accumulation and progress reporting.
    """
    return AudioStats(processed=len(batch))


def _names_passed(mock_generate):
    """Flatten the Name rows the command passed to ``generate_pronunciations``."""
    passed = []
    for call in mock_generate.call_args_list:
        batch = call.args[0]
        passed.extend(batch)
    return passed


@pytest.mark.django_db
def test_clean_rerun_without_force_makes_zero_polly_work():
    """
    When every active name already has stored audio, a run without ``--force``
    selects zero names and never invokes the service (zero Polly work on a clean
    re-run).

    Validates: Requirements 6.5
    """
    _create_name("Aiden", pronunciation_audio=AUDIO)
    _create_name("Sofia", pronunciation_audio=AUDIO)

    out = StringIO()
    with patch(GENERATE_TARGET, side_effect=_stats_for_batch) as mock_generate:
        call_command("generate_pronunciations", stdout=out)

    mock_generate.assert_not_called()
    assert "Nothing to do" in out.getvalue()


@pytest.mark.django_db
def test_resume_passes_only_empty_audio_active_names():
    """
    A resumed run without ``--force`` generates audio only for the active names
    that still have empty ``pronunciation_audio``, skipping already-audio'd and
    inactive names.

    Validates: Requirements 12.4
    """
    audioed = _create_name("Aiden", pronunciation_audio=AUDIO)
    empty_a = _create_name("Bella")
    empty_b = _create_name("Caleb")
    inactive_empty = _create_name("Dormant", active=False)

    out = StringIO()
    with patch(GENERATE_TARGET, side_effect=_stats_for_batch) as mock_generate:
        call_command("generate_pronunciations", stdout=out)

    selected_ids = {n.pk for n in _names_passed(mock_generate)}

    # Exactly the active, empty-audio names were selected.
    assert selected_ids == {empty_a.pk, empty_b.pk}
    assert audioed.pk not in selected_ids
    assert inactive_empty.pk not in selected_ids

    # The service was invoked without force on this resume run.
    for call in mock_generate.call_args_list:
        assert call.kwargs["force"] is False


@pytest.mark.django_db
def test_force_regenerates_all_active_names():
    """
    With ``--force``, every active name (including already-audio'd ones) is
    passed to the service with ``force=True``.

    Validates: Requirements 6.5
    """
    audioed = _create_name("Aiden", pronunciation_audio=AUDIO)
    empty = _create_name("Bella")
    inactive = _create_name("Dormant", active=False)

    out = StringIO()
    with patch(GENERATE_TARGET, side_effect=_stats_for_batch) as mock_generate:
        call_command("generate_pronunciations", "--force", stdout=out)

    selected_ids = {n.pk for n in _names_passed(mock_generate)}

    # Both the audio'd and the empty active name are regenerated; inactive excluded.
    assert selected_ids == {audioed.pk, empty.pk}
    assert inactive.pk not in selected_ids

    assert mock_generate.call_count >= 1
    for call in mock_generate.call_args_list:
        assert call.kwargs["force"] is True


@pytest.mark.django_db
def test_batching_and_progress_reporting():
    """
    The command iterates in batches of ``--batch-size`` and reports per-batch
    progress including processed and remaining counts.

    Validates: Requirements 6.5, 12.4
    """
    total = 5
    batch_size = 2
    # Created out of alphabetical order; the command sorts by canonical_name.
    for canonical in ["Eli", "Bo", "Dan", "Ava", "Cal"]:
        _create_name(canonical)

    out = StringIO()
    with patch(GENERATE_TARGET, side_effect=_stats_for_batch) as mock_generate:
        call_command("generate_pronunciations", "--batch-size", str(batch_size), stdout=out)

    # One service call per batch: ceil(5 / 2) == 3 batches of sizes 2, 2, 1.
    expected_batches = math.ceil(total / batch_size)
    assert mock_generate.call_count == expected_batches
    assert [len(call.args[0]) for call in mock_generate.call_args_list] == [2, 2, 1]

    # Names are selected in canonical_name order for deterministic batching.
    passed = [n.canonical_name for n in _names_passed(mock_generate)]
    assert passed == ["Ava", "Bo", "Cal", "Dan", "Eli"]

    output = out.getvalue()
    # Per-batch progress reports both processed counts and remaining counts.
    assert "remaining" in output
    assert "(2/5 done, 3 remaining)" in output
    assert "(4/5 done, 1 remaining)" in output
    assert "(5/5 done, 0 remaining)" in output
    # Final summary reflects the accumulated processed total across all names.
    assert "Processed 5" in output
    assert "across 5 names" in output
