"""Quality-check the LLM-enriched cultural metadata CSVs.

Reports completeness, valid enum usage, distribution stats, and
flags suspicious rows (default fallbacks the LLM may have used).
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "core" / "fixtures"
SOURCES = [
    FIXTURES / "ssa_2020_top500_boys_cultural_metadata.csv",
    FIXTURES / "ssa_2020_top500_girls_cultural_metadata.csv",
]

ENRICHED_COLUMNS = [
    "origin_backgrounds",
    "languages",
    "scripts",
    "variants",
    "meaning",
    "age_style_category",
    "historical_significance_score",
    "semantic_summary",
]
VALID_AGE_STYLE = {"classic", "modern", "timeless"}
ISO_639_1 = re.compile(r"^[a-z]{2}$")


def split_pipe(value: str) -> list[str]:
    return [p.strip() for p in (value or "").split("|") if p.strip()]


def analyze_file(path: Path) -> None:
    print(f"\n=== {path.name} ===")
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    print(f"Rows: {total}")

    blank_counts = {col: 0 for col in ENRICHED_COLUMNS}
    invalid_age_style = []
    invalid_score = []
    invalid_lang_codes = []
    suspect_us = []
    suspect_en_only = []
    no_variants = []
    short_summary = []
    origin_counter: Counter[str] = Counter()
    lang_counter: Counter[str] = Counter()
    age_style_counter: Counter[str] = Counter()
    score_buckets = Counter()

    for row in rows:
        name = row["name"]
        for col in ENRICHED_COLUMNS:
            if not row.get(col, "").strip():
                blank_counts[col] += 1

        origins = split_pipe(row.get("origin_backgrounds", ""))
        for o in origins:
            origin_counter[o] += 1
        if "United States" in origins or "American" in origins:
            suspect_us.append(name)

        langs = split_pipe(row.get("languages", ""))
        for la in langs:
            lang_counter[la] += 1
            if not ISO_639_1.match(la):
                invalid_lang_codes.append(f"{name}:{la}")
        if langs == ["en"]:
            suspect_en_only.append(name)

        variants = split_pipe(row.get("variants", ""))
        if len(variants) <= 1:
            no_variants.append(name)

        age_style = row.get("age_style_category", "").strip()
        age_style_counter[age_style] += 1
        if age_style and age_style not in VALID_AGE_STYLE:
            invalid_age_style.append(f"{name}:{age_style}")

        try:
            score = float(row.get("historical_significance_score") or 0)
            if not (0.0 <= score <= 1.0):
                invalid_score.append(f"{name}:{score}")
            else:
                bucket = round(score * 10) / 10
                score_buckets[bucket] += 1
        except ValueError:
            invalid_score.append(f"{name}:{row.get('historical_significance_score')}")

        summary = (row.get("semantic_summary") or "").strip()
        if 0 < len(summary) < 30:
            short_summary.append(f"{name}: {summary}")

    print("\nCompleteness (blank cells per column):")
    for col, count in blank_counts.items():
        pct = (count / total) * 100 if total else 0
        marker = " <-- problem" if count > 0 else ""
        print(f"  {col:35s} {count:4d} blank ({pct:5.1f}%){marker}")

    print("\nTop 15 origin_backgrounds:")
    for origin, count in origin_counter.most_common(15):
        print(f"  {origin:25s} {count}")
    print(f"  (total distinct origins: {len(origin_counter)})")

    print("\nTop 10 languages:")
    for lang, count in lang_counter.most_common(10):
        print(f"  {lang:5s} {count}")
    print(f"  (total distinct lang codes: {len(lang_counter)})")

    print("\nage_style_category distribution:")
    for cat, count in age_style_counter.most_common():
        print(f"  {cat or '(blank)':10s} {count}")

    print("\nhistorical_significance_score buckets:")
    for bucket in sorted(score_buckets):
        print(f"  {bucket:.1f}  {score_buckets[bucket]}")

    print("\nIssues:")
    if invalid_age_style:
        print(f"  Invalid age_style_category values ({len(invalid_age_style)}): {invalid_age_style[:5]}")
    if invalid_score:
        print(f"  Invalid historical_significance_score ({len(invalid_score)}): {invalid_score[:5]}")
    if invalid_lang_codes:
        print(f"  Invalid language codes (not ISO 639-1) ({len(invalid_lang_codes)}): {invalid_lang_codes[:5]}")
    if suspect_us:
        print(f"  origin_backgrounds contains 'United States' or 'American' ({len(suspect_us)}): {suspect_us[:5]}")
    if suspect_en_only:
        print(f"  Names with languages == ['en'] only ({len(suspect_en_only)}): {suspect_en_only[:10]}")
    if no_variants:
        print(f"  Names with <= 1 variant ({len(no_variants)}): {no_variants[:5]}")
    if short_summary:
        print(f"  Suspiciously short semantic_summary ({len(short_summary)}): {short_summary[:3]}")

    if not any([invalid_age_style, invalid_score, invalid_lang_codes, suspect_us]):
        print("  None of the hard validation issues detected.")


if __name__ == "__main__":
    for source in SOURCES:
        if not source.exists():
            print(f"Missing: {source}")
            continue
        analyze_file(source)
