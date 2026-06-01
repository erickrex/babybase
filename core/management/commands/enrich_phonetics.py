"""Management command to backfill cached phonetic profiles via Bedrock Nova.

One-time, batched, idempotent, and resumable enrichment of active names. For
each batch it calls ``enrich_names``, which invokes Nova once per name lacking a
cached profile and persists the parsed profile to ``Name.phonetic_profile``.

This command does NOT re-index Qdrant: re-embedding the ``phonetic_style``
vector from the cached profiles stays the separate ``index_names_to_qdrant``
step (per the design's two-step backfill runbook).
"""

import logging

from django.core.management.base import BaseCommand

from core.models import Name
from core.services.phonetics import EnrichmentStats, enrich_names

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50


class Command(BaseCommand):
    help = "Generate and cache phonetic profiles for active names using Bedrock Nova."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of names to enrich per batch (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Regenerate profiles even for names that already have a cached phonetic_profile.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap the total number of names processed in this run (optional, for demo control).",
        )

    def handle(self, *args, **options):
        batch_size = max(options["batch_size"], 1)
        force = options["force"]
        limit = options["limit"]

        names = self._get_names_to_enrich(force=force, limit=limit)
        total = len(names)

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No names need enrichment. Nothing to do."))
            return

        self.stdout.write(f"Enriching {total} names (batch size {batch_size}, force={force})...")

        totals = EnrichmentStats()
        handled = 0
        for start in range(0, total, batch_size):
            batch = names[start : start + batch_size]
            stats = enrich_names(batch, force=force)

            totals.processed += stats.processed
            totals.skipped += stats.skipped
            totals.failed += stats.failed
            handled += len(batch)
            remaining = total - handled

            self.stdout.write(
                f"  Batch processed {stats.processed}, skipped {stats.skipped}, failed {stats.failed} "
                f"({handled}/{total} done, {remaining} remaining)."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {totals.processed}, skipped {totals.skipped}, "
                f"failed {totals.failed} across {total} names."
            )
        )

    def _get_names_to_enrich(self, *, force: bool, limit: int | None) -> list:
        """Return the active names to enrich this run.

        Without ``--force`` this excludes names that already have a non-empty
        ``phonetic_profile`` (stored as an empty dict when unenriched), so an
        interrupted run resumes by processing only the names still missing a
        profile. With ``--force`` all active names are included. ``--limit``
        caps the total names returned. Ordered by canonical name for stable,
        deterministic batching across runs.
        """
        queryset = Name.objects.filter(active=True)
        if not force:
            queryset = queryset.filter(phonetic_profile={})
        queryset = queryset.order_by("canonical_name")

        if limit is not None:
            queryset = queryset[: max(limit, 0)]

        return list(queryset)
