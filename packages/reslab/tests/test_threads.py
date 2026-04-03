"""Tests for research threads."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.threads import Thread, discover_threads, thread_to_dict
from reslab.cli import main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> LocalStore:
    """Create a bare store."""
    return LocalStore(str(tmp_path / ".resdag"))


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a project root with .resdag store and git repo."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    store_path = project_root / ".resdag"

    subprocess.run(["git", "init", str(project_root)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    (project_root / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(project_root), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(project_root), "commit", "-m", "init"],
        capture_output=True, check=True,
    )

    LocalStore(str(store_path))
    return store_path, project_root


def _claim(text: str, ctype: ClaimType = ClaimType.RESULT, parents: tuple = (), domains: tuple = ()) -> Claim:
    return Claim(claim=text, type=ctype, parents=parents, domain=domains)


# ---------------------------------------------------------------------------
# Unit tests: discover_threads
# ---------------------------------------------------------------------------

class TestEmptyStore:
    def test_empty_store_returns_empty_list(self, store: LocalStore) -> None:
        assert discover_threads(store) == []


class TestSingleThread:
    def test_hypothesis_only_is_open(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        threads = discover_threads(store)
        assert len(threads) == 1
        assert threads[0].hypothesis_cid == h_cid
        assert threads[0].status == "open"
        assert threads[0].claim_count == 1

    def test_hypothesis_with_result_is_open(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))
        threads = discover_threads(store)
        assert len(threads) == 1
        assert threads[0].status == "open"
        assert threads[0].claim_count == 2

    def test_hypothesis_with_replication_is_confirmed(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r_cid = store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))
        store.put(_claim("rep1", ClaimType.REPLICATION, parents=(r_cid,)))
        threads = discover_threads(store)
        assert len(threads) == 1
        assert threads[0].status == "confirmed"
        assert threads[0].claim_count == 3

    def test_hypothesis_with_refutation_is_refuted(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r_cid = store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))
        store.put(_claim("ref1", ClaimType.REFUTATION, parents=(r_cid,)))
        threads = discover_threads(store)
        assert len(threads) == 1
        assert threads[0].status == "refuted"

    def test_hypothesis_with_both_is_mixed(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r1 = store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))
        store.put(_claim("rep1", ClaimType.REPLICATION, parents=(r1,)))
        store.put(_claim("ref1", ClaimType.REFUTATION, parents=(r1,)))
        threads = discover_threads(store)
        assert len(threads) == 1
        assert threads[0].status == "mixed"


class TestMultipleThreads:
    def test_two_hypotheses_two_threads(self, store: LocalStore) -> None:
        store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("h2", ClaimType.HYPOTHESIS))
        threads = discover_threads(store)
        assert len(threads) == 2

    def test_threads_sorted_by_last_date(self, store: LocalStore) -> None:
        h1 = store.put(Claim(claim="h1", type=ClaimType.HYPOTHESIS, timestamp="2026-01-01T00:00:00Z"))
        h2 = store.put(Claim(claim="h2", type=ClaimType.HYPOTHESIS, timestamp="2026-02-01T00:00:00Z"))
        threads = discover_threads(store)
        assert threads[0].hypothesis_cid == h2  # newer first
        assert threads[1].hypothesis_cid == h1


class TestMultiAncestor:
    def test_result_in_multiple_threads(self, store: LocalStore) -> None:
        """A result with two hypothesis parents appears in both threads."""
        h1 = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        h2 = store.put(_claim("h2", ClaimType.HYPOTHESIS))
        # Result descends from both via an intermediate
        r1 = store.put(_claim("r1", ClaimType.RESULT, parents=(h1,)))
        # Second thread gets its own result that links to h2
        store.put(_claim("r2", ClaimType.RESULT, parents=(h2, r1)))
        threads = discover_threads(store)
        assert len(threads) == 2
        # r2 is a descendant of h2 directly and also a descendant of h1 via r1
        cids_in_threads = {t.hypothesis_cid: set(t.descendant_cids) for t in threads}
        # h1's thread should contain r1 and r2 (r2 is a descendant of r1 which is a descendant of h1)
        # Actually, r2's parent is (h2, r1). r1's parent is h1. So r2 is reachable from h1 via r1→r2.
        # And r2 is reachable from h2 directly.
        r1_cid = r1
        r2_cid = [c for c in store.list_cids() if c not in (h1, h2, r1)][0]
        assert r1_cid in cids_in_threads[h1]
        assert r2_cid in cids_in_threads[h1]
        assert r2_cid in cids_in_threads[h2]


class TestDomains:
    def test_thread_collects_domains(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS, domains=("training",)))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,), domains=("grokking",)))
        threads = discover_threads(store)
        assert "training" in threads[0].domains
        assert "grokking" in threads[0].domains


class TestDateRange:
    def test_thread_date_range(self, store: LocalStore) -> None:
        h = store.put(Claim(claim="h1", type=ClaimType.HYPOTHESIS, timestamp="2026-01-01T00:00:00Z"))
        store.put(Claim(claim="r1", type=ClaimType.RESULT, parents=(h,), timestamp="2026-03-15T00:00:00Z"))
        threads = discover_threads(store)
        assert threads[0].first_date == "2026-01-01T00:00:00Z"
        assert threads[0].last_date == "2026-03-15T00:00:00Z"


class TestNoHypotheses:
    def test_store_with_no_hypotheses_returns_empty(self, store: LocalStore) -> None:
        store.put(_claim("r1", ClaimType.RESULT))
        store.put(_claim("r2", ClaimType.RESULT))
        threads = discover_threads(store)
        assert len(threads) == 0


class TestThreadToDict:
    def test_serializable(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS, domains=("training",)))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        threads = discover_threads(store)
        d = thread_to_dict(threads[0])
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert parsed["status"] == "open"
        assert parsed["claim_count"] == 2
        assert parsed["domains"] == ["training"]

    def test_all_keys_present(self, store: LocalStore) -> None:
        store.put(_claim("h1", ClaimType.HYPOTHESIS))
        threads = discover_threads(store)
        d = thread_to_dict(threads[0])
        expected_keys = {
            "hypothesis_cid", "hypothesis_text", "status", "claim_count",
            "domains", "first_date", "last_date", "descendant_cids",
        }
        assert set(d.keys()) == expected_keys


class TestDeepThread:
    def test_deep_chain_all_counted(self, store: LocalStore) -> None:
        """h → r1 → r2 → r3 → replication: all 5 in one thread."""
        h = store.put(_claim("h", ClaimType.HYPOTHESIS))
        r1 = store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        r2 = store.put(_claim("r2", ClaimType.RESULT, parents=(r1,)))
        r3 = store.put(_claim("r3", ClaimType.RESULT, parents=(r2,)))
        store.put(_claim("rep", ClaimType.REPLICATION, parents=(r3,)))
        threads = discover_threads(store)
        assert len(threads) == 1
        assert threads[0].claim_count == 5
        assert threads[0].status == "confirmed"


class TestBranchedThread:
    def test_branch_hypothesis_creates_separate_thread(self, store: LocalStore) -> None:
        """h1 → r1 → h2 (branch): h2 is its own thread, but r1 and h2 are descendants of h1."""
        h1 = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r1 = store.put(_claim("r1", ClaimType.RESULT, parents=(h1,)))
        h2 = store.put(_claim("h2", ClaimType.HYPOTHESIS, parents=(r1,)))
        store.put(_claim("r2", ClaimType.RESULT, parents=(h2,)))
        threads = discover_threads(store)
        assert len(threads) == 2
        thread_map = {t.hypothesis_cid: t for t in threads}
        # h1's thread includes r1, h2, r2 (all descendants)
        assert thread_map[h1].claim_count == 4
        # h2's thread includes r2
        assert thread_map[h2].claim_count == 2


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestThreadsCLI:
    def test_threads_empty_store(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store_path), "threads"])
        assert result.exit_code == 0
        assert "No threads found" in result.output

    def test_threads_lists_threads(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "test hypothesis",
            "--no-validate", "--repo", str(project_root),
        ])

        result = runner.invoke(main, ["--root", str(store_path), "threads"])
        assert result.exit_code == 0
        assert "open" in result.output
        assert "test hypothesis" in result.output

    def test_threads_open_flag(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        # Create a confirmed thread (hypothesis + result + replication)
        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "confirmed hypo",
            "--no-validate", "--repo", str(project_root),
        ])
        store = LocalStore(str(store_path))
        h_cid = store.list_cids()[0]
        runner.invoke(main, [
            "--root", str(store_path), "execute", "result",
            "-h", h_cid, "--no-validate", "--repo", str(project_root),
        ])
        r_cid = [c for c in store.list_cids() if c != h_cid][0]
        runner.invoke(main, [
            "--root", str(store_path), "replicate", "rep",
            r_cid, "--no-validate", "--repo", str(project_root),
        ])

        # Create an open thread
        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "open hypo",
            "--no-validate", "--repo", str(project_root),
        ])

        result = runner.invoke(main, ["--root", str(store_path), "threads", "--open"])
        assert result.exit_code == 0
        assert "open hypo" in result.output
        assert "confirmed hypo" not in result.output

    def test_threads_json_output(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "json test",
            "--no-validate", "--repo", str(project_root),
        ])

        result = runner.invoke(main, ["--root", str(store_path), "threads", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["status"] == "open"
        assert "json test" in data[0]["hypothesis_text"]

    def test_threads_open_empty(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store_path), "threads", "--open"])
        assert result.exit_code == 0
        assert "No open threads" in result.output


# ---------------------------------------------------------------------------
# Site rendering tests
# ---------------------------------------------------------------------------

class TestSiteThreadPages:
    def test_thread_index_rendered(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "site test hypo",
            "--no-validate", "--repo", str(project_root),
        ])

        output_dir = project_root / "site"
        result = runner.invoke(main, [
            "--root", str(store_path), "render", str(output_dir),
        ])
        assert result.exit_code == 0

        threads_index = output_dir / "threads" / "index.html"
        assert threads_index.exists()
        html = threads_index.read_text()
        assert "Research Threads" in html
        assert "site test hypo" in html
        assert "open" in html.lower()

    def test_thread_detail_rendered(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        store = LocalStore(str(store_path))
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "detail test hypo",
            "--no-validate", "--repo", str(project_root),
        ])

        h_cid = store.list_cids()[0]
        output_dir = project_root / "site"
        runner.invoke(main, ["--root", str(store_path), "render", str(output_dir)])

        detail_path = output_dir / "threads" / f"{h_cid}.html"
        assert detail_path.exists()
        html = detail_path.read_text()
        assert "detail test hypo" in html
        assert "hypothesis" in html.lower()

    def test_no_threads_dir_when_no_hypotheses(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        # Add a result but no hypothesis
        runner.invoke(main, [
            "--root", str(store_path), "note", "just a note",
            "--repo", str(project_root),
        ])

        output_dir = project_root / "site"
        runner.invoke(main, ["--root", str(store_path), "render", str(output_dir)])

        assert not (output_dir / "threads" / "index.html").exists()

    def test_index_links_to_threads(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "link test",
            "--no-validate", "--repo", str(project_root),
        ])

        output_dir = project_root / "site"
        runner.invoke(main, ["--root", str(store_path), "render", str(output_dir)])

        index_html = (output_dir / "index.html").read_text()
        assert "threads/index.html" in index_html

    def test_thread_with_claims_rendered(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        store = LocalStore(str(store_path))
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "rendered thread hypo",
            "--no-validate", "--repo", str(project_root),
        ])
        h_cid = store.list_cids()[0]
        runner.invoke(main, [
            "--root", str(store_path), "execute", "result in thread",
            "-h", h_cid, "--no-validate", "--repo", str(project_root),
        ])

        output_dir = project_root / "site"
        runner.invoke(main, ["--root", str(store_path), "render", str(output_dir)])

        detail_html = (output_dir / "threads" / f"{h_cid}.html").read_text()
        assert "rendered thread hypo" in detail_html
        assert "result in thread" in detail_html
        assert "2 claims" in detail_html
