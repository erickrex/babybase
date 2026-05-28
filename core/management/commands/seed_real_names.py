"""Seed real baby names from SSA national baby-name data."""

from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    MutualMatch,
    Name,
    NameVectorIndexRef,
    RecommendationDeck,
    Swipe,
    UserTasteVector,
)

OFFICIAL_SSA_NAMES_ZIP_URL = "https://www.ssa.gov/oact/babynames/names.zip"
FALLBACK_SSA_NAMES_ZIP_URL = (
    "https://raw.githubusercontent.com/hackerb9/ssa-baby-names/main/raw-data/names.zip"
)
YEAR_FILE_RE = re.compile(r"yob(?P<year>\d{4})\.txt$")
BUNDLED_CSV_PATHS = (
    Path(__file__).resolve().parents[2] / "fixtures" / "ssa_2020_top500_boys_cultural_metadata.csv",
    Path(__file__).resolve().parents[2] / "fixtures" / "ssa_2020_top500_girls_cultural_metadata.csv",
)
ENRICHED_BUNDLED_CSV_PATHS = (
    Path(__file__).resolve().parents[2] / "fixtures" / "ssa_2020_top500_boys_enriched.csv",
    Path(__file__).resolve().parents[2] / "fixtures" / "ssa_2020_top500_girls_enriched.csv",
)
LEGACY_BUNDLED_CSV_PATHS = (
    Path(__file__).resolve().parents[2] / "fixtures" / "ssa_2020_top500_boys.csv",
    Path(__file__).resolve().parents[2] / "fixtures" / "ssa_2020_top500_girls.csv",
)


def _split_pipe(value: str | None) -> list[str]:
    """Parse a pipe-separated cell into a clean list. Empty cells return []."""
    if not value:
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


@dataclass(frozen=True)
class SsaNameRow:
    name: str
    sex: str
    count: int
    year: int


@dataclass
class SsaNameStats:
    name: str
    latest_year: int
    latest_counts_by_sex: dict[str, int]
    latest_ranks_by_sex: dict[str, int]
    first_year: int
    total_count: int
    # Enriched metadata (from LLM-filled CSVs). Empty when not provided.
    origin_backgrounds: list[str] | None = None
    languages: list[str] | None = None
    scripts: list[str] | None = None
    variants: list[str] | None = None
    meaning: str = ""
    age_style_category_override: str = ""
    historical_significance_override: float | None = None
    semantic_summary_override: str = ""


def _download_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/zip,*/*",
            "User-Agent": "BabyBase name seeder (local development)",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _load_zip_bytes(source_zip: str | None) -> bytes:
    if source_zip:
        with open(source_zip, "rb") as source_file:
            return source_file.read()

    try:
        return _download_url(OFFICIAL_SSA_NAMES_ZIP_URL)
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return _download_url(FALLBACK_SSA_NAMES_ZIP_URL)


def _latest_year_from_zip(names_zip: zipfile.ZipFile, requested_year: int | None) -> int:
    years = []
    for filename in names_zip.namelist():
        match = YEAR_FILE_RE.search(filename)
        if match:
            years.append(int(match.group("year")))

    if not years:
        raise CommandError("No SSA yobYYYY.txt files were found in the source zip.")

    latest_year = max(years)
    if requested_year is None:
        return latest_year
    if requested_year not in years:
        raise CommandError(f"Year {requested_year} was not found in the SSA source zip.")
    return requested_year


def _read_year_rows(names_zip: zipfile.ZipFile, year: int) -> list[SsaNameRow]:
    filename = f"yob{year}.txt"
    try:
        raw = names_zip.read(filename).decode("utf-8")
    except KeyError as exc:
        raise CommandError(f"{filename} was not found in the SSA source zip.") from exc

    rows = []
    for name, sex, count in csv.reader(io.StringIO(raw)):
        rows.append(SsaNameRow(name=name, sex=sex, count=int(count), year=year))
    return rows


def _select_latest_rows(
    rows: list[SsaNameRow],
    *,
    max_per_sex: int,
    include_sexes: set[str],
) -> list[SsaNameRow]:
    selected = []
    for sex in sorted(include_sexes):
        sex_rows = [row for row in rows if row.sex == sex]
        sex_rows.sort(key=lambda row: row.count, reverse=True)
        selected.extend(sex_rows[:max_per_sex])
    return selected


def _build_stats(
    names_zip: zipfile.ZipFile,
    *,
    latest_rows: list[SsaNameRow],
    latest_year: int,
) -> list[SsaNameStats]:
    selected_names = {row.name for row in latest_rows}
    stats_by_name = {
        name: SsaNameStats(
            name=name,
            latest_year=latest_year,
            latest_counts_by_sex={},
            latest_ranks_by_sex={},
            first_year=latest_year,
            total_count=0,
        )
        for name in selected_names
    }

    latest_by_sex: dict[str, list[SsaNameRow]] = {"F": [], "M": []}
    for row in latest_rows:
        latest_by_sex.setdefault(row.sex, []).append(row)
        stats_by_name[row.name].latest_counts_by_sex[row.sex] = row.count

    for sex_rows in latest_by_sex.values():
        sex_rows.sort(key=lambda row: row.count, reverse=True)
        for rank, row in enumerate(sex_rows, start=1):
            stats_by_name[row.name].latest_ranks_by_sex[row.sex] = rank

    year_files = []
    for filename in names_zip.namelist():
        match = YEAR_FILE_RE.search(filename)
        if match:
            year_files.append((int(match.group("year")), filename))

    for year, filename in sorted(year_files):
        raw = names_zip.read(filename).decode("utf-8")
        for name, _sex, count in csv.reader(io.StringIO(raw)):
            stats = stats_by_name.get(name)
            if not stats:
                continue
            stats.first_year = min(stats.first_year, year)
            stats.total_count += int(count)

    return sorted(
        stats_by_name.values(),
        key=lambda stats: (
            min(stats.latest_ranks_by_sex.values()),
            stats.name,
        ),
    )


def _build_stats_from_csv(csv_paths: list[str | Path]) -> list[SsaNameStats]:
    stats_by_name: dict[str, SsaNameStats] = {}

    for csv_path in csv_paths:
        with open(csv_path, newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                name = row["name"]
                sex = row["sex"]
                stats = stats_by_name.setdefault(
                    name,
                    SsaNameStats(
                        name=name,
                        latest_year=int(row["latest_year"]),
                        latest_counts_by_sex={},
                        latest_ranks_by_sex={},
                        first_year=int(row["first_year"]),
                        total_count=int(row["total_count"]),
                    ),
                )
                stats.latest_year = max(stats.latest_year, int(row["latest_year"]))
                stats.first_year = min(stats.first_year, int(row["first_year"]))
                stats.total_count = max(stats.total_count, int(row["total_count"]))
                stats.latest_counts_by_sex[sex] = int(row["latest_count"])
                stats.latest_ranks_by_sex[sex] = int(row["latest_rank"])

                # Optional enriched columns. Last non-empty value wins
                # when the same name appears in multiple files (unisex names).
                if row.get("origin_backgrounds"):
                    stats.origin_backgrounds = _split_pipe(row["origin_backgrounds"])
                if row.get("languages"):
                    stats.languages = _split_pipe(row["languages"])
                if row.get("scripts"):
                    stats.scripts = _split_pipe(row["scripts"])
                if row.get("variants"):
                    stats.variants = _split_pipe(row["variants"])
                if row.get("meaning"):
                    stats.meaning = row["meaning"].strip()
                if row.get("age_style_category"):
                    stats.age_style_category_override = row["age_style_category"].strip()
                if row.get("historical_significance_score"):
                    try:
                        stats.historical_significance_override = float(
                            row["historical_significance_score"]
                        )
                    except ValueError:
                        pass
                if row.get("semantic_summary"):
                    stats.semantic_summary_override = row["semantic_summary"].strip()

    return sorted(
        stats_by_name.values(),
        key=lambda stats: (
            min(stats.latest_ranks_by_sex.values()),
            stats.name,
        ),
    )


def _length_category(name: str) -> str:
    if len(name) <= 5:
        return "short"
    if len(name) <= 8:
        return "medium"
    return "long"


def _age_style_category(stats: SsaNameStats) -> str:
    if stats.age_style_category_override in {"classic", "modern", "timeless"}:
        return stats.age_style_category_override
    if stats.first_year <= 1925 and min(stats.latest_ranks_by_sex.values()) <= 500:
        return "timeless"
    if stats.latest_year - stats.first_year <= 25:
        return "modern"
    return "classic"


def _historical_score(stats: SsaNameStats, max_total_count: int) -> float:
    if stats.historical_significance_override is not None:
        return max(0.0, min(1.0, stats.historical_significance_override))
    if max_total_count <= 0:
        return 0.0
    return round(0.2 + (0.75 * (stats.total_count / max_total_count)), 2)


def _gender_usage(stats: SsaNameStats) -> list[str]:
    usage = []
    if "M" in stats.latest_counts_by_sex:
        usage.append("boy")
    if "F" in stats.latest_counts_by_sex:
        usage.append("girl")
    return usage


def _filter_stats_to_sex(stats: list[SsaNameStats], sex: str) -> list[SsaNameStats]:
    filtered_stats = []
    for item in stats:
        if sex not in item.latest_counts_by_sex:
            continue
        filtered_stats.append(
            SsaNameStats(
                name=item.name,
                latest_year=item.latest_year,
                latest_counts_by_sex={sex: item.latest_counts_by_sex[sex]},
                latest_ranks_by_sex={sex: item.latest_ranks_by_sex[sex]},
                first_year=item.first_year,
                total_count=item.total_count,
                origin_backgrounds=item.origin_backgrounds,
                languages=item.languages,
                scripts=item.scripts,
                variants=item.variants,
                meaning=item.meaning,
                age_style_category_override=item.age_style_category_override,
                historical_significance_override=item.historical_significance_override,
                semantic_summary_override=item.semantic_summary_override,
            )
        )
    return filtered_stats


def _semantic_summary(stats: SsaNameStats) -> str:
    if stats.semantic_summary_override:
        return stats.semantic_summary_override

    sex_summaries = []
    if "M" in stats.latest_counts_by_sex:
        sex_summaries.append(
            f"ranked #{stats.latest_ranks_by_sex['M']} for boys "
            f"with {stats.latest_counts_by_sex['M']} births"
        )
    if "F" in stats.latest_counts_by_sex:
        sex_summaries.append(
            f"ranked #{stats.latest_ranks_by_sex['F']} for girls "
            f"with {stats.latest_counts_by_sex['F']} births"
        )
    latest_text = " and ".join(sex_summaries)
    meaning_text = f" Meaning: {stats.meaning}." if stats.meaning else ""
    origin_text = ""
    if stats.origin_backgrounds:
        origin_text = f" Origin: {', '.join(stats.origin_backgrounds)}."
    return (
        f"{stats.name} is a real given name recorded in SSA national baby-name data. "
        f"In {stats.latest_year}, it {latest_text}; the name first appears in the "
        f"public national series in {stats.first_year}.{origin_text}{meaning_text}"
    )


def _build_name(stats: SsaNameStats, max_total_count: int) -> Name:
    return Name(
        canonical_name=stats.name,
        display_name=stats.name,
        gender_usage=_gender_usage(stats),
        origin_backgrounds=stats.origin_backgrounds or ["United States"],
        languages=stats.languages or ["en"],
        scripts=stats.scripts or ["Latin"],
        variants=stats.variants or [stats.name],
        length_category=_length_category(stats.name),
        age_style_category=_age_style_category(stats),
        historical_significance_score=_historical_score(stats, max_total_count),
        semantic_summary=_semantic_summary(stats),
        active=True,
    )


class Command(BaseCommand):
    help = "Load real baby names from SSA national data. Use --replace to remove stale generated names."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-zip",
            default=None,
            help="Optional local SSA names.zip path. Defaults to bundled CSV seed files.",
        )
        parser.add_argument(
            "--source-csv",
            action="append",
            default=None,
            help="Optional bundled-format CSV path. Can be passed multiple times.",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="SSA birth year to import. Defaults to latest year available in the source zip.",
        )
        parser.add_argument(
            "--max-per-sex",
            type=int,
            default=1000,
            help="Maximum latest-year names per SSA sex series to import.",
        )
        parser.add_argument(
            "--sex",
            choices=["both", "boy", "girl"],
            default="both",
            help="Import boy names, girl names, or both.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help=(
                "Delete existing names plus name-dependent decks, swipes, matches, vector refs, "
                "and taste vectors before seeding."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        max_per_sex = options["max_per_sex"]
        if max_per_sex <= 0:
            raise CommandError("--max-per-sex must be greater than zero.")

        if options["source_zip"]:
            stats = self._build_stats_from_zip_options(options)
        else:
            csv_paths = [Path(path) for path in (options["source_csv"] or BUNDLED_CSV_PATHS)]
            # Cascade fallback: cultural_metadata -> enriched -> legacy
            if not options["source_csv"] and not all(path.exists() for path in csv_paths):
                csv_paths = [Path(path) for path in ENRICHED_BUNDLED_CSV_PATHS]
            if not options["source_csv"] and not all(path.exists() for path in csv_paths):
                csv_paths = [Path(path) for path in LEGACY_BUNDLED_CSV_PATHS]
            missing_paths = [str(path) for path in csv_paths if not path.exists()]
            if missing_paths:
                raise CommandError(f"CSV seed file(s) not found: {', '.join(missing_paths)}")
            stats = _build_stats_from_csv(csv_paths)

        if options["sex"] == "boy":
            stats = _filter_stats_to_sex(stats, "M")
        elif options["sex"] == "girl":
            stats = _filter_stats_to_sex(stats, "F")

        if options["replace"]:
            RecommendationDeck.objects.all().delete()
            Swipe.objects.all().delete()
            MutualMatch.objects.all().delete()
            UserTasteVector.objects.all().delete()
            NameVectorIndexRef.objects.all().delete()
            Name.objects.all().delete()

        max_total_count = max((item.total_count for item in stats), default=0)
        created = 0
        skipped = 0
        for item in stats:
            if Name.objects.filter(canonical_name=item.name).exists():
                skipped += 1
                continue
            _build_name(item, max_total_count).save()
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} real names from SSA year {_latest_year_from_stats(stats)}; "
                f"{skipped} already existed."
            )
        )

    def _build_stats_from_zip_options(self, options: dict) -> list[SsaNameStats]:
        zip_bytes = _load_zip_bytes(options["source_zip"])
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as names_zip:
            latest_year = _latest_year_from_zip(names_zip, options["year"])
            latest_rows = _read_year_rows(names_zip, latest_year)
            include_sexes = {"M", "F"}
            if options["sex"] == "boy":
                include_sexes = {"M"}
            elif options["sex"] == "girl":
                include_sexes = {"F"}

            selected_rows = _select_latest_rows(
                latest_rows,
                max_per_sex=options["max_per_sex"],
                include_sexes=include_sexes,
            )
            return _build_stats(names_zip, latest_rows=selected_rows, latest_year=latest_year)


def _latest_year_from_stats(stats: list[SsaNameStats]) -> int | str:
    if not stats:
        return "unknown"
    return max(item.latest_year for item in stats)
