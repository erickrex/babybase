"""Tests for real-name SSA seeding."""

import csv
import zipfile

import pytest
from django.core.management import call_command

from core.models import Name

BASE_FIELDS = ["name", "sex", "latest_year", "latest_rank", "latest_count", "first_year", "total_count"]
ENRICHED_FIELDS = [
    *BASE_FIELDS,
    "origin_backgrounds",
    "languages",
    "scripts",
    "variants",
    "meaning",
    "age_style_category",
    "historical_significance_score",
    "semantic_summary",
]


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _base_row(name, sex, rank, count, first_year=1880, total_count=3000):
    return {
        "name": name,
        "sex": sex,
        "latest_year": 2020,
        "latest_rank": rank,
        "latest_count": count,
        "first_year": first_year,
        "total_count": total_count,
    }


def _name_set():
    return set(Name.objects.values_list("canonical_name", flat=True))


@pytest.fixture
def ssa_source_zip(tmp_path):
    zip_path = tmp_path / "names.zip"
    with zipfile.ZipFile(zip_path, "w") as names_zip:
        names_zip.writestr(
            "yob1920.txt",
            "\n".join(
                [
                    "Mary,F,70982",
                    "John,M,56913",
                    "James,M,47912",
                    "Frances,F,31707",
                    "Alden,M,100",
                ]
            ),
        )
        names_zip.writestr(
            "yob2020.txt",
            "\n".join(
                [
                    "Olivia,F,17535",
                    "Emma,F,15581",
                    "Liam,M,19659",
                    "Noah,M,18252",
                    "Alden,M,300",
                ]
            ),
        )
    return zip_path


@pytest.fixture
def ssa_source_csvs(tmp_path):
    boy_path = tmp_path / "boys.csv"
    girl_path = tmp_path / "girls.csv"
    _write_csv(
        boy_path,
        BASE_FIELDS,
        [
            _base_row("Avery", "M", 1, 100),
            _base_row("Liam", "M", 2, 90, first_year=1967, total_count=2000),
        ],
    )
    _write_csv(
        girl_path,
        BASE_FIELDS,
        [
            _base_row("Avery", "F", 1, 110),
            _base_row("Olivia", "F", 2, 95, total_count=2500),
        ],
    )
    return boy_path, girl_path


@pytest.fixture
def ssa_enriched_csvs(tmp_path):
    boy_path = tmp_path / "boys_enriched.csv"
    girl_path = tmp_path / "girls_enriched.csv"
    _write_csv(
        boy_path,
        ENRICHED_FIELDS,
        [
            {
                **_base_row("Liam", "M", 1, 19659, first_year=1947, total_count=253444),
                "origin_backgrounds": "Irish|Hebrew",
                "languages": "en|ga|he",
                "scripts": "Latin|Hebrew",
                "variants": "Liam|William|Wilhelm",
                "meaning": "strong-willed warrior",
                "age_style_category": "timeless",
                "historical_significance_score": "0.85",
                "semantic_summary": "Liam is an Irish short form of William meaning strong-willed warrior.",
            }
        ],
    )
    _write_csv(
        girl_path,
        ENRICHED_FIELDS,
        [
            {
                **_base_row("Olivia", "F", 1, 17535, total_count=489456),
                "origin_backgrounds": "",
                "languages": "",
                "scripts": "",
                "variants": "",
                "meaning": "",
                "age_style_category": "",
                "historical_significance_score": "",
                "semantic_summary": "",
            }
        ],
    )
    return boy_path, girl_path


@pytest.mark.django_db
def test_seed_real_names_loads_latest_real_names_from_zip(ssa_source_zip):
    call_command("seed_real_names", source_zip=str(ssa_source_zip), max_per_sex=2)

    assert list(Name.objects.order_by("canonical_name").values_list("canonical_name", flat=True)) == [
        "Emma",
        "Liam",
        "Noah",
        "Olivia",
    ]
    liam = Name.objects.get(canonical_name="Liam")
    assert liam.gender_usage == ["boy"]
    assert liam.origin_backgrounds == ["United States"]
    assert "SSA national baby-name data" in liam.semantic_summary


@pytest.mark.django_db
def test_seed_real_names_replace_removes_existing_names(ssa_source_zip):
    Name.objects.create(
        canonical_name="Adelrwina",
        display_name="Adelrwina",
        gender_usage=["girl"],
        origin_backgrounds=["Generated"],
        languages=["en"],
        scripts=["Latin"],
        variants=["Adelrwina"],
        length_category="long",
        age_style_category="modern",
        historical_significance_score=0.2,
        semantic_summary="Generated test name.",
        active=True,
    )

    call_command("seed_real_names", source_zip=str(ssa_source_zip), max_per_sex=1, replace=True)

    assert not Name.objects.filter(canonical_name="Adelrwina").exists()
    assert _name_set() == {"Liam", "Olivia"}


@pytest.mark.django_db
def test_seed_real_names_defaults_to_bundled_csv_files(monkeypatch, ssa_source_csvs):
    import core.management.commands.seed_real_names as module

    monkeypatch.setattr(module, "BUNDLED_CSV_PATHS", ssa_source_csvs)

    call_command("seed_real_names")

    assert _name_set() == {"Avery", "Liam", "Olivia"}
    avery = Name.objects.get(canonical_name="Avery")
    assert avery.gender_usage == ["boy", "girl"]
    assert "ranked #1 for boys" in avery.semantic_summary
    assert "ranked #1 for girls" in avery.semantic_summary


@pytest.mark.django_db
def test_seed_real_names_filters_csv_by_requested_sex(ssa_source_csvs):
    boy_path, girl_path = ssa_source_csvs

    call_command("seed_real_names", source_csv=[str(boy_path), str(girl_path)], sex="boy")

    assert _name_set() == {"Avery", "Liam"}
    assert Name.objects.get(canonical_name="Avery").gender_usage == ["boy"]


@pytest.mark.django_db
def test_seed_real_names_uses_enriched_columns_and_falls_back_when_blank(ssa_enriched_csvs):
    boy_path, girl_path = ssa_enriched_csvs

    call_command("seed_real_names", source_csv=[str(boy_path), str(girl_path)])

    liam = Name.objects.get(canonical_name="Liam")
    assert liam.origin_backgrounds == ["Irish", "Hebrew"]
    assert liam.languages == ["en", "ga", "he"]
    assert liam.scripts == ["Latin", "Hebrew"]
    assert liam.variants == ["Liam", "William", "Wilhelm"]
    assert liam.age_style_category == "timeless"
    assert liam.historical_significance_score == 0.85
    assert liam.semantic_summary == "Liam is an Irish short form of William meaning strong-willed warrior."

    olivia = Name.objects.get(canonical_name="Olivia")
    assert olivia.origin_backgrounds == ["United States"]
    assert olivia.languages == ["en"]
    assert olivia.scripts == ["Latin"]
    assert olivia.variants == ["Olivia"]
    assert 0.0 <= olivia.historical_significance_score <= 1.0
    assert "ranked #1 for girls" in olivia.semantic_summary
