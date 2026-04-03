"""Tests for evidence artifact handling."""

import json
import os

import pytest
from click.testing import CliRunner

from resdag.claim import Claim, ClaimType
from resdag.cli import main
from resdag.evidence import compute_cid
from resdag.storage.local import LocalStore


# ── Unit tests: evidence CID ──────────────────────────────────

class TestComputeCid:
    def test_deterministic(self):
        data = b"hello world"
        assert compute_cid(data) == compute_cid(data)

    def test_different_content_different_cid(self):
        assert compute_cid(b"aaa") != compute_cid(b"bbb")

    def test_returns_string(self):
        cid = compute_cid(b"test data")
        assert isinstance(cid, str)
        assert len(cid) > 10

    def test_empty_bytes(self):
        cid = compute_cid(b"")
        assert isinstance(cid, str)
        assert len(cid) > 10


# ── Unit tests: evidence storage ──────────────────────────────

@pytest.fixture
def store(tmp_path):
    s = LocalStore(tmp_path / ".resdag")
    s.init()
    return s


class TestPutEvidence:
    def test_returns_cid(self, store):
        data = b"col1,col2\n1,2\n3,4"
        cid = store.put_evidence(data, filename="data.csv", media_type="text/csv")
        assert cid == compute_cid(data)

    def test_creates_file(self, store):
        data = b"some binary data"
        cid = store.put_evidence(data, filename="blob.bin")
        path = store._evidence_path(cid)
        assert path.exists()

    def test_creates_meta_sidecar(self, store):
        data = b'{"key": "value"}'
        cid = store.put_evidence(data, filename="results.json", media_type="application/json")
        meta_path = store._evidence_path(cid).with_name(store._evidence_path(cid).name + ".meta")
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["filename"] == "results.json"
        assert meta["media_type"] == "application/json"
        assert meta["size"] == len(data)

    def test_duplicate_write_is_noop(self, store):
        data = b"duplicate data"
        cid1 = store.put_evidence(data, filename="a.txt")
        cid2 = store.put_evidence(data, filename="a.txt")
        assert cid1 == cid2

    def test_stores_raw_bytes(self, store):
        data = b"\x00\x01\x02\xff"
        cid = store.put_evidence(data, filename="binary.bin")
        stored = store._evidence_path(cid).read_bytes()
        assert stored == data


class TestGetEvidence:
    def test_retrieves_bytes(self, store):
        data = b"col1,col2\n1,2\n3,4"
        cid = store.put_evidence(data, filename="data.csv")
        assert store.get_evidence(cid) == data

    def test_missing_raises_key_error(self, store):
        with pytest.raises(KeyError):
            store.get_evidence("nonexistent_cid")

    def test_integrity_check(self, store):
        data = b"original data"
        cid = store.put_evidence(data, filename="test.txt")
        # Corrupt the file
        store._evidence_path(cid).write_bytes(b"tampered data")
        with pytest.raises(ValueError, match="Integrity error"):
            store.get_evidence(cid)


class TestGetEvidenceMeta:
    def test_retrieves_metadata(self, store):
        data = b'{"result": 42}'
        cid = store.put_evidence(data, filename="output.json", media_type="application/json")
        meta = store.get_evidence_meta(cid)
        assert meta["filename"] == "output.json"
        assert meta["media_type"] == "application/json"
        assert meta["size"] == len(data)

    def test_missing_returns_empty_dict(self, store):
        assert store.get_evidence_meta("nonexistent") == {}


class TestHasEvidence:
    def test_exists(self, store):
        cid = store.put_evidence(b"data", filename="test.txt")
        assert store.has_evidence(cid)

    def test_not_exists(self, store):
        assert not store.has_evidence("nonexistent")


class TestListEvidenceCids:
    def test_empty(self, store):
        assert store.list_evidence_cids() == []

    def test_lists_all(self, store):
        cid1 = store.put_evidence(b"data1", filename="a.txt")
        cid2 = store.put_evidence(b"data2", filename="b.txt")
        assert set(store.list_evidence_cids()) == {cid1, cid2}

    def test_excludes_meta_files(self, store):
        store.put_evidence(b"data", filename="test.txt")
        cids = store.list_evidence_cids()
        assert all(not c.endswith(".meta") for c in cids)


class TestEvidenceDirSeparation:
    def test_evidence_dir_created_on_init(self, store):
        assert store.evidence_dir.exists()
        assert store.evidence_dir.is_dir()

    def test_evidence_separate_from_claims(self, store):
        """Evidence stored in evidence/, not objects/."""
        data = b"evidence data"
        cid = store.put_evidence(data, filename="test.txt")
        # Should be in evidence dir, not objects dir
        assert store._evidence_path(cid).exists()
        assert not store._object_path(cid).exists()


# ── Integration tests: evidence + claims ──────────────────────

class TestEvidenceClaimIntegration:
    def test_attach_csv_to_claim(self, store):
        csv_data = b"experiment,result\ntrial1,0.95\ntrial2,0.87"
        evidence_cid = store.put_evidence(csv_data, filename="results.csv", media_type="text/csv")
        claim = Claim(
            claim="Model accuracy exceeds 85% on test set",
            type=ClaimType.RESULT,
            evidence=(evidence_cid,),
            domain=("ml.evaluation",),
            timestamp="2026-01-01T00:00:00Z",
        )
        claim_cid = store.put(claim)
        retrieved = store.get(claim_cid)
        assert evidence_cid in retrieved.evidence
        assert store.get_evidence(evidence_cid) == csv_data

    def test_attach_json_to_claim(self, store):
        json_data = json.dumps({"metric": "f1", "score": 0.92}).encode()
        evidence_cid = store.put_evidence(json_data, filename="metrics.json", media_type="application/json")
        claim = Claim(
            claim="F1 score is 0.92",
            type=ClaimType.RESULT,
            evidence=(evidence_cid,),
            timestamp="2026-01-01T00:00:00Z",
        )
        claim_cid = store.put(claim)
        retrieved = store.get(claim_cid)
        assert evidence_cid in retrieved.evidence
        result = json.loads(store.get_evidence(evidence_cid))
        assert result["score"] == 0.92

    def test_multiple_evidence_on_one_claim(self, store):
        csv_cid = store.put_evidence(b"a,b\n1,2", filename="data.csv")
        json_cid = store.put_evidence(b'{"key": 1}', filename="config.json")
        claim = Claim(
            claim="Pipeline produces expected output",
            type=ClaimType.RESULT,
            evidence=(csv_cid, json_cid),
            timestamp="2026-01-01T00:00:00Z",
        )
        store.put(claim)
        assert store.has_evidence(csv_cid)
        assert store.has_evidence(json_cid)

    def test_shared_evidence_across_claims(self, store):
        data = b"shared dataset"
        evidence_cid = store.put_evidence(data, filename="shared.csv")
        c1 = Claim(claim="Claim A", type=ClaimType.RESULT, evidence=(evidence_cid,), timestamp="2026-01-01T00:00:00Z")
        c2 = Claim(claim="Claim B", type=ClaimType.RESULT, evidence=(evidence_cid,), timestamp="2026-01-01T00:00:00Z")
        store.put(c1)
        store.put(c2)
        # Evidence stored once (content-addressed dedup)
        assert store.list_evidence_cids().count(evidence_cid) == 1


# ── CLI tests: evidence through the command line ──────────────

class TestCLIEvidence:
    def test_commit_with_evidence_file(self, tmp_path):
        runner = CliRunner()
        os.chdir(tmp_path)
        runner.invoke(main, ["init"])
        # Create an evidence file
        csv_file = tmp_path / "results.csv"
        csv_file.write_text("trial,score\n1,0.95\n2,0.87")
        result = runner.invoke(main, [
            "commit", "-c", "Accuracy is 91%", "-t", "result",
            "-e", str(csv_file),
        ])
        assert result.exit_code == 0
        assert "evidence: results.csv" in result.output
        assert "result" in result.output

    def test_commit_with_multiple_evidence(self, tmp_path):
        runner = CliRunner()
        os.chdir(tmp_path)
        runner.invoke(main, ["init"])
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2")
        json_file = tmp_path / "config.json"
        json_file.write_text('{"lr": 0.001}')
        result = runner.invoke(main, [
            "commit", "-c", "Training complete", "-t", "result",
            "-e", str(csv_file), "-e", str(json_file),
        ])
        assert result.exit_code == 0
        assert "evidence: data.csv" in result.output
        assert "evidence: config.json" in result.output

    def test_show_displays_evidence(self, tmp_path):
        runner = CliRunner()
        os.chdir(tmp_path)
        runner.invoke(main, ["init"])
        csv_file = tmp_path / "results.csv"
        csv_file.write_text("trial,score\n1,0.95")
        runner.invoke(main, [
            "commit", "-c", "Has evidence", "-t", "result",
            "-e", str(csv_file),
        ])
        log_result = runner.invoke(main, ["log"])
        short_cid = log_result.output.strip().split()[0]
        show_result = runner.invoke(main, ["show", short_cid])
        assert show_result.exit_code == 0
        assert "Evidence:" in show_result.output
        assert "results.csv" in show_result.output
        assert "text/csv" in show_result.output

    def test_commit_with_nonexistent_evidence_fails(self, tmp_path):
        runner = CliRunner()
        os.chdir(tmp_path)
        runner.invoke(main, ["init"])
        result = runner.invoke(main, [
            "commit", "-c", "Bad evidence", "-t", "result",
            "-e", "/nonexistent/file.csv",
        ])
        assert result.exit_code != 0
