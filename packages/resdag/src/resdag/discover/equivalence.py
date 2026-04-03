"""Equivalence claim generation and querying.

An equivalence claim is a Claim of type EQUIVALENCE with exactly two
parents, asserting that they are semantically equivalent within a stated
scope. Scope is required — equivalence is always "equivalent under what
interpretation."

Equivalence claims are DAG nodes with their own provenance — they can
be signed, have evidence attached, and be verified themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from resdag.claim import Claim, ClaimType
from resdag.dag import DAG


@dataclass(frozen=True)
class EquivalenceAssertion:
    """Structured view of an equivalence claim.

    Provides typed access to equivalence-specific fields that are
    encoded in the claim text of an EQUIVALENCE-type Claim.
    """

    left_cid: str
    right_cid: str
    scope: str
    description: str = ""


def create_equivalence(
    cid_a: str,
    cid_b: str,
    scope: str,
    description: str = "",
    evidence: tuple[str, ...] = (),
    domain: tuple[str, ...] = (),
    author: str = "",
    timestamp: str = "",
) -> Claim:
    """Create an equivalence claim linking two claims.

    The two claims become parents of the equivalence node.
    Scope is required — equivalence is always scoped.
    """
    if not scope:
        raise ValueError("Scope is required for equivalence claims")

    payload: dict = {
        "description": description,
        "scope": scope,
    }

    kwargs: dict = {
        "claim": json.dumps(payload, sort_keys=True),
        "type": ClaimType.EQUIVALENCE,
        "parents": (cid_a, cid_b),
        "evidence": evidence,
        "domain": domain,
        "author": author,
    }
    if timestamp:
        kwargs["timestamp"] = timestamp
    return Claim(**kwargs)


def parse_equivalence(claim: Claim) -> EquivalenceAssertion:
    """Parse an equivalence Claim into a structured EquivalenceAssertion.

    Raises ValueError if the claim is not a valid equivalence claim.
    """
    if claim.type != ClaimType.EQUIVALENCE:
        raise ValueError(f"Not an equivalence claim: type is {claim.type.value}")
    if len(claim.parents) != 2:
        raise ValueError(
            f"Equivalence claim must have exactly 2 parents, got {len(claim.parents)}"
        )

    try:
        payload = json.loads(claim.claim)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid equivalence claim payload: {e}") from e

    if "scope" not in payload:
        raise ValueError("Equivalence claim payload missing required 'scope' field")

    return EquivalenceAssertion(
        left_cid=claim.parents[0],
        right_cid=claim.parents[1],
        scope=payload["scope"],
        description=payload.get("description", ""),
    )


def equivalence_cluster(cid: str, dag: DAG) -> set[str]:
    """Find all claims equivalent to a given claim (transitive).

    Walks equivalence edges transitively: if A≡B and B≡C, then
    querying A returns {A, B, C}. The starting claim is always
    included in the result.
    """
    cluster: set[str] = set()
    stack = [cid]

    # Build index: for each CID, which equivalence claims reference it?
    eq_by_parent: dict[str, list[str]] = {}
    for eq_cid in dag.store.list_cids():
        claim = dag.store.get(eq_cid)
        if claim.type == ClaimType.EQUIVALENCE and len(claim.parents) == 2:
            for parent in claim.parents:
                eq_by_parent.setdefault(parent, []).append(eq_cid)

    while stack:
        current = stack.pop()
        if current in cluster:
            continue
        cluster.add(current)
        for eq_cid in eq_by_parent.get(current, []):
            eq_claim = dag.store.get(eq_cid)
            for parent in eq_claim.parents:
                if parent not in cluster:
                    stack.append(parent)

    return cluster
