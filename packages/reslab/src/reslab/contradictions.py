"""Contradiction detection for research claims.

Detects when a new result contradicts an existing claim in the DAG.
Uses TF-IDF similarity to find related claims, then applies heuristic
contradiction signals: negation patterns, opposing quantitative results,
explicit refutation language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.suggest import _tokenize, _idf, _tfidf_vector, _cosine


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Contradiction:
    """A detected contradiction between two claims."""

    cid_a: str
    cid_b: str
    claim_a: Claim
    claim_b: Claim
    similarity: float
    signals: list[str]
    confidence: float  # 0.0 - 1.0

    def format_line(self) -> str:
        signals_str = ", ".join(self.signals)
        return (
            f"  {self.cid_a[:12]} vs {self.cid_b[:12]}  "
            f"(confidence: {self.confidence:.0%}, signals: {signals_str})"
        )

    def to_dict(self) -> dict:
        return {
            "cid_a": self.cid_a,
            "cid_b": self.cid_b,
            "text_a": self.claim_a.claim,
            "text_b": self.claim_b.claim,
            "similarity": round(self.similarity, 3),
            "signals": self.signals,
            "confidence": round(self.confidence, 3),
        }


# ---------------------------------------------------------------------------
# Contradiction signal detection
# ---------------------------------------------------------------------------

# Negation words/phrases
_NEGATION_WORDS = {
    "not", "no", "never", "neither", "nor", "none", "nothing",
    "doesn't", "don't", "didn't", "isn't", "aren't", "wasn't",
    "weren't", "won't", "wouldn't", "can't", "cannot", "shouldn't",
    "hasn't", "haven't", "hadn't",
}

# Antonym pairs that indicate opposing results
_ANTONYM_PAIRS = [
    ("increase", "decrease"),
    ("improve", "worsen"),
    ("improve", "degrade"),
    ("higher", "lower"),
    ("more", "less"),
    ("positive", "negative"),
    ("confirm", "refute"),
    ("support", "contradict"),
    ("succeed", "fail"),
    ("present", "absent"),
    ("significant", "insignificant"),
    ("converge", "diverge"),
    ("accelerate", "decelerate"),
    ("enable", "disable"),
    ("stable", "unstable"),
]


def _extract_quantities(text: str) -> list[tuple[str, float]]:
    """Extract (context, value) pairs from text.

    Looks for patterns like "accuracy 92%", "d=0.478", "loss 0.03".
    """
    results: list[tuple[str, float]] = []

    # Percentage: "accuracy 92%", "85% accuracy"
    for m in re.finditer(r"(\w+)\s+(\d+\.?\d*)\s*%", text):
        results.append((m.group(1).lower(), float(m.group(2))))
    for m in re.finditer(r"(\d+\.?\d*)\s*%\s+(\w+)", text):
        results.append((m.group(2).lower(), float(m.group(1))))

    # Equals: "d=0.478", "loss=0.03"
    for m in re.finditer(r"(\w+)\s*=\s*(\d+\.?\d*)", text):
        results.append((m.group(1).lower(), float(m.group(2))))

    return results


def _detect_signals(text_a: str, text_b: str) -> list[str]:
    """Detect contradiction signals between two claim texts."""
    signals: list[str] = []
    tokens_a = set(_tokenize(text_a))
    tokens_b = set(_tokenize(text_b))

    # Signal 1: Negation asymmetry — one has negation words, the other doesn't
    neg_a = tokens_a & _NEGATION_WORDS
    neg_b = tokens_b & _NEGATION_WORDS
    if bool(neg_a) != bool(neg_b):
        signals.append("negation_asymmetry")

    # Signal 2: Antonym pairs — both texts discuss the same thing with opposing terms
    lower_a = text_a.lower()
    lower_b = text_b.lower()
    for word1, word2 in _ANTONYM_PAIRS:
        if (word1 in lower_a and word2 in lower_b) or (word2 in lower_a and word1 in lower_b):
            signals.append(f"antonym:{word1}/{word2}")
            break  # One antonym pair is enough

    # Signal 3: Opposing quantitative results — same metric, different values
    quant_a = _extract_quantities(text_a)
    quant_b = _extract_quantities(text_b)
    for ctx_a, val_a in quant_a:
        for ctx_b, val_b in quant_b:
            if ctx_a == ctx_b and abs(val_a - val_b) > 0.01:
                signals.append(f"quantity_mismatch:{ctx_a}({val_a} vs {val_b})")
                break
        else:
            continue
        break

    # Signal 4: Explicit refutation language
    refutation_patterns = [
        r"\b(?:contradicts?|refutes?|disproves?|invalidates?|overturns?)\b",
        r"\b(?:contrary to|in contrast|inconsistent with|conflicts? with)\b",
        r"\b(?:failed to replicate|could not reproduce|does not hold)\b",
    ]
    for text in [text_a, text_b]:
        for p in refutation_patterns:
            if re.search(p, text, re.IGNORECASE):
                signals.append("refutation_language")
                break
        else:
            continue
        break

    return signals


def _confidence_from_signals(similarity: float, signals: list[str]) -> float:
    """Compute contradiction confidence from similarity and signals.

    High similarity + contradiction signals = high confidence.
    High similarity alone = low confidence (just related, not contradictory).
    """
    if not signals:
        return 0.0

    base = min(similarity, 1.0) * 0.4  # similarity contributes up to 0.4

    signal_score = 0.0
    for s in signals:
        if s == "negation_asymmetry":
            signal_score += 0.2
        elif s.startswith("antonym:"):
            signal_score += 0.3
        elif s.startswith("quantity_mismatch:"):
            signal_score += 0.3
        elif s == "refutation_language":
            signal_score += 0.2

    return min(base + signal_score, 1.0)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

_SIMILARITY_THRESHOLD = 0.15  # Minimum TF-IDF similarity to consider
_CONFIDENCE_THRESHOLD = 0.3   # Minimum confidence to report


def find_contradictions_for(
    store: LocalStore,
    cid: str,
    *,
    confidence_threshold: float = _CONFIDENCE_THRESHOLD,
) -> list[Contradiction]:
    """Find claims that contradict a specific claim.

    Parameters
    ----------
    store : LocalStore
        The claim store.
    cid : str
        CID of the claim to check.
    confidence_threshold : float
        Minimum confidence to include in results.

    Returns
    -------
    list[Contradiction]
        Detected contradictions sorted by confidence (descending).
    """
    target = store.get(cid)
    if target is None:
        raise ValueError(f"Claim {cid} not found")

    target_tokens = _tokenize(target.claim)
    if not target_tokens:
        return []

    # Collect all other claims
    candidates: list[tuple[str, Claim, list[str]]] = []
    for other_cid in store.list_cids():
        if other_cid == cid:
            continue
        claim = store.get(other_cid)
        # Skip non-result/hypothesis types (equivalence, refutation are meta)
        if claim.type not in (ClaimType.RESULT, ClaimType.HYPOTHESIS, ClaimType.REPLICATION):
            continue
        tokens = _tokenize(claim.claim)
        if tokens:
            candidates.append((other_cid, claim, tokens))

    if not candidates:
        return []

    # Build TF-IDF
    all_docs = [tokens for _, _, tokens in candidates] + [target_tokens]
    idf_map = _idf(all_docs)
    target_vec = _tfidf_vector(target_tokens, idf_map)

    contradictions: list[Contradiction] = []
    for other_cid, claim, tokens in candidates:
        vec = _tfidf_vector(tokens, idf_map)
        sim = _cosine(target_vec, vec)

        if sim < _SIMILARITY_THRESHOLD:
            continue

        signals = _detect_signals(target.claim, claim.claim)
        if not signals:
            continue

        confidence = _confidence_from_signals(sim, signals)
        if confidence >= confidence_threshold:
            contradictions.append(Contradiction(
                cid_a=cid,
                cid_b=other_cid,
                claim_a=target,
                claim_b=claim,
                similarity=sim,
                signals=signals,
                confidence=confidence,
            ))

    contradictions.sort(key=lambda c: c.confidence, reverse=True)
    return contradictions


def find_all_contradictions(
    store: LocalStore,
    *,
    confidence_threshold: float = _CONFIDENCE_THRESHOLD,
) -> list[Contradiction]:
    """Scan the full DAG for unresolved contradictions.

    Returns deduplicated contradiction pairs sorted by confidence.
    """
    all_cids = store.list_cids()
    seen_pairs: set[tuple[str, str]] = set()
    contradictions: list[Contradiction] = []

    # Only check result/hypothesis/replication claims
    checkable = []
    for cid in all_cids:
        claim = store.get(cid)
        if claim.type in (ClaimType.RESULT, ClaimType.HYPOTHESIS, ClaimType.REPLICATION):
            checkable.append(cid)

    for cid in checkable:
        for c in find_contradictions_for(store, cid, confidence_threshold=confidence_threshold):
            pair = tuple(sorted([c.cid_a, c.cid_b]))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                contradictions.append(c)

    contradictions.sort(key=lambda c: c.confidence, reverse=True)
    return contradictions


def check_new_claim(
    store: LocalStore,
    claim_text: str,
    claim_type: ClaimType = ClaimType.RESULT,
    domains: Sequence[str] = (),
    *,
    confidence_threshold: float = _CONFIDENCE_THRESHOLD,
) -> list[Contradiction]:
    """Check a new claim (not yet committed) for contradictions.

    Creates a temporary claim for comparison without persisting.
    """
    temp = Claim(
        claim=claim_text,
        type=claim_type,
        domain=tuple(domains),
    )
    temp_tokens = _tokenize(claim_text)
    if not temp_tokens:
        return []

    candidates: list[tuple[str, Claim, list[str]]] = []
    for cid in store.list_cids():
        claim = store.get(cid)
        if claim.type not in (ClaimType.RESULT, ClaimType.HYPOTHESIS, ClaimType.REPLICATION):
            continue
        tokens = _tokenize(claim.claim)
        if tokens:
            candidates.append((cid, claim, tokens))

    if not candidates:
        return []

    all_docs = [tokens for _, _, tokens in candidates] + [temp_tokens]
    idf_map = _idf(all_docs)
    temp_vec = _tfidf_vector(temp_tokens, idf_map)

    contradictions: list[Contradiction] = []
    for cid, claim, tokens in candidates:
        vec = _tfidf_vector(tokens, idf_map)
        sim = _cosine(temp_vec, vec)
        if sim < _SIMILARITY_THRESHOLD:
            continue

        signals = _detect_signals(claim_text, claim.claim)
        if not signals:
            continue

        confidence = _confidence_from_signals(sim, signals)
        if confidence >= confidence_threshold:
            contradictions.append(Contradiction(
                cid_a="(new)",
                cid_b=cid,
                claim_a=temp,
                claim_b=claim,
                similarity=sim,
                signals=signals,
                confidence=confidence,
            ))

    contradictions.sort(key=lambda c: c.confidence, reverse=True)
    return contradictions


def format_contradictions(contradictions: list[Contradiction]) -> str:
    """Format contradictions for CLI display."""
    if not contradictions:
        return "No contradictions found."

    lines = [f"Found {len(contradictions)} contradiction(s):"]
    for c in contradictions:
        lines.append(c.format_line())
        # Show truncated claim texts
        text_a = re.sub(r"\s*\[(?:command|git_ref|git_dirty):[^\]]*\]", "", c.claim_a.claim)
        text_b = re.sub(r"\s*\[(?:command|git_ref|git_dirty):[^\]]*\]", "", c.claim_b.claim)
        if len(text_a) > 70:
            text_a = text_a[:67] + "..."
        if len(text_b) > 70:
            text_b = text_b[:67] + "..."
        lines.append(f"    A: {text_a}")
        lines.append(f"    B: {text_b}")
    return "\n".join(lines)
