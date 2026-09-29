"""
A small FAISS index wrapper.

Vectors are stored in the database (BinaryField) - the database is the source of truth.
The FAISS index is just an in-memory copy for fast search: it is built from the database on
first use and rebuilt automatically whenever the number of stored vectors changes
(e.g. another worker process saved a new complaint), or a watched row is added or deleted.

IndexFlatIP = exact inner-product search. With normalised vectors that is cosine similarity.
Exact search is fast enough for tens of thousands of vectors, so no approximate index is needed.

Without FAISS installed (the Vercel build leaves it out to keep the function bundle small), the
same exact search runs in numpy: a matrix-vector product, giving identical results.
"""

import threading

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None
from django.db.models.signals import post_delete, post_save

from .embeddings import DIMENSION, from_bytes


class ExactIndex:
    """numpy stand-in for faiss.IndexIDMap(faiss.IndexFlatIP(d)): exact inner-product search."""

    def __init__(self):
        self.ids = np.zeros(0, dtype=np.int64)
        self.vectors = np.zeros((0, DIMENSION), dtype=np.float32)

    @property
    def ntotal(self):
        return len(self.ids)

    def add_with_ids(self, vectors, ids):
        self.vectors = np.vstack([self.vectors, vectors])
        self.ids = np.concatenate([self.ids, ids])

    def search(self, queries, k, only_ids=None):
        scores = self.vectors @ queries[0]
        ids = self.ids
        if only_ids is not None:
            keep = np.isin(ids, np.asarray(only_ids, dtype=np.int64))
            scores, ids = scores[keep], ids[keep]
        top = np.argsort(-scores, kind="stable")[:k]
        return scores[top][None, :], ids[top][None, :]


class VectorIndex:
    def __init__(self, queryset_factory):
        """
        queryset_factory: function returning a queryset with a non-null `embedding` BinaryField.
        The model's primary key is used as the FAISS id.
        """
        self._queryset_factory = queryset_factory
        self._index = None
        self._lock = threading.Lock()

    def _rows(self):
        return self._queryset_factory().exclude(embedding__isnull=True)

    def _build(self):
        index = faiss.IndexIDMap(faiss.IndexFlatIP(DIMENSION)) if faiss else ExactIndex()
        ids, vectors = [], []
        for pk, data in self._rows().values_list("pk", "embedding"):
            ids.append(pk)
            vectors.append(from_bytes(data))
        if ids:
            index.add_with_ids(np.array(vectors, dtype=np.float32), np.array(ids, dtype=np.int64))
        return index

    def _current_index(self):
        expected = self._rows().count()
        with self._lock:
            if self._index is None or self._index.ntotal != expected:
                self._index = self._build()
            return self._index

    def search(self, vector, k=10, only_ids=None, exclude_ids=()):
        """
        Return [(pk, similarity), ...] best first.
        only_ids limits the search to those primary keys (e.g. one customer's complaints).
        """
        index = self._current_index()
        if index.ntotal == 0:
            return []
        if only_ids is not None:
            only_ids = [i for i in only_ids if i not in set(exclude_ids)]
            if not only_ids:
                return []

        k = min(k + len(exclude_ids), index.ntotal)
        query = np.array([vector], dtype=np.float32)
        if faiss is None:
            scores, ids = index.search(query, k, only_ids)
        else:
            params = None
            if only_ids is not None:
                params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(np.array(only_ids, dtype=np.int64)))
            scores, ids = index.search(query, k, params=params)
        return [
            (int(pk), float(score))
            for pk, score in zip(ids[0], scores[0])
            if pk != -1 and pk not in exclude_ids
        ]

    def invalidate(self):
        with self._lock:
            self._index = None

    def watch(self, model):
        """
        Rebuild after a row is added or deleted in this process. The count check above alone misses
        "one deleted, one added" (same count, different vectors), e.g. after a rolled-back
        transaction. Embeddings never change after creation, so ordinary saves are ignored.
        """
        def on_save(sender, instance, created, **kwargs):
            if created:
                self.invalidate()

        def on_delete(sender, instance, **kwargs):
            self.invalidate()

        post_save.connect(on_save, sender=model, weak=False)
        post_delete.connect(on_delete, sender=model, weak=False)
        return self
