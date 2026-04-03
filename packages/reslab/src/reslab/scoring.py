"""Hypothesis quality scoring.

Scores hypotheses on four dimensions before execution:
  specificity   — quantitative prediction present?
  falsifiability — clear failure condition?
  grounding     — references prior results (parent links or CID mentions)?
  novelty       — not already tested in the DAG?

Returns a grade (A-F) with actionable feedback. Integrated into
commit-time validation in disciplined/strict modes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.suggest import _tokenize, _idf, _tfidf_vector, _cosine


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


@dataclass
class DimensionScore:
    name: str
    score: float  # 0.0 - 1.0
    reason: str


@dataclass
class HypothesisScore:
    grade: Grade
    total: float  # 0.0 - 1.0
    dimensions: list[DimensionScore] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        lines = [f"Grade: {self.grade.value} ({self.total:.0%})"]
        for d in self.dimensions:
            bar = "#" * int(d.score * 10) + "-" * (10 - int(d.score * 10))
            lines.append(f"  {d.name:<16} [{bar}] {d.score:.0%}  {d.reason}")
        if self.feedback:
            lines.append("")
            for f in self.feedback:
                lines.append(f"  -> {f}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "grade": self.grade.value,
            "total": round(self.total, 3),
            "dimensions": [
                {"name": d.name, "score": round(d.score, 3), "reason": d.reason}
                for d in self.dimensions
            ],
            "feedback": self.feedback,
        }


# ---------------------------------------------------------------------------
# Scoring heuristics
# ---------------------------------------------------------------------------

# Patterns that indicate quantitative predictions
_QUANTITY_PATTERNS = [
    r"\b\d+\.?\d*\s*%",              # percentages
    r"\b[<>=!]+\s*\d",               # comparisons (>, <, >=, !=, ==)
    r"\bd\s*[>=<]\s*\d",             # effect size d>0.5
    r"\b\d+x\b",                     # multipliers (4x, 10x)
    r"\b\d+\.?\d*\s*(?:ms|s|min|hr|hours?|steps?|epochs?|layers?)\b",  # units
    r"\bincreas|decreas|improv|reduc",  # directional
    r"\bbetween\s+\d+\s+and\s+\d+",  # ranges
]

# Patterns that indicate falsifiable conditions
_FALSIFIABLE_PATTERNS = [
    r"\bif wrong\b",
    r"\bif (?:this|the) (?:fails|doesn't|does not)\b",
    r"\bfailure condition\b",
    r"\bwould (?:disprove|refute|falsify)\b",
    r"\bexpect(?:ed)?\b.*\b(?:otherwise|instead)\b",
    r"\bpredict(?:ion)?:?\b",
    r"\bshould\b.*\b(?:not|never|always)\b",
    r"\bhypothes[ie]s\b",
]

# Template section markers for structured hypotheses
_STRUCTURE_MARKERS = ("Prediction:", "Rationale:", "If wrong:")


def _score_specificity(text: str) -> DimensionScore:
    """Score whether the hypothesis makes a specific, quantitative prediction."""
    hits = sum(1 for p in _QUANTITY_PATTERNS if re.search(p, text, re.IGNORECASE))

    if hits >= 3:
        return DimensionScore("specificity", 1.0, "multiple quantitative predictions")
    if hits == 2:
        return DimensionScore("specificity", 0.8, "quantitative prediction with context")
    if hits == 1:
        return DimensionScore("specificity", 0.5, "some quantitative element")

    # Check for directional predictions without numbers
    if re.search(r"\b(?:more|less|higher|lower|faster|slower|better|worse)\b", text, re.IGNORECASE):
        return DimensionScore("specificity", 0.3, "directional but not quantitative")

    return DimensionScore("specificity", 0.0, "no specific prediction")


def _score_falsifiability(text: str) -> DimensionScore:
    """Score whether the hypothesis has a clear failure condition."""
    # Structured template with "If wrong:" section is best
    if "If wrong:" in text:
        return DimensionScore("falsifiability", 1.0, "explicit failure condition (If wrong:)")

    hits = sum(1 for p in _FALSIFIABLE_PATTERNS if re.search(p, text, re.IGNORECASE))
    if hits >= 2:
        return DimensionScore("falsifiability", 0.8, "multiple falsifiable elements")
    if hits == 1:
        return DimensionScore("falsifiability", 0.5, "some falsifiable language")

    # Predictions imply falsifiability even without explicit conditions
    if re.search(r"\bpredict|expect|should\b", text, re.IGNORECASE):
        return DimensionScore("falsifiability", 0.3, "implicit prediction without failure condition")

    return DimensionScore("falsifiability", 0.0, "no falsifiable condition")


def _score_grounding(
    text: str,
    claim: Claim,
    store: LocalStore,
) -> DimensionScore:
    """Score whether the hypothesis references prior results."""
    signals = 0

    # Has parent links (strongest signal — explicit lineage)
    if claim.parents:
        signals += 2

    # References CIDs in text (e.g., "Session 74 showed...")
    if re.search(r"\b(?:bafkrei|bafy)[a-z2-7]{10,}", text, re.IGNORECASE):
        signals += 1

    # References session numbers or prior work
    if re.search(r"\b[Ss]ession\s+\d+\b", text):
        signals += 1

    # References specific prior findings with "because" or "since"
    if re.search(r"\b(?:because|since|given that|based on|building on)\b", text, re.IGNORECASE):
        signals += 1

    if signals >= 3:
        return DimensionScore("grounding", 1.0, "well-grounded in prior work")
    if signals == 2:
        return DimensionScore("grounding", 0.7, "references prior results")
    if signals == 1:
        return DimensionScore("grounding", 0.4, "some reference to prior work")

    return DimensionScore("grounding", 0.0, "no reference to prior results")


def _score_novelty(
    text: str,
    claim: Claim,
    store: LocalStore,
) -> DimensionScore:
    """Score whether this hypothesis tests something new (not already tested)."""
    # Build TF-IDF vectors for all existing hypotheses
    hypotheses: list[tuple[str, Claim, list[str]]] = []
    for cid in store.list_cids():
        existing = store.get(cid)
        if existing.type is ClaimType.HYPOTHESIS:
            tokens = _tokenize(existing.claim)
            if tokens:
                hypotheses.append((cid, existing, tokens))

    if not hypotheses:
        return DimensionScore("novelty", 1.0, "first hypothesis in DAG")

    query_tokens = _tokenize(text)
    if not query_tokens:
        return DimensionScore("novelty", 0.5, "could not analyze text")

    all_docs = [tokens for _, _, tokens in hypotheses] + [query_tokens]
    idf_map = _idf(all_docs)
    query_vec = _tfidf_vector(query_tokens, idf_map)

    max_sim = 0.0
    most_similar_cid = ""
    for cid, _, tokens in hypotheses:
        vec = _tfidf_vector(tokens, idf_map)
        sim = _cosine(query_vec, vec)
        if sim > max_sim:
            max_sim = sim
            most_similar_cid = cid

    if max_sim > 0.8:
        return DimensionScore("novelty", 0.0, f"very similar to {most_similar_cid[:12]}")
    if max_sim > 0.6:
        return DimensionScore("novelty", 0.3, f"overlaps with {most_similar_cid[:12]}")
    if max_sim > 0.4:
        return DimensionScore("novelty", 0.6, "somewhat related to existing hypotheses")

    return DimensionScore("novelty", 1.0, "tests something new")


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "specificity": 0.30,
    "falsifiability": 0.25,
    "grounding": 0.25,
    "novelty": 0.20,
}


def _grade_from_score(score: float) -> Grade:
    if score >= 0.8:
        return Grade.A
    if score >= 0.6:
        return Grade.B
    if score >= 0.4:
        return Grade.C
    if score >= 0.2:
        return Grade.D
    return Grade.F


def _build_feedback(dimensions: list[DimensionScore]) -> list[str]:
    """Generate actionable feedback from low-scoring dimensions."""
    feedback: list[str] = []
    by_name = {d.name: d for d in dimensions}

    s = by_name.get("specificity")
    if s and s.score < 0.5:
        feedback.append("Add a quantitative prediction (e.g., 'I predict d>0.5' or 'accuracy >80%')")

    f = by_name.get("falsifiability")
    if f and f.score < 0.5:
        feedback.append("Add 'If wrong:' section with explicit failure condition")

    g = by_name.get("grounding")
    if g and g.score < 0.5:
        feedback.append("Link to prior results with --parent or reference specific prior findings")

    n = by_name.get("novelty")
    if n and n.score < 0.3:
        feedback.append("This hypothesis is very similar to an existing one — consider differentiating or testing a new angle")

    return feedback


def score_hypothesis(
    store: LocalStore,
    cid: str,
) -> HypothesisScore:
    """Score a hypothesis claim on quality dimensions.

    Parameters
    ----------
    store : LocalStore
        The claim store.
    cid : str
        CID of the hypothesis claim to score.

    Returns
    -------
    HypothesisScore
        Grade, dimension scores, and actionable feedback.

    Raises
    ------
    ValueError
        If the CID doesn't exist or isn't a hypothesis.
    """
    claim = store.get(cid)
    if claim is None:
        raise ValueError(f"Claim {cid} not found")
    if claim.type is not ClaimType.HYPOTHESIS:
        raise ValueError(f"Claim {cid} is {claim.type.value}, not hypothesis")

    text = claim.claim

    dimensions = [
        _score_specificity(text),
        _score_falsifiability(text),
        _score_grounding(text, claim, store),
        _score_novelty(text, claim, store),
    ]

    total = sum(d.score * _WEIGHTS[d.name] for d in dimensions)
    grade = _grade_from_score(total)
    feedback = _build_feedback(dimensions)

    return HypothesisScore(
        grade=grade,
        total=total,
        dimensions=dimensions,
        feedback=feedback,
    )


def score_hypothesis_text(
    store: LocalStore,
    text: str,
    parents: Sequence[str] = (),
) -> HypothesisScore:
    """Score hypothesis text before committing (preview mode).

    Creates a temporary Claim object for scoring without persisting.
    """
    claim = Claim(
        claim=text,
        type=ClaimType.HYPOTHESIS,
        parents=tuple(parents),
    )

    dimensions = [
        _score_specificity(text),
        _score_falsifiability(text),
        _score_grounding(text, claim, store),
        _score_novelty(text, claim, store),
    ]

    total = sum(d.score * _WEIGHTS[d.name] for d in dimensions)
    grade = _grade_from_score(total)
    feedback = _build_feedback(dimensions)

    return HypothesisScore(
        grade=grade,
        total=total,
        dimensions=dimensions,
        feedback=feedback,
    )
