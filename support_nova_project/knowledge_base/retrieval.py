"""
Policy retrieval (SRS Step 25): find the most relevant *usable* policy chunks for some text.

Three modes, all traceable back to document + version + section:
  keyword   score = matches in the text + 2 x matches in the heading (+3 if the category matches)
  semantic  cosine similarity of sentence embeddings, searched with FAISS
  hybrid    both lists merged with Reciprocal Rank Fusion: each list adds 1 / (60 + rank).
            Keyword search catches exact terms ("restocking fee"); semantic search catches
            meaning ("my parcel never showed up" -> Lost Parcels).
Only chunks of active, currently effective, non-expired documents are ever returned, so an
outdated policy can never ground a resolution. Ties go to the higher-precedence document.
"""

import re
from datetime import date

from django.db.models import Q

from vector_search.embeddings import embed_text
from vector_search.index import VectorIndex

from .models import DocumentStatus, PolicyChunk

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "have", "has", "was", "were", "are", "but",
    "not", "you", "your", "our", "from", "they", "them", "been", "will", "would", "could",
    "should", "into", "about", "after", "before", "when", "what", "which", "there", "their",
    "please", "also", "just", "still", "very", "can", "cannot", "did", "does", "any", "all",
}
RRF_K = 60

chunk_index = VectorIndex(lambda: PolicyChunk.objects.all()).watch(PolicyChunk)


def extract_terms(text, limit=15):
    words = re.findall(r"[a-z0-9]+", text.lower())
    terms = []
    for w in words:
        if len(w) >= 3 and w not in STOPWORDS and w not in terms:
            terms.append(w)
    return terms[:limit]


def usable_chunks():
    """Chunks from documents that are active, already effective and not expired."""
    today = date.today()
    return PolicyChunk.objects.select_related("document", "document__category").filter(
        Q(document__expiry_date__isnull=True) | Q(document__expiry_date__gte=today),
        document__status=DocumentStatus.ACTIVE,
        document__effective_date__lte=today,
    )


def _sort_key(score, chunk):
    return (-score, chunk.document.precedence, -chunk.document.effective_date.toordinal())


def keyword_search(query, category_code=None, limit=5):
    terms = extract_terms(query)
    if not terms:
        return []

    any_term = Q()
    for term in terms:
        any_term |= Q(text__icontains=term) | Q(heading__icontains=term)

    results = []
    for chunk in usable_chunks().filter(any_term):
        text, heading = chunk.text.lower(), chunk.heading.lower()
        score = sum(text.count(t) for t in terms) + 2 * sum(t in heading for t in terms)
        if category_code and chunk.document.category and chunk.document.category.code == category_code:
            score += 3
        results.append((score, chunk))
    results.sort(key=lambda r: _sort_key(*r))
    return [{"score": score, "chunk": chunk} for score, chunk in results[:limit]]


# Kept for callers written before semantic search existed.
search_policies = keyword_search


def semantic_search(query, limit=5):
    usable = usable_chunks()
    ids = list(usable.values_list("pk", flat=True))
    if not ids or not query.strip():
        return []
    hits = chunk_index.search(embed_text(query), k=limit, only_ids=ids)
    chunks = usable.in_bulk([pk for pk, _ in hits])
    return [{"score": round(score, 3), "chunk": chunks[pk]} for pk, score in hits if pk in chunks]


def hybrid_search(query, category_code=None, limit=6):
    keyword = keyword_search(query, category_code=category_code, limit=limit * 2)
    semantic = semantic_search(query, limit=limit * 2)

    fused = {}  # chunk pk -> [rrf score, chunk, keyword score, semantic score]
    for rank, hit in enumerate(keyword, start=1):
        entry = fused.setdefault(hit["chunk"].pk, [0.0, hit["chunk"], None, None])
        entry[0] += 1 / (RRF_K + rank)
        entry[2] = hit["score"]
    for rank, hit in enumerate(semantic, start=1):
        entry = fused.setdefault(hit["chunk"].pk, [0.0, hit["chunk"], None, None])
        entry[0] += 1 / (RRF_K + rank)
        entry[3] = hit["score"]

    ranked = sorted(fused.values(), key=lambda e: _sort_key(e[0], e[1]))[:limit]
    return [
        {"score": round(rrf, 4), "chunk": chunk, "keyword_score": kw, "semantic_score": sem}
        for rrf, chunk, kw, sem in ranked
    ]


SEARCH_MODES = {"keyword": keyword_search, "semantic": semantic_search, "hybrid": hybrid_search}
