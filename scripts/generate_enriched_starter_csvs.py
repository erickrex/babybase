"""Generate enriched starter CSVs from the existing SSA seed files.

Adds blank columns for cultural metadata (origin_backgrounds, languages,
scripts, variants, meaning, age_style_category, historical_significance_score,
semantic_summary). The blank cells are intended to be filled by an LLM,
then the enriched files become the new seed source for `seed_real_names`.

Usage:
    uv run python scripts/generate_enriched_starter_csvs.py
"""

from __future__ import annotations

import csv
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "core" / "fixtures"

SOURCE_FILES = [
    ("ssa_2020_top500_boys.csv", "ssa_2020_top500_boys_enriched.csv"),
    ("ssa_2020_top500_girls.csv", "ssa_2020_top500_girls_enriched.csv"),
]

# Columns added on top of the SSA stats columns.
# All start blank — the LLM is expected to fill them in.
ENRICHED_COLUMNS = [
    "origin_backgrounds",            # pipe-separated cultural origins, e.g. "Hebrew|Irish"
    "languages",                     # pipe-separated ISO 639-1 codes, e.g. "en|he|ga"
    "scripts",                       # pipe-separated writing systems, e.g. "Latin|Hebrew"
    "variants",                      # pipe-separated spelling variants, e.g. "William|Wilhelm|Guillermo"
    "meaning",                       # short etymological meaning, e.g. "strong-willed warrior"
    "age_style_category",            # one of: classic, modern, timeless
    "historical_significance_score", # float in [0.0, 1.0]
    "semantic_summary",              # 1-2 sentence rich description for semantic search
]


def main() -> None:
    for source_name, target_name in SOURCE_FILES:
        source = FIXTURES_DIR / source_name
        target = FIXTURES_DIR / target_name

        with open(source, newline="") as src_file:
            reader = csv.DictReader(src_file)
            rows = list(reader)
            existing_columns = list(reader.fieldnames or [])

        if not rows:
            print(f"Skipping empty file: {source}")
            continue

        new_fieldnames = existing_columns + ENRICHED_COLUMNS

        with open(target, "w", newline="") as out_file:
            writer = csv.DictWriter(out_file, fieldnames=new_fieldnames)
            writer.writeheader()
            for row in rows:
                for column in ENRICHED_COLUMNS:
                    row.setdefault(column, "")
                writer.writerow(row)

        print(f"Wrote {len(rows)} rows to {target}")


if __name__ == "__main__":
    main()
