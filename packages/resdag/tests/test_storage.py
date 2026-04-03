"""Tests for local content-addressed storage."""

import json

import pytest

from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore


@pytest.fixture
def store(tmp_path):
    s = LocalStore(tmp_path / ".resdag")
    s.init()
    return s


@pytest.fixture
def sample_claim():
    return Claim(
        claim="Grokking occurs after 10^4 steps",
        type=ClaimType.RESULT,
        domain=("ml.generalization",),
        timestamp="2026-01-01T00:00:00Z",
    )


class TestInit:
    def test_creates_objects_dir(self, store):
        assert store.objects_dir.exists()
        assert store.objects_dir.is_dir()

    def test_init_idempotent(self, store):
        store.init()  # second call should not fail
        assert store.objects_dir.exists()


class TestPut:
    def test_returns_cid(self, store, sample_claim):
        cid = store.put(sample_claim)
        assert cid == sample_claim.cid()

    def test_creates_file(self, store, sample_claim):
        cid = store.put(sample_claim)
        path = store._object_path(cid)
        assert path.exists()

    def test_duplicate_write_is_noop(self, store, sample_claim):
        cid1 = store.put(sample_claim)
        cid2 = store.put(sample_claim)
        assert cid1 == cid2
        assert len(store.list_cids()) == 1

    def test_file_not_overwritten_on_duplicate(self, store, sample_claim):
        cid = store.put(sample_claim)
        path = store._object_path(cid)
        mtime_before = path.stat().st_mtime
        store.put(sample_claim)
        mtime_after = path.stat().st_mtime
        assert mtime_before == mtime_after


class TestGet:
    def test_retrieves_claim(self, store, sample_claim):
        cid = store.put(sample_claim)
        retrieved = store.get(cid)
        assert retrieved.claim == sample_claim.claim
        assert retrieved.type == sample_claim.type
        assert retrieved.cid() == cid

    def test_missing_raises_key_error(self, store):
        with pytest.raises(KeyError):
            store.get("bafkreinotexistent")

    def test_roundtrip_preserves_all_fields(self, store):
        claim = Claim(
            claim="Test roundtrip",
            type=ClaimType.METHOD,
            parents=("bafkreiabc",),
            evidence=("bafkreixyz",),
            domain=("testing",),
            author="did:key:test",
            timestamp="2026-01-01T00:00:00Z",
            signature="sig123",
        )
        cid = store.put(claim)
        retrieved = store.get(cid)
        assert retrieved == claim

    def test_integrity_check(self, store, sample_claim):
        """Tampering with stored content is detected."""
        cid = store.put(sample_claim)
        path = store._object_path(cid)
        # Corrupt the file
        path.write_text('{"claim": "tampered"}', encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            store.get(cid)


class TestHas:
    def test_exists(self, store, sample_claim):
        cid = store.put(sample_claim)
        assert store.has(cid)

    def test_not_exists(self, store):
        assert not store.has("bafkreinotexistent")


class TestListCids:
    def test_empty(self, store):
        assert store.list_cids() == []

    def test_lists_all(self, store):
        c1 = Claim(claim="Claim A", type=ClaimType.RESULT, timestamp="2026-01-01T00:00:00Z")
        c2 = Claim(claim="Claim B", type=ClaimType.HYPOTHESIS, timestamp="2026-01-01T00:00:00Z")
        cid1 = store.put(c1)
        cid2 = store.put(c2)
        assert set(store.list_cids()) == {cid1, cid2}

    def test_multiple_claims(self, store):
        claims = [
            Claim(claim=f"Claim {i}", type=ClaimType.RESULT, timestamp="2026-01-01T00:00:00Z")
            for i in range(5)
        ]
        cids = {store.put(c) for c in claims}
        assert set(store.list_cids()) == cids


class TestGitFriendly:
    def test_directory_layout(self, store, sample_claim):
        """Storage uses objects/{prefix}/{rest} like git."""
        cid = store.put(sample_claim)
        expected = store.objects_dir / cid[:2] / cid[2:]
        assert expected.exists()

    def test_stored_as_readable_json(self, store, sample_claim):
        """Stored files are human-readable JSON (diffable in git)."""
        cid = store.put(sample_claim)
        path = store._object_path(cid)
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["claim"] == sample_claim.claim
        # Indented (human-readable, not compact)
        assert "\n" in content
