"""Seed a large deterministic multi-region baby name dataset."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Name

VOWELS = set("aeiou")
AGE_STYLES = ("classic", "modern", "timeless")
FEMALE_CONNECTORS = ("", "n", "l", "r")
MALE_CONNECTORS = ("", "r", "n", "v")
INTERNATIONAL_CONNECTORS = ("", "n", "l")


@dataclass(frozen=True)
class RegionSpec:
    label: str
    languages: tuple[str, ...]
    scripts: tuple[str, ...]
    girl_starts: tuple[str, ...]
    girl_ends: tuple[str, ...]
    boy_starts: tuple[str, ...]
    boy_ends: tuple[str, ...]


REGION_SPECS: tuple[RegionSpec, ...] = (
    RegionSpec(
        label="Spanish",
        languages=("es", "en"),
        scripts=("Latin",),
        girl_starts=("Adri", "Alma", "Bele", "Cami", "Daniel", "Elena", "Flor", "Ines", "Luci", "Mari"),
        girl_ends=("a", "ia", "ana", "ela", "ina", "ora", "isa", "ena", "ita", "aya"),
        boy_starts=("Alej", "Brun", "Dami", "Emili", "Ferna", "Gabr", "Javi", "Leona", "Mate", "Rafa"),
        boy_ends=("o", "io", "an", "el", "ar", "or", "as", "in", "iel", "ado"),
    ),
    RegionSpec(
        label="Russian",
        languages=("ru", "en"),
        scripts=("Cyrillic", "Latin"),
        girl_starts=("Alen", "Anas", "Dari", "Ekate", "Irin", "Ksen", "Lari", "Marin", "Nadi", "Tati"),
        girl_ends=("a", "ina", "eva", "iya", "ana", "ena", "ora", "ila", "ina", "usha"),
        boy_starts=("Alek", "Bori", "Demi", "Grigo", "Ily", "Konstan", "Maksi", "Niko", "Pave", "Vlade"),
        boy_ends=("a", "ei", "in", "ov", "an", "iy", "or", "ek", "mir", "islav"),
    ),
    RegionSpec(
        label="German",
        languages=("de", "en"),
        scripts=("Latin",),
        girl_starts=("Adel", "Anne", "Brig", "Clari", "Els", "Frie", "Gre", "Hel", "Lies", "Marl"),
        girl_ends=("a", "e", "ine", "ina", "hild", "gard", "liese", "traud", "run", "wina"),
        boy_starts=("Albre", "Bern", "Conra", "Diete", "Emme", "Frie", "Gerha", "Hein", "Ludw", "Wilhe"),
        boy_ends=("t", "hard", "rich", "mar", "win", "fried", "mann", "bert", "olf", "im"),
    ),
    RegionSpec(
        label="Arabic",
        languages=("ar", "en"),
        scripts=("Arabic", "Latin"),
        girl_starts=("Ami", "Dali", "Far", "Hadi", "Jami", "Kar", "Lay", "Nadi", "Rim", "Sam"),
        girl_ends=("a", "ah", "ia", "ina", "aya", "ara", "ana", "iya", "una", "ira"),
        boy_starts=("Azi", "Fari", "Hasa", "Jala", "Kari", "Mali", "Nasi", "Rafi", "Sami", "Tari"),
        boy_ends=("d", "n", "r", "m", "l", "q", "an", "im", "ir", "uf"),
    ),
    RegionSpec(
        label="Japanese",
        languages=("ja", "en"),
        scripts=("Kanji", "Hiragana", "Latin"),
        girl_starts=("Aki", "Emi", "Hana", "Kiyo", "Mado", "Mina", "Nao", "Rina", "Saki", "Yumi"),
        girl_ends=("ka", "ko", "na", "mi", "ri", "yo", "ha", "e", "sa", "no"),
        boy_starts=("Aki", "Da", "Haru", "Kazu", "Kiyo", "Masa", "Nobu", "Ren", "Shin", "Yuto"),
        boy_ends=("to", "shi", "ya", "ki", "ma", "ro", "ta", "nori", "hei", "suke"),
    ),
    RegionSpec(
        label="Indian",
        languages=("hi", "en"),
        scripts=("Devanagari", "Latin"),
        girl_starts=("Ana", "Diya", "Ira", "Kavi", "Leela", "Mahi", "Navi", "Pri", "Riya", "Sana"),
        girl_ends=("a", "ika", "ini", "ita", "ya", "ana", "isha", "ita", "ali", "ora"),
        boy_starts=("Aru", "Deva", "Isha", "Kri", "Manu", "Nila", "Pran", "Raja", "Soma", "Vira"),
        boy_ends=("n", "sh", "jit", "raj", "dev", "esh", "an", "il", "ay", "veer"),
    ),
    RegionSpec(
        label="Scandinavian",
        languages=("sv", "no", "da", "en"),
        scripts=("Latin",),
        girl_starts=("Astri", "Eli", "Frey", "Gun", "Ingri", "Kari", "Liva", "Signe", "Solve", "Yr"),
        girl_ends=("a", "d", "e", "hild", "dis", "lin", "veig", "run", "unn", "borg"),
        boy_starts=("Arne", "Bjor", "Eri", "Gunna", "Hal", "Iva", "Kjel", "Lei", "Sver", "Tore"),
        boy_ends=("n", "ar", "ik", "ald", "ulf", "vard", "mir", "son", "or", "vin"),
    ),
    RegionSpec(
        label="Greek",
        languages=("el", "en"),
        scripts=("Greek", "Latin"),
        girl_starts=("Aga", "Cali", "Deme", "Eleni", "Iphi", "Kalli", "Lysi", "Mela", "Sofi", "Theodo"),
        girl_ends=("a", "ia", "ina", "ora", "ope", "issa", "eni", "andra", "ara", "eia"),
        boy_starts=("Alexa", "Deme", "Geor", "Leona", "Niko", "Pana", "Stefa", "Theo", "Yanni", "Zeno"),
        boy_ends=("s", "os", "is", "on", "as", "ios", "ides", "ros", "dor", "los"),
    ),
    RegionSpec(
        label="Italian",
        languages=("it", "en"),
        scripts=("Latin",),
        girl_starts=("Ales", "Bianca", "Carla", "Donat", "Elisa", "Fiore", "Giuli", "Luci", "Mari", "Viole"),
        girl_ends=("a", "ia", "ina", "etta", "ella", "ora", "isa", "ana", "etta", "ina"),
        boy_starts=("Alessa", "Bruno", "Carlo", "Danie", "Emili", "Fabri", "Gabrie", "Lorenz", "Matte", "Vale"),
        boy_ends=("o", "io", "ino", "ello", "ano", "ore", "iano", "etto", "aro", "one"),
    ),
    RegionSpec(
        label="Yoruba",
        languages=("yo", "en"),
        scripts=("Latin",),
        girl_starts=("Ade", "Ayo", "Dara", "Ife", "Kemi", "Lola", "Mide", "Sade", "Temi", "Yemi"),
        girl_ends=("ola", "ayo", "ire", "funke", "yemi", "dara", "tayo", "lola", "sola", "wumi"),
        boy_starts=("Ade", "Ayo", "Bolu", "Dayo", "Ife", "Kunle", "Moyo", "Seyi", "Tolu", "Yemi"),
        boy_ends=("wale", "dare", "tayo", "mide", "sola", "bayo", "femi", "lola", "wumi", "niyi"),
    ),
)

INTERNATIONAL_STARTS = (
    "Ari", "Eli", "Lina", "Mira", "Nico", "Rafa", "Sami", "Tali", "Vera", "Zara",
    "Adri", "Mila", "Noa", "Luca", "Mina", "Kira", "Leo", "Maya", "Oren", "Sora",
)
INTERNATIONAL_ENDS = ("a", "ia", "ina", "ela", "ora", "io", "ian", "iel", "ara", "en")


def _merge_parts(prefix: str, suffix: str) -> str:
    """Merge syllable parts into a name-like token."""
    if not prefix:
        return suffix.title()
    if not suffix:
        return prefix.title()

    left = prefix.strip()
    right = suffix.strip()
    if left[-1].lower() == right[0].lower():
        merged = left + right[1:]
    elif left[-1].lower() in VOWELS and right[0].lower() in VOWELS:
        merged = left + right[1:]
    else:
        merged = left + right
    return merged.title()


def _length_category(name: str) -> str:
    size = len(name)
    if size <= 5:
        return "short"
    if size <= 8:
        return "medium"
    return "long"


def _historical_score(index: int, total: int) -> float:
    ratio = index / max(total - 1, 1)
    return round(0.25 + (ratio * 0.7), 2)


class Command(BaseCommand):
    help = (
        "Generate and seed a deterministic large baby-name dataset with "
        "at least 10 regions and a pool of international names."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--per-region",
            type=int,
            default=200,
            help="Number of names to generate per region (default: 200).",
        )
        parser.add_argument(
            "--international",
            type=int,
            default=200,
            help="Number of international names to generate (default: 200).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        per_region = max(options["per_region"], 200)
        international_count = max(options["international"], 200)

        existing = set(Name.objects.values_list("canonical_name", flat=True))
        to_create: list[Name] = []
        created_by_region: dict[str, int] = {}

        for spec in REGION_SPECS:
            region_names = self._build_region_dataset(spec, per_region, existing)
            created_by_region[spec.label] = len(region_names)
            existing.update(name.canonical_name for name in region_names)
            to_create.extend(region_names)

        international_names = self._build_international_dataset(international_count, existing)
        created_by_region["International"] = len(international_names)
        to_create.extend(international_names)

        if to_create:
            Name.objects.bulk_create(to_create, batch_size=500)

        self.stdout.write(self.style.SUCCESS(f"Created {len(to_create)} names."))
        for label, count in created_by_region.items():
            self.stdout.write(f"  {label}: {count}")

    def _build_region_dataset(
        self,
        spec: RegionSpec,
        count: int,
        existing: set[str],
    ) -> list[Name]:
        target_per_gender = count // 2
        region_names: list[Name] = []

        girl_entries = self._build_gendered_names(
            region=spec.label,
            starts=spec.girl_starts,
            ends=spec.girl_ends,
            gender="girl",
            count=target_per_gender,
            languages=spec.languages,
            scripts=spec.scripts,
            existing=existing,
        )
        region_names.extend(girl_entries)

        boy_entries = self._build_gendered_names(
            region=spec.label,
            starts=spec.boy_starts,
            ends=spec.boy_ends,
            gender="boy",
            count=count - len(region_names),
            languages=spec.languages,
            scripts=spec.scripts,
            existing=existing | {name.canonical_name for name in region_names},
        )
        region_names.extend(boy_entries)
        return region_names

    def _build_gendered_names(
        self,
        *,
        region: str,
        starts: tuple[str, ...],
        ends: tuple[str, ...],
        gender: str,
        count: int,
        languages: tuple[str, ...],
        scripts: tuple[str, ...],
        existing: set[str],
    ) -> list[Name]:
        names: list[Name] = []
        seen = set(existing)
        connectors = FEMALE_CONNECTORS if gender == "girl" else MALE_CONNECTORS
        combinations = list(product(starts, connectors, ends))

        for index, (start, connector, end) in enumerate(combinations):
            canonical = _merge_parts(_merge_parts(start, connector), end)
            if canonical in seen:
                continue

            age_style = AGE_STYLES[index % len(AGE_STYLES)]
            names.append(
                Name(
                    canonical_name=canonical,
                    display_name=canonical,
                    gender_usage=[gender],
                    origin_backgrounds=[region],
                    languages=list(languages),
                    scripts=list(scripts),
                    variants=[canonical],
                    length_category=_length_category(canonical),
                    age_style_category=age_style,
                    historical_significance_score=_historical_score(len(names), max(count, 1)),
                    semantic_summary=(
                        f"{canonical} is a {age_style} {region.lower()}-inspired {gender} name. "
                        "Seeded for regional recommendation, filtering, and multilingual matching demos."
                    ),
                    active=True,
                )
            )
            seen.add(canonical)
            if len(names) >= count:
                break

        if len(names) < count:
            raise ValueError(f"Unable to generate {count} unique names for {region} ({gender}).")

        return names

    def _build_international_dataset(self, count: int, existing: set[str]) -> list[Name]:
        names: list[Name] = []
        seen = set(existing)
        region_labels = [spec.label for spec in REGION_SPECS]
        language_map = {spec.label: spec.languages for spec in REGION_SPECS}

        for index, (start, connector, end) in enumerate(
            product(INTERNATIONAL_STARTS, INTERNATIONAL_CONNECTORS, INTERNATIONAL_ENDS)
        ):
            canonical = _merge_parts(_merge_parts(start, connector), end)
            if canonical in seen:
                continue

            region_a = region_labels[index % len(region_labels)]
            region_b = region_labels[(index + 3) % len(region_labels)]
            region_c = region_labels[(index + 6) % len(region_labels)]
            backgrounds = [region_a, region_b, region_c, "International"]

            languages = ["en", "de"]
            for region in (region_a, region_b, region_c):
                for language in language_map[region]:
                    if language not in languages:
                        languages.append(language)

            gender_usage = ["girl", "boy"] if index % 4 == 0 else (["girl"] if index % 2 == 0 else ["boy"])
            age_style = AGE_STYLES[index % len(AGE_STYLES)]

            names.append(
                Name(
                    canonical_name=canonical,
                    display_name=canonical,
                    gender_usage=gender_usage,
                    origin_backgrounds=backgrounds,
                    languages=languages,
                    scripts=["Latin"],
                    variants=[canonical],
                    length_category=_length_category(canonical),
                    age_style_category=age_style,
                    historical_significance_score=_historical_score(len(names), max(count, 1)),
                    semantic_summary=(
                        f"{canonical} is an {age_style} international name bridging {region_a}, "
                        f"{region_b}, and {region_c} naming patterns. Seeded for global discovery "
                        "and cross-cultural recommendation demos."
                    ),
                    active=True,
                )
            )
            seen.add(canonical)
            if len(names) >= count:
                break

        if len(names) < count:
            raise ValueError(f"Unable to generate {count} unique international names.")

        return names
