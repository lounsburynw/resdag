"""Gossip protocol for DAG sync.

Sync between two ClaimStores by diffing CID sets and transferring
missing claims in topological order. Content-addressing makes dedup
automatic; the append-only DAG guarantees conflict-free merges.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from resdag.dag import ClaimStore


@dataclass
class SyncResult:
    """Summary of a sync operation."""

    claims_pushed: int = 0
    evidence_pushed: int = 0


def diff(source: ClaimStore, target: ClaimStore) -> set[str]:
    """Return CIDs present in source but not in target."""
    return set(source.list_cids()) - set(target.list_cids())


def _topological_order(store: ClaimStore, cids: set[str]) -> list[str]:
    """Order a subset of CIDs so parents in the set come before children.

    Claims whose parents are outside the set (already in target or
    external roots) are treated as having zero in-set dependencies.
    """
    in_degree: dict[str, int] = {c: 0 for c in cids}
    children_of: dict[str, list[str]] = {c: [] for c in cids}

    for cid in cids:
        claim = store.get(cid)
        for parent in claim.parents:
            if parent in cids:
                in_degree[cid] += 1
                children_of[parent].append(cid)

    queue = deque(c for c in cids if in_degree[c] == 0)
    result: list[str] = []

    while queue:
        current = queue.popleft()
        result.append(current)
        for child in children_of[current]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(result) != len(cids):
        raise ValueError("Cycle detected in claims to sync")

    return result


def push(
    source: ClaimStore,
    target: ClaimStore,
    *,
    include_evidence: bool = False,
) -> SyncResult:
    """Push claims from source to target.

    Copies claims present in source but not in target, in topological
    order (parents before children). Content-addressing means duplicate
    writes are no-ops.
    """
    missing = diff(source, target)
    if not missing:
        return SyncResult()

    ordered = _topological_order(source, missing)
    result = SyncResult()

    for cid in ordered:
        claim = source.get(cid)
        target.put(claim)
        result.claims_pushed += 1

    if include_evidence:
        result.evidence_pushed = _sync_evidence(source, target)

    return result


def _sync_evidence(source: ClaimStore, target: ClaimStore) -> int:
    """Copy evidence from source to target. Returns count transferred."""
    if not (hasattr(source, "list_evidence_cids") and hasattr(target, "put_evidence")):
        return 0

    source_evidence = set(source.list_evidence_cids())
    target_evidence = (
        set(target.list_evidence_cids())
        if hasattr(target, "list_evidence_cids")
        else set()
    )

    count = 0
    for cid in source_evidence - target_evidence:
        data = source.get_evidence(cid)
        meta = source.get_evidence_meta(cid) if hasattr(source, "get_evidence_meta") else {}
        target.put_evidence(
            data,
            filename=meta.get("filename", ""),
            media_type=meta.get("media_type", ""),
        )
        count += 1

    return count


def sync(
    store_a: ClaimStore,
    store_b: ClaimStore,
    *,
    include_evidence: bool = False,
) -> SyncResult:
    """Bidirectional sync: ensure both stores have all claims from either.

    Content-addressing guarantees no duplicates.
    Append-only DAG guarantees no conflicts.
    """
    result_ab = push(store_a, store_b, include_evidence=include_evidence)
    result_ba = push(store_b, store_a, include_evidence=include_evidence)

    return SyncResult(
        claims_pushed=result_ab.claims_pushed + result_ba.claims_pushed,
        evidence_pushed=result_ab.evidence_pushed + result_ba.evidence_pushed,
    )
