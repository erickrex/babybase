"""Management command to backfill pronunciation audio via Amazon Polly.

One-time, batched, idempotent, and resumable generation of spoken pronunciation
audio for active names. For each batch it calls ``generate_pronunciations``,
which synthesizes audio with Polly for each name lacking stored audio, stores
the mp3 privately in S3, and persists the returned reference to
``Name.pronunciation_audio``.

This command is independent of phonetic enrichment and Qdrant indexing: it only
produces and stores audio, so it can run before or after those steps (per the
design's backfill runbook).
"""

import logging

from django.core.management.base import BaseCommand

from core.models import Name
from core.services.pronunciation import AudioStats, generate_pronunciations

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50


class Command(BaseCommand):
    help = "Generate and store pronunciation audio for active names using Amazon Polly."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of names to synthesize audio for per batch (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Regenerate audio even for names that already have stored pronunciation_audio.",
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

        names = self._get_names_to_process(force=force, limit=limit)
        total = len(names)

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No names need audio. Nothing to do."))
            return

        self.stdout.write(
            f"Generating audio for {total} names (batch size {batch_size}, force={force})..."
        )

        totals = AudioStats()
        handled = 0
        for start in range(0, total, batch_size):
            batch = names[start : start + batch_size]
            stats = generate_pronunciations(batch, force=force)

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

    def _get_names_to_process(self, *, force: bool, limit: int | None) -> list:
        """Return the active names to generate audio for this run.

        Without ``--force`` this excludes names that already have a non-empty
        ``pronunciation_audio`` reference (stored as an empty dict when no audio
        exists), so an interrupted run resumes by processing only the names
        still missing audio. With ``--force`` all active names are included.
        ``--limit`` caps the total names returned. Ordered by canonical name for
        stable, deterministic batching across runs.
        """
        queryset = Name.objects.filter(active=True)
        if not force:
            queryset = queryset.filter(pronunciation_audio={})
        queryset = queryset.order_by("canonical_name")

        if limit is not None:
            queryset = queryset[: max(limit, 0)]

        return list(queryset)
