"""Management command to index names into Qdrant with 3 named vectors."""

import logging
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from qdrant_client.models import Distance, PointIdsList, PointStruct, VectorParams

from core.models import Name, NameVectorIndexRef, UserTasteVector
from core.services.embeddings import (
    EMBEDDING_DIM,
    build_cross_cultural_text,
    build_phonetic_text,
    build_semantic_text,
    generate_embeddings_batch,
)
from core.services.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)

EMBEDDING_VERSION = "nova-embed-text-v1"
COLLECTION_NAME = "names_global_v1"
VECTOR_DIM = EMBEDDING_DIM
BATCH_SIZE = 20


class Command(BaseCommand):
    help = "Create Qdrant collection and index all active names with 3 named vectors."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-recreate",
            action="store_true",
            default=False,
            help=(
                "Delete NameVectorIndexRef records for the target collection, recreate the Qdrant collection, "
                "and clear UserTasteVector records."
            ),
        )

    def handle(self, *args, **options):
        client = get_qdrant_client()
        force_recreate = options["force_recreate"]
        self.collection_name = settings.QDRANT_COLLECTION

        if force_recreate:
            self._force_recreate(client)

        # Step 1: Ensure collection exists with 3 named vectors at correct dimensions
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

    def _force_recreate(self, client):
        """Delete all index refs, recreate collection, and clear taste vectors."""
        # Delete index refs for the target Qdrant collection.
        deleted_refs, _ = NameVectorIndexRef.objects.filter(qdrant_collection=self.collection_name).delete()
        self.stdout.write(f"Deleted {deleted_refs} NameVectorIndexRef records.")
        logger.info("Force recreate: deleted %s NameVectorIndexRef records", deleted_refs)

        # Delete the Qdrant collection if it exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        if self.collection_name in collection_names:
            client.delete_collection(collection_name=self.collection_name)
            self.stdout.write(f"Deleted Qdrant collection '{self.collection_name}'.")
            logger.info("Force recreate: deleted Qdrant collection '%s'", self.collection_name)

        # Clear all UserTasteVector records
        deleted_taste, _ = UserTasteVector.objects.all().delete()
        self.stdout.write(f"Cleared {deleted_taste} UserTasteVector records.")
        logger.info("Force recreate: cleared %s UserTasteVector records", deleted_taste)

    def _ensure_collection(self, client):
        """Create the collection if it doesn't exist, or recreate if dimensions don't match."""
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name in collection_names:
            # Check if existing collection has the correct dimensions
            collection_info = client.get_collection(self.collection_name)
            vectors_config = collection_info.config.params.vectors

            needs_recreate = self._collection_requires_recreate(vectors_config)

            if needs_recreate:
                self.stdout.write(
                    f"Collection '{self.collection_name}' has wrong dimensions. Deleting and recreating."
                )
                logger.info(
                    "Collection '%s' has wrong vector dimensions, recreating with dim=%s",
                    self.collection_name,
                    VECTOR_DIM,
                )
                client.delete_collection(collection_name=self.collection_name)
                self._clear_index_refs_and_taste_vectors_for_rebuild()
            else:
                self.stdout.write(f"Collection '{self.collection_name}' already exists with correct dimensions.")
                return

        client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "semantic": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
                "phonetic_style": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
                "cross_cultural": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Created collection '{self.collection_name}'."))

    def _collection_requires_recreate(self, vectors_config) -> bool:
        """Return True when the collection is missing required named vectors or dimensions."""
        required_vectors = ("semantic", "phonetic_style", "cross_cultural")
        for vector_name in required_vectors:
            vector_config = vectors_config.get(vector_name) if hasattr(vectors_config, "get") else None
            if vector_config is None or vector_config.size != VECTOR_DIM:
                return True
        return False

    def _clear_index_refs_and_taste_vectors_for_rebuild(self) -> None:
        """Clear local vector metadata that points at a collection being rebuilt."""
        deleted_refs, _ = NameVectorIndexRef.objects.filter(qdrant_collection=self.collection_name).delete()
        deleted_taste, _ = UserTasteVector.objects.all().delete()
        logger.info(
            "Collection rebuild: cleared %s NameVectorIndexRef records and %s UserTasteVector records",
            deleted_refs,
            deleted_taste,
        )

    def _get_names_to_index(self) -> list:
        """Return active names not yet indexed with the current embedding version."""
        already_indexed_name_ids = set(
            NameVectorIndexRef.objects.filter(
                embedding_version=EMBEDDING_VERSION,
                qdrant_collection=self.collection_name,
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

        existing_refs = list(NameVectorIndexRef.objects.filter(name__in=names))
        existing_point_ids = [
            str(ref.qdrant_point_id) for ref in existing_refs if ref.qdrant_collection == self.collection_name
        ]
        if existing_point_ids:
            client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=existing_point_ids),
            )
        if existing_refs:
            NameVectorIndexRef.objects.filter(name__in=names).delete()

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
                    qdrant_collection=self.collection_name,
                    qdrant_point_id=point_id,
                    embedding_version=EMBEDDING_VERSION,
                    indexed_at=now,
                )
            )

        # Upsert points to Qdrant
        client.upsert(collection_name=self.collection_name, points=points)

        # Store references in PostgreSQL
        NameVectorIndexRef.objects.bulk_create(refs_to_create)
