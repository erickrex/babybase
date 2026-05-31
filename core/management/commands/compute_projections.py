"""Management command to compute 2D projections for the Name Constellation map.

Persists ``Name.x_2d`` / ``Name.y_2d`` as a deterministic PCA (SVD) projection
of the ``semantic`` named vectors retrieved from Qdrant, normalized per-axis to
the ``[0, 1]`` range expected by the constellation API and frontend.

The math and Qdrant retrieval live in ``core/services/projection.py``; this
command only orchestrates loading, partitioning, persistence selection, and
reporting so it stays thin (per the project architecture rules).
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from qdrant_client.http.exceptions import UnexpectedResponse

from core.models import Name
from core.services.projection import (
    INSUFFICIENT_VECTORS,
    fetch_semantic_vectors,
    normalize_axes,
    pca_project_2d,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Compute 2D projections for names via PCA over Qdrant semantic vectors."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute projections even for names that already have coordinates.",
        )

    def handle(self, *args, **options):
        force = options["force"]

        # Load all active names in a stable order by id so the PCA input matrix
        # and persisted coordinates are independent of row arrival order (Req 3.3).
        names = list(Name.objects.filter(active=True).order_by("id"))
        if not names:
            self.stdout.write(self.style.SUCCESS("No active names to project."))
            return

        # Retrieve semantic vectors from Qdrant. On failure, abort before any
        # write so existing coordinates are never partially corrupted (Req 5).
        name_ids = [str(name.id) for name in names]
        try:
            vectors = fetch_semantic_vectors(name_ids)
        except (UnexpectedResponse, ConnectionError, TimeoutError) as exc:
            logger.error("Semantic vector retrieval from Qdrant failed: %s", exc)
            raise CommandError(
                f"Aborting projection: semantic vector retrieval from Qdrant failed: {exc}"
            ) from exc

        # Partition into names that have a retrievable semantic vector and those
        # that do not. Skipped names keep their existing coordinates (Req 4).
        has_vector = [name for name in names if str(name.id) in vectors]
        skipped = len(names) - len(has_vector)

        if len(has_vector) < INSUFFICIENT_VECTORS:
            self.stdout.write(
                self.style.WARNING(
                    f"Insufficient vectors to project: {len(has_vector)} name(s) have "
                    f"a retrievable semantic vector (need at least {INSUFFICIENT_VECTORS}). "
                    "No coordinates were written."
                )
            )
            return

        # Build the PCA input matrix from ALL has-vector names regardless of
        # --force, so the flag changes only which results are persisted, not the
        # projection itself (Req 6.3). Rows are in id order, matching has_vector.
        matrix = [vectors[str(name.id)] for name in has_vector]
        coords = normalize_axes(pca_project_2d(matrix))

        # Select which names to persist based on the --force flag (Req 6.1, 6.2).
        # With --force: overwrite all has-vector names. Without: only fill names
        # whose stored x_2d is null (a stored 0.0 is a valid coordinate and is
        # left untouched).
        selected: list[Name] = []
        for name, (x, y) in zip(has_vector, coords):
            if force or name.x_2d is None:
                name.x_2d = x
                name.y_2d = y
                selected.append(name)

        if selected:
            with transaction.atomic():
                Name.objects.bulk_update(selected, ["x_2d", "y_2d"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Projected {len(has_vector)} name(s); "
                f"skipped {skipped} (no semantic vector); "
                f"wrote {len(selected)} coordinate(s)."
            )
        )
