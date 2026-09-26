"""
Text -> vector embeddings.

Backends (settings.EMBEDDING_BACKEND):
  fastembed - BAAI/bge-small-en-v1.5 via ONNX, runs locally on CPU, 384 dimensions.
              Downloaded once into models_cache/. This is what the application uses.
  hashing   - a tiny bag-of-words fallback with the same dimension. No download, not semantic;
              only used by the test suite so tests run offline and fast.

All vectors are L2-normalised float32, so inner product == cosine similarity.
"""

import re
import threading
import zlib

import numpy as np
from django.conf import settings

DIMENSION = 384

_model = None
_model_lock = threading.Lock()


def _fastembed_model():
    """Load the model once per process (first call takes a few seconds)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from fastembed import TextEmbedding

                _model = TextEmbedding(settings.EMBEDDING_MODEL, cache_dir=str(settings.EMBEDDING_CACHE_DIR))
    return _model


def _hashing_vector(text):
    vector = np.zeros(DIMENSION, dtype=np.float32)
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vector[zlib.crc32(word.encode()) % DIMENSION] += 1.0
    return vector


def embed_texts(texts):
    """Return an (n, 384) array of normalised vectors."""
    if not texts:
        return np.zeros((0, DIMENSION), dtype=np.float32)
    if settings.EMBEDDING_BACKEND == "hashing":
        vectors = np.array([_hashing_vector(t) for t in texts], dtype=np.float32)
    else:
        vectors = np.array(list(_fastembed_model().embed(list(texts))), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def embed_text(text):
    return embed_texts([text])[0]


def to_bytes(vector):
    """Store a vector in a BinaryField."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_bytes(data):
    return np.frombuffer(data, dtype=np.float32)
