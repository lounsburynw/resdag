"""DAG operations: add, query, traverse."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from resdag.claim import Claim


@runtime_checkable
class ClaimStore(Protocol):
    """Structural interface for what DAG needs from a storage backend."""

    def put(self, claim: Claim) -> str: ...
    def get(self, cid: str) -> Claim: ...
    def has(self, cid: str) -> bool: ...
    def list_cids(self) -> list[str]: ...


class DAG:
    """Directed acyclic graph of claims backed by a ClaimStore.

    Provides parent-validated insertion, ancestor/descendant traversal,
    root/leaf queries, and independent convergence detection.
    """

    def __init__(self, store: ClaimStore) -> None:
        self.store = store

    def add(self, claim: Claim) -> str:
        """Add a claim to the DAG. All parents must already exist in the store."""
        for parent_cid in claim.parents:
            if not self.store.has(parent_cid):
                raise KeyError(f"Parent not found: {parent_cid}")
        return self.store.put(claim)

    def get(self, cid: str) -> Claim:
        """Retrieve a claim by CID."""
        return self.store.get(cid)

    def ancestors(self, cid: str) -> set[str]:
        """Return all ancestor CIDs (transitive parents), excluding the starting node."""
        visited: set[str] = set()
        stack = list(self.store.get(cid).parents)
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            claim = self.store.get(current)
            stack.extend(p for p in claim.parents if p not in visited)
        return visited

    def descendants(self, cid: str) -> set[str]:
        """Return all descendant CIDs (transitive children), excluding the starting node."""
        children_of = self._children_map()
        visited: set[str] = set()
        stack = list(children_of.get(cid, []))
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(c for c in children_of.get(current, []) if c not in visited)
        return visited

    def roots(self) -> list[str]:
        """Return CIDs of claims with no parents (DAG entry points)."""
        return [
            cid
            for cid in self.store.list_cids()
            if not self.store.get(cid).parents
        ]

    def leaves(self) -> list[str]:
        """Return CIDs of claims with no children (DAG tips)."""
        referenced_as_parent: set[str] = set()
        all_cids = self.store.list_cids()
        for cid in all_cids:
            referenced_as_parent.update(self.store.get(cid).parents)
        return [cid for cid in all_cids if cid not in referenced_as_parent]

    def find_independent_convergence(self) -> list[tuple[str, str]]:
        """Find pairs of claims with same text and completely disjoint ancestry.

        Independent convergence — two researchers arriving at the same claim
        with no shared lineage — is the strongest structural evidence in the DAG.
        """
        by_text: dict[str, list[str]] = {}
        for cid in self.store.list_cids():
            claim = self.store.get(cid)
            by_text.setdefault(claim.claim, []).append(cid)

        pairs = []
        for cids in by_text.values():
            if len(cids) < 2:
                continue
            # Cache ancestor sets (including self) for each CID in this group
            full_ancestry = {
                c: self.ancestors(c) | {c} for c in cids
            }
            for i in range(len(cids)):
                for j in range(i + 1, len(cids)):
                    if not (full_ancestry[cids[i]] & full_ancestry[cids[j]]):
                        pairs.append((cids[i], cids[j]))
        return pairs

    def children(self, cid: str) -> list[str]:
        """Return CIDs of claims that have this CID as a parent (direct children)."""
        return self._children_map().get(cid, [])

    def _children_map(self) -> dict[str, list[str]]:
        """Build a reverse index: parent CID -> list of child CIDs."""
        children: dict[str, list[str]] = {}
        for cid in self.store.list_cids():
            for parent in self.store.get(cid).parents:
                children.setdefault(parent, []).append(cid)
        return children
