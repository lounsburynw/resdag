"""Parent suggestion via TF-IDF cosine similarity.

Suggests parent claims for new claims by computing text similarity
against all existing claims in the store. Zero external dependencies
(uses stdlib math/collections/re). Optional upgrade path via
sentence-transformers when available.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from resdag.claim import Claim
from resdag.storage.local import LocalStore


@dataclass
class Suggestion:
    """A suggested parent claim with similarity score."""

    cid: str
    score: float
    claim: Claim


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip git trailers, split on non-alphanumeric."""
    text = re.sub(r"\[(?:command|git_ref|git_dirty):[^\]]*\]", "", text)
    return re.findall(r"[a-z0-9]+", text.lower())


def _idf(documents: list[list[str]]) -> dict[str, float]:
    """Smooth inverse document frequency: log(1 + N/df) for each term."""
    n = len(documents)
    if n == 0:
        return {}
    df: Counter[str] = Counter()
    for doc in documents:
        df.update(set(doc))
    return {t: math.log(1.0 + n / count) for t, count in df.items()}


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Sparse TF-IDF vector from raw tokens."""
    counts = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return {}
    return {t: (c / total) * idf.get(t, 0.0) for t, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[k] * b[k] for k in shared)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def suggest_parents(
    store: LocalStore,
    claim_text: str,
    *,
    n: int = 3,
    domains: Sequence[str] = (),
    exclude_cids: set[str] | None = None,
) -> list[Suggestion]:
    """Suggest parent claims via TF-IDF cosine similarity.

    Returns up to *n* Suggestions sorted by descending score.
    Domain overlap boosts the score by 20% per shared tag.
    """
    exclude = exclude_cids or set()

    # Collect candidates with their tokens
    candidates: list[tuple[str, Claim, list[str]]] = []
    for cid in store.list_cids():
        if cid in exclude:
            continue
        claim = store.get(cid)
        tokens = _tokenize(claim.claim)
        if tokens:
            candidates.append((cid, claim, tokens))

    if not candidates:
        return []

    query_tokens = _tokenize(claim_text)
    if not query_tokens:
        return []

    # Build IDF from all documents (candidates + query)
    all_docs = [tokens for _, _, tokens in candidates] + [query_tokens]
    idf_map = _idf(all_docs)

    query_vec = _tfidf_vector(query_tokens, idf_map)

    domain_set = set(domains)

    scored: list[Suggestion] = []
    for cid, claim, tokens in candidates:
        vec = _tfidf_vector(tokens, idf_map)
        score = _cosine(query_vec, vec)
        if score > 0.0:
            # Boost for shared domain tags
            if domain_set and claim.domain:
                overlap = len(domain_set & set(claim.domain))
                score *= 1.0 + 0.2 * overlap
            scored.append(Suggestion(cid=cid, score=score, claim=claim))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:n]


def suggest_parents_embedding(
    store: LocalStore,
    claim_text: str,
    *,
    n: int = 3,
    exclude_cids: set[str] | None = None,
) -> list[Suggestion]:
    """Suggest parents via sentence-transformers embeddings.

    Falls back to TF-IDF if sentence-transformers is not installed.
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        return suggest_parents(store, claim_text, n=n, exclude_cids=exclude_cids)

    exclude = exclude_cids or set()

    candidates: list[tuple[str, Claim]] = []
    for cid in store.list_cids():
        if cid in exclude:
            continue
        candidates.append((cid, store.get(cid)))

    if not candidates:
        return []

    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [c.claim for _, c in candidates] + [claim_text]
    embeddings = model.encode(texts, convert_to_numpy=True)

    query_emb = embeddings[-1]
    candidate_embs = embeddings[:-1]

    norms = np.linalg.norm(candidate_embs, axis=1) * np.linalg.norm(query_emb)
    norms = np.where(norms == 0, 1.0, norms)
    similarities = np.dot(candidate_embs, query_emb) / norms

    scored: list[Suggestion] = []
    for i, (cid, claim) in enumerate(candidates):
        score = float(similarities[i])
        if score > 0.0:
            scored.append(Suggestion(cid=cid, score=score, claim=claim))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:n]


def format_suggestions(suggestions: list[Suggestion]) -> str:
    """Format suggestions for CLI display."""
    if not suggestions:
        return "No similar claims found."

    lines = ["Suggested parents:"]
    for i, s in enumerate(suggestions, 1):
        text = re.sub(r"\s*\[(?:command|git_ref|git_dirty):[^\]]*\]", "", s.claim.claim)
        if len(text) > 80:
            text = text[:77] + "..."
        type_badge = s.claim.type.value.upper()
        lines.append(f"  {i}. [{s.cid[:12]}] ({s.score:.3f}) [{type_badge}] {text}")
    return "\n".join(lines)
