"""DAG health audit for reslab.

`lab audit` reports structural quality of the DAG:
  - type distribution
  - hypothesis coverage (fraction of results with a hypothesis ancestor)
  - orphan rate (parentless non-hypothesis claims)
  - branch ratio (claims with >1 child / total)
  - max linear run (longest unbranched chain)
  - refutation patterns

`lab audit --json` returns machine-readable output for the research loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from resdag.claim import ClaimType
from resdag.dag import ClaimStore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AuditReport:
    total_claims: int = 0
    type_distribution: dict[str, int] = field(default_factory=dict)
    hypothesis_count: int = 0
    hypothesis_coverage: float = 0.0  # fraction of results with hypothesis ancestor
    orphan_count: int = 0
    orphan_rate: float = 0.0
    branch_points: int = 0
    branch_ratio: float = 0.0
    max_linear_run: int = 0
    refutation_count: int = 0
    supersession_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_claims": self.total_claims,
            "type_distribution": self.type_distribution,
            "hypothesis_count": self.hypothesis_count,
            "hypothesis_coverage": self.hypothesis_coverage,
            "orphan_count": self.orphan_count,
            "orphan_rate": self.orphan_rate,
            "branch_points": self.branch_points,
            "branch_ratio": self.branch_ratio,
            "max_linear_run": self.max_linear_run,
            "refutation_count": self.refutation_count,
            "supersession_count": self.supersession_count,
            "warnings": self.warnings,
        }

    def format_text(self) -> str:
        """Format as human-readable text for CLI output."""
        if self.total_claims == 0:
            return "Empty store — no claims to audit."

        lines = [
            f"Claims:     {self.total_claims}",
            f"Types:      {', '.join(f'{t}={n}' for t, n in sorted(self.type_distribution.items()))}",
            f"Hypotheses: {self.hypothesis_count} ({_pct(self.hypothesis_coverage)} of results covered)",
            f"Orphans:    {self.orphan_count} ({_pct(self.orphan_rate)})",
            f"Branching:  {self.branch_points} branch points ({_pct(self.branch_ratio)})",
            f"Linear run: {self.max_linear_run} (longest unbranched chain)",
            f"Refutations:{self.refutation_count}",
            f"Supersessions:{self.supersession_count}",
        ]

        if self.warnings:
            lines.append("")
            for w in self.warnings:
                lines.append(f"⚠ {w}")

        return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{int(value * 100)}%"


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------

def audit_dag(store: ClaimStore) -> AuditReport:
    """Compute comprehensive DAG health metrics from a store."""
    cids = store.list_cids()
    total = len(cids)

    if total == 0:
        return AuditReport()

    # First pass: gather all claims and build indexes
    claims: dict[str, object] = {}
    children_map: dict[str, list[str]] = {}
    parent_count: dict[str, int] = {}
    type_dist: dict[str, int] = {}

    hypothesis_cids: set[str] = set()
    result_cids: list[str] = []
    orphans = 0
    refutations = 0
    supersessions = 0

    for cid in cids:
        claim = store.get(cid)
        claims[cid] = claim

        # Type distribution
        t = claim.type.value
        type_dist[t] = type_dist.get(t, 0) + 1

        # Track hypotheses and results
        if claim.type is ClaimType.HYPOTHESIS:
            hypothesis_cids.add(cid)
        if claim.type is ClaimType.RESULT:
            result_cids.append(cid)
        if claim.type is ClaimType.REFUTATION:
            refutations += 1
        if claim.type is ClaimType.SUPERSESSION:
            supersessions += 1

        # Orphan: no parents, not a hypothesis
        if not claim.parents and claim.type is not ClaimType.HYPOTHESIS:
            orphans += 1

        # Build children map and parent counts
        parent_count[cid] = len(claim.parents)
        for pcid in claim.parents:
            children_map.setdefault(pcid, []).append(cid)

    # Hypothesis coverage: fraction of results with at least one hypothesis ancestor
    covered_results = 0
    for rcid in result_cids:
        if _has_hypothesis_ancestor(rcid, claims, hypothesis_cids):
            covered_results += 1
    hypothesis_coverage = round(covered_results / len(result_cids), 2) if result_cids else 0.0

    # Branch ratio: claims with >1 child
    branch_points = sum(1 for cid in cids if len(children_map.get(cid, [])) > 1)
    branch_ratio = round(branch_points / total, 2)

    # Max linear run: longest chain of single-child, single-parent nodes
    max_run = _compute_max_linear_run(cids, claims, children_map)

    # Warnings
    warnings = _compute_warnings(
        total=total,
        hypothesis_count=len(hypothesis_cids),
        orphan_rate=round(orphans / total, 2),
        max_linear_run=max_run,
        refutation_count=refutations,
    )

    return AuditReport(
        total_claims=total,
        type_distribution=type_dist,
        hypothesis_count=len(hypothesis_cids),
        hypothesis_coverage=hypothesis_coverage,
        orphan_count=orphans,
        orphan_rate=round(orphans / total, 2),
        branch_points=branch_points,
        branch_ratio=branch_ratio,
        max_linear_run=max_run,
        refutation_count=refutations,
        supersession_count=supersessions,
        warnings=warnings,
    )


def _has_hypothesis_ancestor(cid: str, claims: dict, hypothesis_cids: set[str]) -> bool:
    """Check if a claim has at least one hypothesis in its ancestry."""
    visited: set[str] = set()
    stack = list(claims[cid].parents)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        if current in hypothesis_cids:
            return True
        if current in claims:
            stack.extend(p for p in claims[current].parents if p not in visited)
    return False


def _compute_max_linear_run(
    cids: list[str],
    claims: dict,
    children_map: dict[str, list[str]],
) -> int:
    """Find the longest chain where every node has at most 1 child and at most 1 parent."""
    # Start from nodes with 0 or 1 parent that have exactly 1 child
    # Follow the chain while the pattern holds
    max_run = 0

    for cid in cids:
        # Only start a run from a chain head: 0 parents, or parent has >1 child
        claim = claims[cid]
        children = children_map.get(cid, [])
        if len(children) != 1:
            continue

        # Check if this is a chain start
        is_start = len(claim.parents) == 0
        if not is_start:
            # Check if any parent has >1 child (meaning this is a branch point child)
            for pcid in claim.parents:
                if len(children_map.get(pcid, [])) > 1:
                    is_start = True
                    break
            # Also start if parent has >1 parent (not a simple chain)
            if not is_start and len(claim.parents) > 1:
                is_start = True

        if not is_start:
            continue

        # Walk the chain
        run = 1
        current = cid
        while True:
            ch = children_map.get(current, [])
            if len(ch) != 1:
                break
            next_cid = ch[0]
            next_claim = claims[next_cid]
            if len(next_claim.parents) != 1:
                break
            run += 1
            current = next_cid
        max_run = max(max_run, run)

    return max_run


def _compute_warnings(
    total: int,
    hypothesis_count: int,
    orphan_rate: float,
    max_linear_run: int,
    refutation_count: int,
) -> list[str]:
    """Generate warnings for degenerate DAG patterns."""
    warnings: list[str] = []

    if max_linear_run > 10:
        warnings.append(
            f"Longest linear chain is {max_linear_run} claims — consider branching."
        )

    if hypothesis_count == 0 and total > 5:
        warnings.append(
            "No hypotheses committed. Use `lab hypothesize` to declare predictions."
        )

    if orphan_rate > 0.3:
        warnings.append(
            f"High orphan rate ({_pct(orphan_rate)}) — many claims lack parent links."
        )

    if refutation_count == 0 and total > 10:
        warnings.append(
            "No refutations — consider challenging assumptions with `lab interpret --refuted`."
        )

    return warnings
