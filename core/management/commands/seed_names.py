"""Management command to seed names from fixture JSON into PostgreSQL."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from core.models import Name


class Command(BaseCommand):
    help = "Load names from core/fixtures/names_seed.json into the database. Idempotent: skips existing names."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture",
            type=str,
            default=None,
            help="Path to fixture JSON file (default: core/fixtures/names_seed.json)",
        )

    def handle(self, *args, **options):
        fixture_path = options["fixture"]
        if fixture_path is None:
            fixture_path = Path(__file__).resolve().parent.parent.parent / "fixtures" / "names_seed.json"
        else:
            fixture_path = Path(fixture_path)

        if not fixture_path.exists():
            self.stderr.write(self.style.ERROR(f"Fixture file not found: {fixture_path}"))
            return

        with open(fixture_path) as f:
            names_data = json.load(f)

        created_count = 0
        skipped_count = 0

        for entry in names_data:
            canonical = entry["canonical_name"]
            if Name.objects.filter(canonical_name=canonical).exists():
                skipped_count += 1
                continue

            Name.objects.create(
                canonical_name=canonical,
                display_name=entry["display_name"],
                gender_usage=entry.get("gender_usage", []),
                origin_backgrounds=entry.get("origin_backgrounds", []),
                languages=entry.get("languages", []),
                scripts=entry.get("scripts", []),
                variants=entry.get("variants", []),
                length_category=entry["length_category"],
                age_style_category=entry["age_style_category"],
                historical_significance_score=entry.get("historical_significance_score", 0.0),
                semantic_summary=entry["semantic_summary"],
                active=entry.get("active", True),
            )
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Seed complete: {created_count} created, {skipped_count} skipped.")
        )
