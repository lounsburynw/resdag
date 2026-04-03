"""Tests for DAG operations."""

import pytest

from resdag.claim import Claim, ClaimType
from resdag.dag import DAG
from resdag.storage.local import LocalStore


@pytest.fixture
def dag(tmp_path):
    store = LocalStore(tmp_path / ".resdag")
    store.init()
    return DAG(store)


def _claim(text, parents=(), **kwargs):
    """Helper to create a claim with fixed fields for deterministic CIDs."""
    return Claim(
        claim=text,
        type=kwargs.get("type", ClaimType.RESULT),
        parents=parents,
        domain=kwargs.get("domain", ("test",)),
        author=kwargs.get("author", "did:key:test"),
        timestamp=kwargs.get("timestamp", "2026-01-01T00:00:00Z"),
    )


# --- add / parent validation ---


class TestAdd:
    def test_add_root_claim(self, dag):
        claim = _claim("root claim")
        cid = dag.add(claim)
        assert dag.get(cid).claim == "root claim"

    def test_add_with_valid_parent(self, dag):
        root = _claim("root")
        root_cid = dag.add(root)
        child = _claim("child", parents=(root_cid,))
        child_cid = dag.add(child)
        assert dag.get(child_cid).parents == (root_cid,)

    def test_add_rejects_missing_parent(self, dag):
        claim = _claim("orphan", parents=("bafkreifakenonexistent",))
        with pytest.raises(KeyError, match="Parent not found"):
            dag.add(claim)

    def test_add_is_idempotent(self, dag):
        claim = _claim("same claim")
        cid1 = dag.add(claim)
        cid2 = dag.add(claim)
        assert cid1 == cid2


# --- ancestors ---


class TestAncestors:
    def test_root_has_no_ancestors(self, dag):
        cid = dag.add(_claim("root"))
        assert dag.ancestors(cid) == set()

    def test_direct_parent(self, dag):
        root_cid = dag.add(_claim("root"))
        child_cid = dag.add(_claim("child", parents=(root_cid,)))
        assert dag.ancestors(child_cid) == {root_cid}

    def test_transitive_ancestors(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        c = dag.add(_claim("C", parents=(b,)))
        assert dag.ancestors(c) == {a, b}

    def test_diamond_ancestors(self, dag):
        #     A
        #    / \
        #   B   C
        #    \ /
        #     D
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        c = dag.add(_claim("C", parents=(a,)))
        d = dag.add(_claim("D", parents=(b, c)))
        assert dag.ancestors(d) == {a, b, c}

    def test_ancestors_excludes_self(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        assert b not in dag.ancestors(b)


# --- descendants ---


class TestDescendants:
    def test_leaf_has_no_descendants(self, dag):
        cid = dag.add(_claim("leaf"))
        assert dag.descendants(cid) == set()

    def test_direct_child(self, dag):
        root_cid = dag.add(_claim("root"))
        child_cid = dag.add(_claim("child", parents=(root_cid,)))
        assert dag.descendants(root_cid) == {child_cid}

    def test_transitive_descendants(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        c = dag.add(_claim("C", parents=(b,)))
        assert dag.descendants(a) == {b, c}

    def test_diamond_descendants(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        c = dag.add(_claim("C", parents=(a,)))
        d = dag.add(_claim("D", parents=(b, c)))
        assert dag.descendants(a) == {b, c, d}

    def test_descendants_excludes_self(self, dag):
        a = dag.add(_claim("A"))
        dag.add(_claim("B", parents=(a,)))
        assert a not in dag.descendants(a)


# --- roots and leaves ---


class TestRootsAndLeaves:
    def test_single_claim_is_root_and_leaf(self, dag):
        cid = dag.add(_claim("solo"))
        assert dag.roots() == [cid]
        assert dag.leaves() == [cid]

    def test_chain_root_and_leaf(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        c = dag.add(_claim("C", parents=(b,)))
        assert dag.roots() == [a]
        assert dag.leaves() == [c]

    def test_fork_has_multiple_leaves(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B", parents=(a,)))
        c = dag.add(_claim("C", parents=(a,)))
        assert dag.roots() == [a]
        assert set(dag.leaves()) == {b, c}

    def test_merge_has_multiple_roots(self, dag):
        a = dag.add(_claim("A"))
        b = dag.add(_claim("B"))
        c = dag.add(_claim("C", parents=(a, b)))
        assert set(dag.roots()) == {a, b}
        assert dag.leaves() == [c]

    def test_empty_dag(self, dag):
        assert dag.roots() == []
        assert dag.leaves() == []


# --- independent convergence ---


class TestIndependentConvergence:
    def test_no_convergence_in_empty_dag(self, dag):
        assert dag.find_independent_convergence() == []

    def test_same_text_disjoint_ancestry(self, dag):
        # Two independent researchers, same claim text, no shared ancestor
        a = dag.add(_claim("photosynthesis increases with CO2", author="did:key:alice"))
        b = dag.add(
            _claim(
                "photosynthesis increases with CO2",
                author="did:key:bob",
                timestamp="2026-02-01T00:00:00Z",
            )
        )
        pairs = dag.find_independent_convergence()
        assert len(pairs) == 1
        assert set(pairs[0]) == {a, b}

    def test_same_text_shared_ancestor_not_convergent(self, dag):
        # Same claim text but sharing an ancestor — not independent
        root = dag.add(_claim("root"))
        a = dag.add(
            _claim("derived conclusion", parents=(root,), author="did:key:alice")
        )
        b = dag.add(
            _claim(
                "derived conclusion",
                parents=(root,),
                author="did:key:bob",
                timestamp="2026-02-01T00:00:00Z",
            )
        )
        # a and b share ancestor `root`, so NOT independent convergence
        pairs = dag.find_independent_convergence()
        assert pairs == []

    def test_different_text_not_convergent(self, dag):
        dag.add(_claim("claim A"))
        dag.add(_claim("claim B", timestamp="2026-02-01T00:00:00Z"))
        assert dag.find_independent_convergence() == []

    def test_convergence_with_deeper_ancestry(self, dag):
        # Two independent chains arriving at the same claim
        # Chain 1: x -> a
        x = dag.add(_claim("hypothesis X"))
        a = dag.add(_claim("the answer is 42", parents=(x,), author="did:key:alice"))
        # Chain 2: y -> b
        y = dag.add(_claim("hypothesis Y", timestamp="2026-02-01T00:00:00Z"))
        b = dag.add(
            _claim(
                "the answer is 42",
                parents=(y,),
                author="did:key:bob",
                timestamp="2026-03-01T00:00:00Z",
            )
        )
        pairs = dag.find_independent_convergence()
        assert len(pairs) == 1
        assert set(pairs[0]) == {a, b}
