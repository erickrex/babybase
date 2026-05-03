"""Management command to compute 2D projections for the Name Constellation map.

For MVP, uses a deterministic hash-based approach that clusters names by origin_backgrounds.
Real UMAP/t-SNE would require actual semantic vectors from Qdrant.
"""

import hashlib

from django.core.management.base import BaseCommand

from core.models import Name

# Origin clusters: map origin backgrounds to approximate x-center positions
ORIGIN_CLUSTERS = {
    "Spanish": (0.2, 0.3),
    "Latin": (0.25, 0.35),
    "Italian": (0.3, 0.25),
    "Portuguese": (0.22, 0.4),
    "French": (0.35, 0.3),
    "Greek": (0.4, 0.5),
    "Russian": (0.7, 0.3),
    "Slavic": (0.72, 0.35),
    "Ukrainian": (0.68, 0.28),
    "Polish": (0.65, 0.32),
    "Czech": (0.63, 0.38),
    "Serbian": (0.67, 0.42),
    "Bulgarian": (0.7, 0.45),
    "Germanic": (0.5, 0.6),
    "German": (0.5, 0.6),
    "English": (0.45, 0.65),
    "Scandinavian": (0.55, 0.7),
    "Norse": (0.58, 0.72),
    "Swedish": (0.56, 0.68),
    "Norwegian": (0.57, 0.74),
    "Danish": (0.54, 0.66),
    "Finnish": (0.6, 0.75),
    "Celtic": (0.4, 0.7),
    "Irish": (0.38, 0.72),
    "Scottish": (0.42, 0.71),
    "Welsh": (0.39, 0.68),
    "Arabic": (0.8, 0.5),
    "Persian": (0.82, 0.55),
    "Turkish": (0.75, 0.52),
    "Hebrew": (0.78, 0.45),
    "Japanese": (0.85, 0.75),
    "Chinese": (0.88, 0.7),
    "Korean": (0.87, 0.78),
    "Hindi": (0.82, 0.65),
    "Sanskrit": (0.8, 0.62),
    "African": (0.3, 0.8),
    "Swahili": (0.32, 0.82),
    "Hawaiian": (0.15, 0.75),
}

# Style offsets for y-axis variation
STYLE_OFFSETS = {
    "classic": -0.05,
    "modern": 0.05,
    "timeless": 0.0,
}


def _deterministic_jitter(name: str, seed: int = 0) -> tuple[float, float]:
    """Generate deterministic jitter from name hash."""
    h = hashlib.md5(f"{name}:{seed}".encode()).hexdigest()
    jx = (int(h[:8], 16) / 0xFFFFFFFF - 0.5) * 0.08
    jy = (int(h[8:16], 16) / 0xFFFFFFFF - 0.5) * 0.08
    return jx, jy


def compute_position(name: Name) -> tuple[float, float]:
    """Compute a deterministic 2D position for a name based on its metadata."""
    origins = name.origin_backgrounds or []

    # Average the cluster centers of all origins
    if origins:
        x_sum, y_sum, count = 0.0, 0.0, 0
        for origin in origins:
            if origin in ORIGIN_CLUSTERS:
                cx, cy = ORIGIN_CLUSTERS[origin]
                x_sum += cx
                y_sum += cy
                count += 1
            else:
                # Try partial match
                for key, (cx, cy) in ORIGIN_CLUSTERS.items():
                    if key.lower() in origin.lower() or origin.lower() in key.lower():
                        x_sum += cx
                        y_sum += cy
                        count += 1
                        break

        if count > 0:
            x = x_sum / count
            y = y_sum / count
        else:
            # Unknown origin — place in center
            x, y = 0.5, 0.5
    else:
        x, y = 0.5, 0.5

    # Apply style offset
    style_offset = STYLE_OFFSETS.get(name.age_style_category, 0.0)
    y += style_offset

    # Apply deterministic jitter based on canonical_name
    jx, jy = _deterministic_jitter(name.canonical_name)
    x += jx
    y += jy

    # Clamp to [0, 1]
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))

    return round(x, 6), round(y, 6)


class Command(BaseCommand):
    help = "Compute 2D projections for all names (deterministic hash-based clustering by origin)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute projections even for names that already have coordinates.",
        )

    def handle(self, *args, **options):
        force = options["force"]

        if force:
            names = Name.objects.filter(active=True)
        else:
            names = Name.objects.filter(active=True, x_2d__isnull=True)

        total = names.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("All names already have projections."))
            return

        updated = 0
        for name in names.iterator():
            x, y = compute_position(name)
            name.x_2d = x
            name.y_2d = y
            name.save(update_fields=["x_2d", "y_2d", "updated_at"])
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Computed projections for {updated} names.")
        )
