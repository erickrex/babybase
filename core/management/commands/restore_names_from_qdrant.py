"""Restore Name records and NameVectorIndexRef from Qdrant payloads.

Use when the relational database has been wiped but Qdrant still holds the
2200 indexed names. Reads each point's payload, recreates the Name row using
payload fields, and links it back to the existing Qdrant point ID.

This avoids re-running expensive embedding generation against Bedrock.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Name, NameVectorIndexRef
from core.services.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)

# Map historical_importance string in Qdrant payload to a numeric score
HISTORICAL_SCORE_MAP = {
    "low": 0.2,
    "moderate": 0.5,
    "medium": 0.5,
    "high": 0.85,
}


def _payload_to_name_kwargs(payload: dict) -> dict:
    """Build Name model kwargs from a Qdrant payload dict."""
    canonical = payload.get("canonical_name") or ""
    historical_str = payload.get("historical_importance") or "moderate"
    return {
        "canonical_name": canonical,
        "display_name": canonical,
        "gender_usage": payload.get("gender_usage") or [],
        "origin_backgrounds": payload.get("origin_backgrounds") or [],
        "languages": payload.get("languages") or [],
        "scripts": ["Latin"],
        "variants": [],
        "length_category": payload.get("length_category") or "medium",
        "age_style_category": payload.get("age_style_category") or "timeless",
        "historical_significance_score": HISTORICAL_SCORE_MAP.get(historical_str, 0.5),
        "semantic_summary": f"{canonical} is a name with origins in "
                           f"{', '.join(payload.get('origin_backgrounds') or ['unknown'])}.",
        "active": payload.get("active", True),
    }


class Command(BaseCommand):
    help = "Restore Name and NameVectorIndexRef records from Qdrant payloads."

    @transaction.atomic
    def handle(self, *args, **options):
        client = get_qdrant_client()
        collection = settings.QDRANT_COLLECTION

        info = client.get_collection(collection)
        total = info.points_count
        self.stdout.write(f"Found {total} points in Qdrant collection '{collection}'.")

        if Name.objects.exists():
            self.stdout.write(self.style.WARNING(
                f"Database already has {Name.objects.count()} names. Aborting to avoid duplicates."
            ))
            return

        offset = None
        created = 0
        skipped = 0
        batch_size = 200

        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            for point in points:
                payload = point.payload or {}
                payload_name_id = payload.get("name_id")
                if not payload_name_id or not payload.get("canonical_name"):
                    skipped += 1
                    continue

                kwargs = _payload_to_name_kwargs(payload)
                # Use the original UUID from the payload so existing references stay valid
                kwargs["id"] = payload_name_id

                name = Name.objects.create(**kwargs)
                NameVectorIndexRef.objects.create(
                    name=name,
                    qdrant_point_id=str(point.id),
                    qdrant_collection=collection,
                    embedding_version="titan-embed-text-v2",
                    indexed_at=timezone.now(),
                )
                created += 1

            self.stdout.write(f"Progress: {created} names restored...")

            if offset is None:
                break

        self.stdout.write(self.style.SUCCESS(
            f"Done. Restored {created} names ({skipped} skipped due to missing payload data)."
        ))
