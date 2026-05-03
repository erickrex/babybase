"""Management command to index names into Qdrant with 3 named vectors."""

import uuid

from django.core.management.base import BaseCommand
from django.utils import timezone
from qdrant_client.models import Distance, PointStruct, VectorParams

from core.models import Name, NameVectorIndexRef
from core.services.embeddings import (
    build_cross_cultural_text,
    build_phonetic_text,
    build_semantic_text,
    generate_embeddings_batch,
)
from core.services.qdrant_client import get_qdrant_client

EMBEDDING_VERSION = "v1"
COLLECTION_NAME = "names_global_v1"
VECTOR_DIM = 1536
BATCH_SIZE = 20


class Command(BaseCommand):
    help = "Create Qdrant collection and index all active names with 3 named vectors."

    def handle(self, *args, **options):
        client = get_qdrant_client()

        # Step 1: Ensure collection exists with 3 named vectors
        self._ensure_collection(client)

        # Step 2: Get names to index (skip already indexed with current version)
        names_to_index = self._get_names_to_index()

        if not names_to_index:
            self.stdout.write(self.style.SUCCESS("All names already indexed. Nothing to do."))
            return

        self.stdout.write(f"Indexing {len(names_to_index)} names...")

        # Step 3: Process in batches
        total_indexed = 0
        for i in range(0, len(names_to_index), BATCH_SIZE):
            batch = names_to_index[i : i + BATCH_SIZE]
            self._index_batch(client, batch)
            total_indexed += len(batch)
            self.stdout.write(f"  Indexed {total_indexed}/{len(names_to_index)}...")

        self.stdout.write(self.style.SUCCESS(f"Done. Indexed {total_indexed} names to Qdrant."))

    def _ensure_collection(self, client):
        """Create the collection if it doesn't exist."""
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if COLLECTION_NAME in collection_names:
            self.stdout.write(f"Collection '{COLLECTION_NAME}' already exists.")
            return

        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "semantic": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
                "phonetic_style": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
                "cross_cultural": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Created collection '{COLLECTION_NAME}'."))

    def _get_names_to_index(self) -> list:
        """Return active names not yet indexed with the current embedding version."""
        already_indexed_name_ids = set(
            NameVectorIndexRef.objects.filter(
                embedding_version=EMBEDDING_VERSION,
                qdrant_collection=COLLECTION_NAME,
            ).values_list("name_id", flat=True)
        )

        names = Name.objects.filter(active=True).exclude(id__in=already_indexed_name_ids)
        return list(names)

    def _index_batch(self, client, names: list):
        """Generate embeddings and upsert a batch of names to Qdrant."""
        # Build text inputs for all 3 vectors
        semantic_texts = [build_semantic_text(n) for n in names]
        phonetic_texts = [build_phonetic_text(n) for n in names]
        cross_cultural_texts = [build_cross_cultural_text(n) for n in names]

        # Generate embeddings in batches (each call handles max 20)
        semantic_embeddings = generate_embeddings_batch(semantic_texts)
        phonetic_embeddings = generate_embeddings_batch(phonetic_texts)
        cross_cultural_embeddings = generate_embeddings_batch(cross_cultural_texts)

        # Build Qdrant points and upsert
        points = []
        refs_to_create = []
        now = timezone.now()

        for idx, name in enumerate(names):
            point_id = str(uuid.uuid4())

            payload = {
                "name_id": str(name.id),
                "canonical_name": name.canonical_name,
                "gender_usage": name.gender_usage,
                "origin_backgrounds": name.origin_backgrounds,
                "languages": name.languages,
                "length_category": name.length_category,
                "age_style_category": name.age_style_category,
                "historical_importance": (
                    "high" if name.historical_significance_score > 0.7
                    else ("moderate" if name.historical_significance_score > 0.3 else "low")
                ),
                "international_score": (
                    min(1.0, len(name.languages or []) / 5.0)
                ),
                "active": name.active,
            }

            point = PointStruct(
                id=point_id,
                vector={
                    "semantic": semantic_embeddings[idx],
                    "phonetic_style": phonetic_embeddings[idx],
                    "cross_cultural": cross_cultural_embeddings[idx],
                },
                payload=payload,
            )
            points.append(point)

            refs_to_create.append(
                NameVectorIndexRef(
                    name=name,
                    qdrant_collection=COLLECTION_NAME,
                    qdrant_point_id=point_id,
                    embedding_version=EMBEDDING_VERSION,
                    indexed_at=now,
                )
            )

        # Upsert points to Qdrant
        client.upsert(collection_name=COLLECTION_NAME, points=points)

        # Store references in PostgreSQL
        NameVectorIndexRef.objects.bulk_create(refs_to_create)
