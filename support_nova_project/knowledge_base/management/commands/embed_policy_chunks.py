"""
(Re)compute embeddings for knowledge-base chunks - e.g. after switching the embedding model.
Usage:  python manage.py embed_policy_chunks [--all]
"""

from django.core.management.base import BaseCommand

from knowledge_base.models import PolicyChunk
from knowledge_base.services import chunk_embedding_text
from vector_search.embeddings import embed_texts, to_bytes


class Command(BaseCommand):
    help = "Compute missing policy-chunk embeddings (or all of them with --all)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Recompute every chunk, not only missing ones")

    def handle(self, *args, **options):
        chunks = list(PolicyChunk.objects.all() if options["all"] else PolicyChunk.objects.filter(embedding__isnull=True))
        vectors = embed_texts([chunk_embedding_text(c.heading, c.text) for c in chunks])
        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = to_bytes(vector)
        PolicyChunk.objects.bulk_update(chunks, ["embedding"], batch_size=200)
        self.stdout.write(self.style.SUCCESS(f"Embedded {len(chunks)} chunks."))
