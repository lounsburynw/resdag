"""Tests for sync protocol (gossip-based peer synchronization)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from resdag.claim import Claim, ClaimType
from resdag.cli import main
from resdag.dag import DAG
from resdag.storage.local import LocalStore
from resdag.sync.gossip import SyncResult, diff, push, sync, _topological_order


# ── Helpers ──────────────────────────────────────────────────────


def _make_store(tmp_path: Path, name: str) -> LocalStore:
    """Create and initialize a LocalStore in a subdirectory."""
    store = LocalStore(tmp_path / name)
    store.init()
    return store


def _claim(text: str, **kwargs) -> Claim:
    """Create a claim with fixed timestamp for deterministic CIDs."""
    return Claim(
        claim=text,
        type=kwargs.get("type", ClaimType.RESULT),
        parents=kwargs.get("parents", ()),
        evidence=kwargs.get("evidence", ()),
        domain=kwargs.get("domain", ()),
        author=kwargs.get("author", ""),
        timestamp=kwargs.get("timestamp", "2026-01-01T00:00:00Z"),
    )


# ── diff ─────────────────────────────────────────────────────────


class TestDiff:
    def test_empty_stores(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        assert diff(a, b) == set()

    def test_source_has_claims(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c1 = _claim("claim one")
        cid = a.put(c1)
        assert diff(a, b) == {cid}
        assert diff(b, a) == set()

    def test_overlapping_claims(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        shared = _claim("shared claim")
        only_a = _claim("only in a")
        only_b = _claim("only in b")
        a.put(shared)
        b.put(shared)
        cid_a = a.put(only_a)
        cid_b = b.put(only_b)
        assert diff(a, b) == {cid_a}
        assert diff(b, a) == {cid_b}


# ── _topological_order ───────────────────────────────────────────


class TestTopologicalOrder:
    def test_single_claim(self, tmp_path):
        store = _make_store(tmp_path, "s")
        c = _claim("root")
        cid = store.put(c)
        order = _topological_order(store, {cid})
        assert order == [cid]

    def test_parent_before_child(self, tmp_path):
        store = _make_store(tmp_path, "s")
        parent = _claim("parent")
        pid = store.put(parent)
        child = _claim("child", parents=(pid,))
        cid = store.put(child)
        order = _topological_order(store, {pid, cid})
        assert order.index(pid) < order.index(cid)

    def test_chain_ordering(self, tmp_path):
        store = _make_store(tmp_path, "s")
        c1 = _claim("first")
        cid1 = store.put(c1)
        c2 = _claim("second", parents=(cid1,))
        cid2 = store.put(c2)
        c3 = _claim("third", parents=(cid2,))
        cid3 = store.put(c3)
        order = _topological_order(store, {cid1, cid2, cid3})
        assert order == [cid1, cid2, cid3]

    def test_diamond_topology(self, tmp_path):
        store = _make_store(tmp_path, "s")
        root = _claim("root")
        rid = store.put(root)
        left = _claim("left", parents=(rid,))
        lid = store.put(left)
        right = _claim("right", parents=(rid,))
        rig = store.put(right)
        merge = _claim("merge", parents=(lid, rig))
        mid = store.put(merge)
        order = _topological_order(store, {rid, lid, rig, mid})
        assert order.index(rid) < order.index(lid)
        assert order.index(rid) < order.index(rig)
        assert order.index(lid) < order.index(mid)
        assert order.index(rig) < order.index(mid)

    def test_external_parents_ignored(self, tmp_path):
        """Parents not in the transfer set are treated as external."""
        store = _make_store(tmp_path, "s")
        parent = _claim("parent")
        pid = store.put(parent)
        child = _claim("child", parents=(pid,))
        cid = store.put(child)
        # Only transferring the child — parent is "already in target"
        order = _topological_order(store, {cid})
        assert order == [cid]


# ── push ─────────────────────────────────────────────────────────


class TestPush:
    def test_push_empty_to_empty(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        result = push(a, b)
        assert result.claims_pushed == 0

    def test_push_single_claim(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c = _claim("hello")
        cid = a.put(c)
        result = push(a, b)
        assert result.claims_pushed == 1
        assert b.has(cid)
        assert b.get(cid).claim == "hello"

    def test_push_chain(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c1 = _claim("root")
        cid1 = a.put(c1)
        c2 = _claim("child", parents=(cid1,))
        cid2 = a.put(c2)
        result = push(a, b)
        assert result.claims_pushed == 2
        assert b.has(cid1)
        assert b.has(cid2)

    def test_push_skips_existing(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        shared = _claim("shared")
        a.put(shared)
        b.put(shared)
        only_a = _claim("only in a")
        cid_a = a.put(only_a)
        result = push(a, b)
        assert result.claims_pushed == 1
        assert b.has(cid_a)

    def test_push_no_op_when_synced(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c = _claim("same")
        a.put(c)
        b.put(c)
        result = push(a, b)
        assert result.claims_pushed == 0

    def test_push_preserves_cid(self, tmp_path):
        """Content-addressing: CID in target matches CID in source."""
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c = _claim("deterministic")
        cid = a.put(c)
        push(a, b)
        assert b.get(cid).cid() == cid

    def test_push_with_evidence(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        ev_cid = a.put_evidence(b"data123", filename="test.csv", media_type="text/csv")
        c = _claim("with evidence", evidence=(ev_cid,))
        a.put(c)
        result = push(a, b, include_evidence=True)
        assert result.claims_pushed == 1
        assert result.evidence_pushed == 1
        assert b.has_evidence(ev_cid)
        assert b.get_evidence(ev_cid) == b"data123"
        meta = b.get_evidence_meta(ev_cid)
        assert meta["filename"] == "test.csv"

    def test_push_evidence_skips_existing(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        ev_cid = a.put_evidence(b"shared", filename="f.txt")
        b.put_evidence(b"shared", filename="f.txt")
        c = _claim("has evidence", evidence=(ev_cid,))
        a.put(c)
        b.put(c)
        result = push(a, b, include_evidence=True)
        assert result.evidence_pushed == 0


# ── sync (bidirectional) ─────────────────────────────────────────


class TestSync:
    def test_sync_disjoint(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        ca = _claim("in a")
        cb = _claim("in b")
        cid_a = a.put(ca)
        cid_b = b.put(cb)
        result = sync(a, b)
        assert result.claims_pushed == 2
        assert a.has(cid_b)
        assert b.has(cid_a)

    def test_sync_already_synced(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c = _claim("shared")
        a.put(c)
        b.put(c)
        result = sync(a, b)
        assert result.claims_pushed == 0

    def test_sync_with_overlap(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        shared = _claim("shared")
        a.put(shared)
        b.put(shared)
        only_a = _claim("only a")
        only_b = _claim("only b")
        cid_a = a.put(only_a)
        cid_b = b.put(only_b)
        result = sync(a, b)
        assert result.claims_pushed == 2
        assert a.has(cid_b)
        assert b.has(cid_a)
        # Both stores now identical
        assert set(a.list_cids()) == set(b.list_cids())

    def test_sync_complex_dag(self, tmp_path):
        """Sync a multi-level DAG between two stores with partial overlap."""
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")

        # Build a chain in store a
        r = _claim("root")
        rid = a.put(r)
        c1 = _claim("child1", parents=(rid,))
        c1id = a.put(c1)
        c2 = _claim("child2", parents=(c1id,))
        c2id = a.put(c2)

        # Store b has the root and a different branch
        b.put(r)
        alt = _claim("alt branch", parents=(rid,))
        alt_id = b.put(alt)

        result = sync(a, b)
        # a gets alt branch, b gets child1 + child2
        assert result.claims_pushed == 3
        assert a.has(alt_id)
        assert b.has(c1id)
        assert b.has(c2id)
        assert set(a.list_cids()) == set(b.list_cids())

    def test_sync_idempotent(self, tmp_path):
        """Syncing twice produces no changes the second time."""
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        a.put(_claim("one"))
        b.put(_claim("two"))
        sync(a, b)
        result = sync(a, b)
        assert result.claims_pushed == 0

    def test_sync_with_evidence(self, tmp_path):
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        ev_a = a.put_evidence(b"data_a", filename="a.csv")
        ev_b = b.put_evidence(b"data_b", filename="b.csv")
        a.put(_claim("claim a", evidence=(ev_a,)))
        b.put(_claim("claim b", evidence=(ev_b,)))
        result = sync(a, b, include_evidence=True)
        assert result.claims_pushed == 2
        assert result.evidence_pushed == 2
        assert a.has_evidence(ev_b)
        assert b.has_evidence(ev_a)

    def test_no_duplicates_after_sync(self, tmp_path):
        """Content-addressing prevents duplicates."""
        a = _make_store(tmp_path, "a")
        b = _make_store(tmp_path, "b")
        c = _claim("same claim")
        a.put(c)
        b.put(c)
        a.put(_claim("extra"))
        sync(a, b)
        # No duplicate CIDs
        assert len(b.list_cids()) == len(set(b.list_cids()))


# ── SyncResult ───────────────────────────────────────────────────


class TestSyncResult:
    def test_defaults(self):
        r = SyncResult()
        assert r.claims_pushed == 0
        assert r.evidence_pushed == 0


# ── CLI integration ──────────────────────────────────────────────


class TestSyncCLI:
    def _init_store(self, path: Path):
        store = LocalStore(path / ".resdag")
        store.init()
        return store

    def test_sync_command(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()

        local_store = self._init_store(local_dir)
        peer_store = self._init_store(peer_dir)

        local_store.put(_claim("local claim"))
        peer_store.put(_claim("peer claim"))

        runner = CliRunner()
        os.chdir(local_dir)
        result = runner.invoke(main, ["sync", str(peer_dir / ".resdag")])
        assert result.exit_code == 0
        assert "2 claim(s)" in result.output

    def test_sync_already_synced(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()

        local_store = self._init_store(local_dir)
        peer_store = self._init_store(peer_dir)

        c = _claim("same")
        local_store.put(c)
        peer_store.put(c)

        runner = CliRunner()
        os.chdir(local_dir)
        result = runner.invoke(main, ["sync", str(peer_dir / ".resdag")])
        assert result.exit_code == 0
        assert "Already in sync" in result.output

    def test_sync_push_only(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()

        local_store = self._init_store(local_dir)
        peer_store = self._init_store(peer_dir)

        c = _claim("local only")
        cid = local_store.put(c)
        peer_store.put(_claim("peer only"))

        runner = CliRunner()
        os.chdir(local_dir)
        result = runner.invoke(main, ["sync", str(peer_dir / ".resdag"), "--push-only"])
        assert result.exit_code == 0
        assert "1 claim(s)" in result.output
        # Peer has local's claim
        assert peer_store.has(cid)
        # Local does NOT have peer's claim (push only)
        assert len(local_store.list_cids()) == 1

    def test_sync_pull_only(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()

        local_store = self._init_store(local_dir)
        peer_store = self._init_store(peer_dir)

        peer_claim = _claim("peer only")
        peer_cid = peer_store.put(peer_claim)
        local_store.put(_claim("local only"))

        runner = CliRunner()
        os.chdir(local_dir)
        result = runner.invoke(main, ["sync", str(peer_dir / ".resdag"), "--pull-only"])
        assert result.exit_code == 0
        assert "1 claim(s)" in result.output
        # Local has peer's claim
        assert local_store.has(peer_cid)
        # Peer does NOT have local's claim (pull only)
        assert len(peer_store.list_cids()) == 1

    def test_sync_push_pull_mutually_exclusive(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()

        self._init_store(local_dir)
        self._init_store(peer_dir)

        runner = CliRunner()
        os.chdir(local_dir)
        result = runner.invoke(
            main, ["sync", str(peer_dir / ".resdag"), "--push-only", "--pull-only"]
        )
        assert result.exit_code != 0
        assert "Cannot use both" in result.output

    def test_sync_not_a_repo(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        not_repo = tmp_path / "empty"
        not_repo.mkdir()

        self._init_store(local_dir)

        runner = CliRunner()
        os.chdir(local_dir)
        result = runner.invoke(main, ["sync", str(not_repo)])
        assert result.exit_code != 0
        assert "Not a resdag repository" in result.output
