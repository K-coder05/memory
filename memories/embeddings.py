"""Every call to the embedding model lives here.

The model is the same one the RAG project used to fill Pinecone (gemini-embedding-001,
3072 dimensions). Gemini embeds documents and queries differently on purpose: pass the
right task type, or retrieval quality drops without any error.
"""
from functools import lru_cache

from django.conf import settings
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .models import EMBEDDING_DIM

MAX_BATCH = 100  # the API accepts at most 100 texts per request


@lru_cache(maxsize=1)
def _client():
    from google import genai  # imported lazily: the API process doesn't pay for it

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set (put it in .env)")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _is_rate_limited(exc):
    return getattr(exc, "code", None) == 429


@retry(retry=retry_if_exception(_is_rate_limited),
       wait=wait_exponential(multiplier=2, min=5, max=120),
       stop=stop_after_attempt(8), reraise=True)
def _embed(texts, task_type):
    from google.genai import types

    response = _client().models.embed_content(
        model=settings.EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    vectors = [list(e.values) for e in response.embeddings]
    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise ValueError(f"model gives {len(vectors[0])} dims, column expects {EMBEDDING_DIM}")
    return vectors


def embed_passages(texts):
    """Embed documents. Returns a list of plain Python lists of floats."""
    texts = list(texts)
    vectors = []
    for start in range(0, len(texts), MAX_BATCH):
        vectors.extend(_embed(texts[start:start + MAX_BATCH], "RETRIEVAL_DOCUMENT"))
    return vectors


def embed_query(text):
    return _embed([text], "RETRIEVAL_QUERY")[0]
