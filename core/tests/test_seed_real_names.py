"""Tests for real-name SSA seeding."""

import csv
import zipfile

import pytest
from django.core.management import call_command

from core.models import Name


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
    fieldnames = ["name", "sex", "latest_year", "latest_rank", "latest_count", "first_year", "total_count"]
    boy_path = tmp_path / "boys.csv"
    girl_path = tmp_path / "girls.csv"

    with boy_path.open("w", newline="") as boy_file:
        writer = csv.DictWriter(boy_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "name": "Avery",
                    "sex": "M",
                    "latest_year": 2020,
                    "latest_rank": 1,
                    "latest_count": 100,
                    "first_year": 1880,
                    "total_count": 3000,
                },
                {
                    "name": "Liam",
                    "sex": "M",
                    "latest_year": 2020,
                    "latest_rank": 2,
                    "latest_count": 90,
                    "first_year": 1967,
                    "total_count": 2000,
                },
            ]
        )

    with girl_path.open("w", newline="") as girl_file:
        writer = csv.DictWriter(girl_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "name": "Avery",
                    "sex": "F",
                    "latest_year": 2020,
                    "latest_rank": 1,
                    "latest_count": 110,
                    "first_year": 1880,
                    "total_count": 3000,
                },
                {
                    "name": "Olivia",
                    "sex": "F",
                    "latest_year": 2020,
                    "latest_rank": 2,
                    "latest_count": 95,
                    "first_year": 1880,
                    "total_count": 2500,
                },
            ]
        )

    return boy_path, girl_path


@pytest.mark.django_db
def test_seed_real_names_loads_latest_real_names(ssa_source_zip):
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
    assert set(Name.objects.values_list("canonical_name", flat=True)) == {"Liam", "Olivia"}


@pytest.mark.django_db
def test_seed_real_names_loads_from_csv_files_without_network(ssa_source_csvs):
    boy_path, girl_path = ssa_source_csvs

    call_command("seed_real_names", source_csv=[str(boy_path), str(girl_path)])

    assert set(Name.objects.values_list("canonical_name", flat=True)) == {"Avery", "Liam", "Olivia"}
    avery = Name.objects.get(canonical_name="Avery")
    assert avery.gender_usage == ["boy", "girl"]
    assert "ranked #1 for boys" in avery.semantic_summary
    assert "ranked #1 for girls" in avery.semantic_summary


@pytest.mark.django_db
def test_seed_real_names_defaults_to_bundled_csv_files(monkeypatch, ssa_source_csvs):
    import core.management.commands.seed_real_names as module

    monkeypatch.setattr(module, "BUNDLED_CSV_PATHS", ssa_source_csvs)

    call_command("seed_real_names")

    assert set(Name.objects.values_list("canonical_name", flat=True)) == {"Avery", "Liam", "Olivia"}


@pytest.mark.django_db
def test_seed_real_names_filters_csv_by_requested_sex(ssa_source_csvs):
    boy_path, girl_path = ssa_source_csvs

    call_command("seed_real_names", source_csv=[str(boy_path), str(girl_path)], sex="boy")

    assert set(Name.objects.values_list("canonical_name", flat=True)) == {"Avery", "Liam"}
    assert Name.objects.get(canonical_name="Avery").gender_usage == ["boy"]


@pytest.fixture
def ssa_enriched_csvs(tmp_path):
    """CSV with the new LLM-fillable enriched columns populated."""
    fieldnames = [
        "name", "sex", "latest_year", "latest_rank", "latest_count", "first_year", "total_count",
        "origin_backgrounds", "languages", "scripts", "variants",
        "meaning", "age_style_category", "historical_significance_score", "semantic_summary",
    ]
    boy_path = tmp_path / "boys_enriched.csv"
    girl_path = tmp_path / "girls_enriched.csv"

    with boy_path.open("w", newline="") as boy_file:
        writer = csv.DictWriter(boy_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "name": "Liam", "sex": "M", "latest_year": 2020, "latest_rank": 1,
            "latest_count": 19659, "first_year": 1947, "total_count": 253444,
            "origin_backgrounds": "Irish|Hebrew",
            "languages": "en|ga|he",
            "scripts": "Latin|Hebrew",
            "variants": "Liam|William|Wilhelm",
            "meaning": "strong-willed warrior",
            "age_style_category": "timeless",
            "historical_significance_score": "0.85",
            "semantic_summary": "Liam is an Irish short form of William meaning strong-willed warrior.",
        })

    with girl_path.open("w", newline="") as girl_file:
        writer = csv.DictWriter(girl_file, fieldnames=fieldnames)
        writer.writeheader()
        # Fully blank enriched cells — should fall back to defaults
        writer.writerow({
            "name": "Olivia", "sex": "F", "latest_year": 2020, "latest_rank": 1,
            "latest_count": 17535, "first_year": 1880, "total_count": 489456,
            "origin_backgrounds": "", "languages": "", "scripts": "", "variants": "",
            "meaning": "", "age_style_category": "",
            "historical_significance_score": "", "semantic_summary": "",
        })

    return boy_path, girl_path


@pytest.mark.django_db
def test_seed_real_names_uses_enriched_csv_columns(ssa_enriched_csvs):
    """Enriched columns from the CSV should be applied to the Name record."""
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


@pytest.mark.django_db
def test_seed_real_names_falls_back_to_defaults_when_enriched_cells_blank(ssa_enriched_csvs):
    """Blank enriched cells should not blow up; defaults are used instead."""
    boy_path, girl_path = ssa_enriched_csvs

    call_command("seed_real_names", source_csv=[str(boy_path), str(girl_path)])

    olivia = Name.objects.get(canonical_name="Olivia")
    assert olivia.origin_backgrounds == ["United States"]
    assert olivia.languages == ["en"]
    assert olivia.scripts == ["Latin"]
    assert olivia.variants == ["Olivia"]
    # historical_significance_score should be computed, not the override
    assert 0.0 <= olivia.historical_significance_score <= 1.0
    assert "ranked #1 for girls" in olivia.semantic_summary
