"""Cost tracking and cost-aware experiment selection.

Tracks experiment costs via claim trailers (cost_seconds, cost_usd).
Estimates cost/benefit ratio for hypotheses before execution.
Reports spend by thread and domain via `lab audit --costs`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from resdag.claim import ClaimType
from resdag.storage.local import LocalStore

from reslab.scoring import score_hypothesis, Grade  # noqa: E402 (circular-safe)
from reslab.threads import discover_threads


# ---------------------------------------------------------------------------
# Trailer parsing
# ---------------------------------------------------------------------------

_TRAILER_RE = re.compile(r"\[([^\]]+)\]\s*$")
_COST_SECONDS_RE = re.compile(r"cost_seconds:\s*([\d.]+)")
_COST_USD_RE = re.compile(r"cost_usd:\s*([\d.]+)")


@dataclass
class CostData:
    """Parsed cost data from a claim's trailer."""

    seconds: float | None = None
    usd: float | None = None

    @property
    def has_cost(self) -> bool:
        return self.seconds is not None or self.usd is not None


def parse_cost_trailer(claim_text: str) -> CostData:
    """Extract cost data from a claim text trailer."""
    m = _TRAILER_RE.search(claim_text)
    if not m:
        return CostData()

    trailer = m.group(1)
    data = CostData()

    sm = _COST_SECONDS_RE.search(trailer)
    if sm:
        data.seconds = float(sm.group(1))

    um = _COST_USD_RE.search(trailer)
    if um:
        data.usd = float(um.group(1))

    return data


def format_cost_trailer(seconds: float | None = None, usd: float | None = None) -> str:
    """Build a trailer string for cost data.

    Returns something like "cost_seconds: 1800, cost_usd: 0.45".
    To be appended to existing trailers in workflow._make_claim.
    """
    parts: list[str] = []
    if seconds is not None:
        parts.append(f"cost_seconds: {seconds}")
    if usd is not None:
        parts.append(f"cost_usd: {usd}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Cost estimate for a hypothesis
# ---------------------------------------------------------------------------

@dataclass
class CostEstimate:
    """Cost/benefit analysis for a hypothesis."""

    hypothesis_cid: str
    hypothesis_text: str
    quality_grade: Grade
    quality_score: float
    thread_depth: int         # how many results already on this thread
    estimated_value: float    # 0.0 - 1.0 (information gain estimate)
    recommendation: str       # "recommended", "marginal", "not recommended"

    def format_text(self) -> str:
        lines = [
            f"Hypothesis: {self.hypothesis_cid[:12]}",
            f"Quality:    {self.quality_grade.value} ({self.quality_score:.0%})",
            f"Thread:     {self.thread_depth} prior results",
            f"Value:      {self.estimated_value:.0%} estimated information gain",
            f"Verdict:    {self.recommendation}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "hypothesis_cid": self.hypothesis_cid,
            "quality_grade": self.quality_grade.value,
            "quality_score": round(self.quality_score, 3),
            "thread_depth": self.thread_depth,
            "estimated_value": round(self.estimated_value, 3),
            "recommendation": self.recommendation,
        }


def estimate_cost(store: LocalStore, hypothesis_cid: str) -> CostEstimate:
    """Estimate information gain for executing a hypothesis.

    Combines hypothesis quality score with thread context (diminishing
    returns as thread depth increases).
    """
    claim = store.get(hypothesis_cid)
    if claim is None:
        raise ValueError(f"Claim {hypothesis_cid} not found")
    if claim.type is not ClaimType.HYPOTHESIS:
        raise ValueError(f"Claim {hypothesis_cid} is {claim.type.value}, not hypothesis")

    # Get quality score
    quality = score_hypothesis(store, hypothesis_cid)

    # Get thread depth (count results in the thread rooted at this hypothesis)
    thread_depth = 0
    threads = discover_threads(store)
    for t in threads:
        if t.hypothesis_cid == hypothesis_cid:
            # Count result descendants
            thread_depth = sum(
                1 for cid in t.descendant_cids
                if store.get(cid).type is ClaimType.RESULT
            )
            break

    # Information gain: quality * diminishing returns
    # First result on a thread is most valuable, then it tapers off
    diminishing = 1.0 / (1.0 + thread_depth * 0.3)
    value = quality.total * diminishing

    # Recommendation
    if value >= 0.5:
        recommendation = "recommended"
    elif value >= 0.25:
        recommendation = "marginal"
    else:
        recommendation = "not recommended"

    return CostEstimate(
        hypothesis_cid=hypothesis_cid,
        hypothesis_text=claim.claim,
        quality_grade=quality.grade,
        quality_score=quality.total,
        thread_depth=thread_depth,
        estimated_value=value,
        recommendation=recommendation,
    )


# ---------------------------------------------------------------------------
# Cost audit
# ---------------------------------------------------------------------------

@dataclass
class CostReport:
    """Aggregate cost metrics across the DAG."""

    total_seconds: float = 0.0
    total_usd: float = 0.0
    claims_with_costs: int = 0
    total_result_claims: int = 0
    cost_by_domain: dict[str, float] = field(default_factory=dict)  # domain → usd
    cost_by_thread: dict[str, float] = field(default_factory=dict)  # hypothesis_cid[:12] → usd
    seconds_by_domain: dict[str, float] = field(default_factory=dict)
    seconds_by_thread: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_seconds": round(self.total_seconds, 1),
            "total_usd": round(self.total_usd, 4),
            "claims_with_costs": self.claims_with_costs,
            "total_result_claims": self.total_result_claims,
            "cost_by_domain": {k: round(v, 4) for k, v in self.cost_by_domain.items()},
            "cost_by_thread": {k: round(v, 4) for k, v in self.cost_by_thread.items()},
            "seconds_by_domain": {k: round(v, 1) for k, v in self.seconds_by_domain.items()},
            "seconds_by_thread": {k: round(v, 1) for k, v in self.seconds_by_thread.items()},
        }

    def format_text(self) -> str:
        if self.claims_with_costs == 0:
            return "No cost data recorded. Use --cost-seconds or --cost-usd with `lab execute`."

        lines = [
            f"Cost tracking: {self.claims_with_costs}/{self.total_result_claims} results have cost data",
            f"Total time:    {_fmt_seconds(self.total_seconds)}",
            f"Total spend:   ${self.total_usd:.2f}",
        ]

        if self.seconds_by_domain:
            lines.append("\nTime by domain:")
            for domain, secs in sorted(self.seconds_by_domain.items(), key=lambda x: -x[1]):
                lines.append(f"  {domain:<20} {_fmt_seconds(secs)}")

        if self.cost_by_domain:
            lines.append("\nSpend by domain:")
            for domain, usd in sorted(self.cost_by_domain.items(), key=lambda x: -x[1]):
                lines.append(f"  {domain:<20} ${usd:.2f}")

        if self.seconds_by_thread:
            lines.append("\nTime by thread:")
            for tid, secs in sorted(self.seconds_by_thread.items(), key=lambda x: -x[1]):
                lines.append(f"  {tid:<14} {_fmt_seconds(secs)}")

        return "\n".join(lines)


def _fmt_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.1f}h"


def audit_costs(store: LocalStore) -> CostReport:
    """Compute cost metrics across the DAG."""
    report = CostReport()

    # Build thread membership map: cid → hypothesis_cid
    threads = discover_threads(store)
    cid_to_thread: dict[str, str] = {}
    for t in threads:
        for dcid in t.descendant_cids:
            cid_to_thread[dcid] = t.hypothesis_cid

    for cid in store.list_cids():
        claim = store.get(cid)
        if claim.type is not ClaimType.RESULT:
            continue
        report.total_result_claims += 1

        cost = parse_cost_trailer(claim.claim)
        if not cost.has_cost:
            continue

        report.claims_with_costs += 1

        if cost.seconds is not None:
            report.total_seconds += cost.seconds
            for d in claim.domain:
                report.seconds_by_domain[d] = report.seconds_by_domain.get(d, 0.0) + cost.seconds
            thread_key = cid_to_thread.get(cid, "(orphan)")[:12]
            report.seconds_by_thread[thread_key] = report.seconds_by_thread.get(thread_key, 0.0) + cost.seconds

        if cost.usd is not None:
            report.total_usd += cost.usd
            for d in claim.domain:
                report.cost_by_domain[d] = report.cost_by_domain.get(d, 0.0) + cost.usd
            thread_key = cid_to_thread.get(cid, "(orphan)")[:12]
            report.cost_by_thread[thread_key] = report.cost_by_thread.get(thread_key, 0.0) + cost.usd

    return report
