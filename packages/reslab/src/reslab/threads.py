"""Research thread discovery and status computation.

A thread is a hypothesis plus all its descendants. Thread status is inferred
from descendant claim types:

  open      — no results, replications, or refutations yet
  confirmed — at least one replication and no refutations
  refuted   — at least one refutation
  mixed     — has both replications/verifications and refutations

`lab threads` lists threads with status and count.
`lab threads --open` returns only unresolved hypotheses (frontier for research loop).
"""

from __future__ import annotations

from dataclasses import dataclass

from resdag.claim import ClaimType
from resdag.dag import ClaimStore


@dataclass
class Thread:
    hypothesis_cid: str
    hypothesis_text: str
    status: str  # open | confirmed | refuted | mixed
    claim_count: int  # total descendants (including hypothesis)
    domains: list[str]
    first_date: str  # earliest timestamp in thread
    last_date: str  # latest timestamp in thread
    descendant_cids: list[str]


def discover_threads(store: ClaimStore) -> list[Thread]:
    """Find all hypothesis claims and compute their thread status."""
    cids = store.list_cids()
    if not cids:
        return []

    # Build children map (parent → children)
    children_map: dict[str, list[str]] = {}
    for cid in cids:
        claim = store.get(cid)
        for pcid in claim.parents:
            children_map.setdefault(pcid, []).append(cid)

    # Find all hypotheses
    hypothesis_cids = []
    for cid in cids:
        claim = store.get(cid)
        if claim.type is ClaimType.HYPOTHESIS:
            hypothesis_cids.append(cid)

    threads = []
    for h_cid in hypothesis_cids:
        h_claim = store.get(h_cid)

        # BFS to find all descendants
        descendants: list[str] = []
        visited: set[str] = {h_cid}
        stack = list(children_map.get(h_cid, []))
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            descendants.append(current)
            stack.extend(c for c in children_map.get(current, []) if c not in visited)

        # Compute status from descendant types
        has_replication = False
        has_refutation = False
        has_result = False

        for d_cid in descendants:
            d_claim = store.get(d_cid)
            if d_claim.type is ClaimType.REPLICATION:
                has_replication = True
            elif d_claim.type is ClaimType.REFUTATION:
                has_refutation = True
            elif d_claim.type is ClaimType.RESULT:
                has_result = True

        status = _infer_status(has_result, has_replication, has_refutation)

        # Collect domains and date range from all thread claims
        all_domains: set[str] = set()
        timestamps: list[str] = []

        for cid in [h_cid] + descendants:
            claim = store.get(cid)
            all_domains.update(claim.domain)
            if claim.timestamp:
                timestamps.append(claim.timestamp)

        timestamps.sort()

        threads.append(Thread(
            hypothesis_cid=h_cid,
            hypothesis_text=h_claim.claim,
            status=status,
            claim_count=1 + len(descendants),
            domains=sorted(all_domains),
            first_date=timestamps[0] if timestamps else "",
            last_date=timestamps[-1] if timestamps else "",
            descendant_cids=descendants,
        ))

    # Sort by last activity (most recent first)
    threads.sort(key=lambda t: t.last_date, reverse=True)
    return threads


def _infer_status(has_result: bool, has_replication: bool, has_refutation: bool) -> str:
    """Infer thread status from descendant claim types."""
    if has_refutation and has_replication:
        return "mixed"
    if has_refutation:
        return "refuted"
    if has_replication:
        return "confirmed"
    return "open"


def thread_to_dict(thread: Thread) -> dict:
    """Convert a Thread to a JSON-serializable dict."""
    return {
        "hypothesis_cid": thread.hypothesis_cid,
        "hypothesis_text": thread.hypothesis_text,
        "status": thread.status,
        "claim_count": thread.claim_count,
        "domains": thread.domains,
        "first_date": thread.first_date,
        "last_date": thread.last_date,
        "descendant_cids": thread.descendant_cids,
    }
