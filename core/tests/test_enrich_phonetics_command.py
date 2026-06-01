"""Tests for the ``enrich_phonetics`` management command (task 4.2).

These tests drive the command through ``django.core.management.call_command``
and mock the service layer (``enrich_names``) so no real Bedrock Nova calls
happen. They verify the command's *selection* and *reporting* behavior:

- a clean re-run without ``--force`` selects zero names and makes zero Nova
  work (the service is never invoked) — Req 3.4;
- a resumed run without ``--force`` passes only the names still missing a
  profile, scoped to active names — Req 3.5, 12.4;
- ``--force`` regenerates by passing every active name with ``force=True`` —
  Req 3.2/3.4 force path;
- batching and per-batch progress reporting (processed/remaining) — Req 3.6.

The command calls ``enrich_names(batch, force=force)`` once per batch, so the
mock's call arguments reveal exactly which Name rows were selected.
"""

import math
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from core.models import Name
from core.services.phonetics import EnrichmentStats

# Where the command looks up the service symbol (imported into the command
# module's namespace), so this is the correct patch target.
ENRICH_TARGET = "core.management.commands.enrich_phonetics.enrich_names"


def _create_name(canonical_name: str, *, active: bool = True, phonetic_profile: dict | None = None) -> Name:
    """Persist a minimal Name following the existing test conventions.

    Mirrors the ``_create_name`` helper in ``test_phonetics.py``. A name is
    considered "already enriched" when ``phonetic_profile`` is non-empty;
    unenriched names default to an empty dict.
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
        phonetic_profile=phonetic_profile if phonetic_profile is not None else {},
    )


# A representative non-empty cached profile (marks a name as already enriched).
PROFILE = {
    "ipa": "ˈeɪdən",
    "rhyme": "-aden",
    "syllables": 2,
    "stress": "primary on first syllable",
    "sounds_like": "two beats, soft ending",
}


def _stats_for_batch(batch, *, force=False):
    """Service stand-in: report every name in the batch as processed.

    The real service persists profiles; the command only reads its queryset
    once at the start, so returning a stats object is sufficient to exercise
    the command's accumulation and progress reporting.
    """
    return EnrichmentStats(processed=len(batch))


def _names_passed(mock_enrich):
    """Flatten the Name rows the command passed to ``enrich_names`` across batches."""
    passed = []
    for call in mock_enrich.call_args_list:
        batch = call.args[0]
        passed.extend(batch)
    return passed


@pytest.mark.django_db
def test_clean_rerun_without_force_makes_zero_nova_work():
    """
    When every active name already has a non-empty profile, a run without
    ``--force`` selects zero names and never invokes the service (zero Nova
    work on a clean re-run).

    Validates: Requirements 3.4
    """
    _create_name("Aiden", phonetic_profile=PROFILE)
    _create_name("Sofia", phonetic_profile=PROFILE)

    out = StringIO()
    with patch(ENRICH_TARGET, side_effect=_stats_for_batch) as mock_enrich:
        call_command("enrich_phonetics", stdout=out)

    mock_enrich.assert_not_called()
    assert "Nothing to do" in out.getvalue()


@pytest.mark.django_db
def test_resume_passes_only_empty_profile_active_names():
    """
    A resumed run without ``--force`` enriches only the active names that still
    have an empty profile, skipping already-profiled and inactive names.

    Validates: Requirements 3.5, 12.4
    """
    profiled = _create_name("Aiden", phonetic_profile=PROFILE)
    empty_a = _create_name("Bella")
    empty_b = _create_name("Caleb")
    inactive_empty = _create_name("Dormant", active=False)

    out = StringIO()
    with patch(ENRICH_TARGET, side_effect=_stats_for_batch) as mock_enrich:
        call_command("enrich_phonetics", stdout=out)

    selected_ids = {n.pk for n in _names_passed(mock_enrich)}

    # Exactly the active, empty-profile names were selected.
    assert selected_ids == {empty_a.pk, empty_b.pk}
    assert profiled.pk not in selected_ids
    assert inactive_empty.pk not in selected_ids

    # The service was invoked without force on this resume run.
    for call in mock_enrich.call_args_list:
        assert call.kwargs["force"] is False


@pytest.mark.django_db
def test_force_regenerates_all_active_names():
    """
    With ``--force``, every active name (including already-profiled ones) is
    passed to the service with ``force=True``.

    Validates: Requirements 3.2, 3.4
    """
    profiled = _create_name("Aiden", phonetic_profile=PROFILE)
    empty = _create_name("Bella")
    inactive = _create_name("Dormant", active=False)

    out = StringIO()
    with patch(ENRICH_TARGET, side_effect=_stats_for_batch) as mock_enrich:
        call_command("enrich_phonetics", "--force", stdout=out)

    selected_ids = {n.pk for n in _names_passed(mock_enrich)}

    # Both the profiled and the empty active name are regenerated; inactive excluded.
    assert selected_ids == {profiled.pk, empty.pk}
    assert inactive.pk not in selected_ids

    assert mock_enrich.call_count >= 1
    for call in mock_enrich.call_args_list:
        assert call.kwargs["force"] is True


@pytest.mark.django_db
def test_batching_and_progress_reporting():
    """
    The command iterates in batches of ``--batch-size`` and reports per-batch
    progress including processed and remaining counts.

    Validates: Requirements 3.6
    """
    total = 5
    batch_size = 2
    # Created out of alphabetical order; the command sorts by canonical_name.
    for canonical in ["Eli", "Bo", "Dan", "Ava", "Cal"]:
        _create_name(canonical)

    out = StringIO()
    with patch(ENRICH_TARGET, side_effect=_stats_for_batch) as mock_enrich:
        call_command("enrich_phonetics", "--batch-size", str(batch_size), stdout=out)

    # One service call per batch: ceil(5 / 2) == 3 batches of sizes 2, 2, 1.
    expected_batches = math.ceil(total / batch_size)
    assert mock_enrich.call_count == expected_batches
    assert [len(call.args[0]) for call in mock_enrich.call_args_list] == [2, 2, 1]

    # Names are selected in canonical_name order for deterministic batching.
    passed = [n.canonical_name for n in _names_passed(mock_enrich)]
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
