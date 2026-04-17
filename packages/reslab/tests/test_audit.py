"""Tests for DAG health audit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.audit import AuditReport, audit_dag
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


def _claim(text: str, ctype: ClaimType = ClaimType.RESULT, parents: tuple = ()) -> Claim:
    return Claim(claim=text, type=ctype, parents=parents)


# ---------------------------------------------------------------------------
# Unit tests: audit_dag
# ---------------------------------------------------------------------------

class TestEmptyStore:
    def test_empty_store_returns_zero(self, store: LocalStore) -> None:
        report = audit_dag(store)
        assert report.total_claims == 0
        assert not report.warnings

    def test_empty_store_format_text(self, store: LocalStore) -> None:
        report = audit_dag(store)
        assert "Empty store" in report.format_text()

    def test_empty_store_to_dict(self, store: LocalStore) -> None:
        report = audit_dag(store)
        d = report.to_dict()
        assert d["total_claims"] == 0
        assert d["type_distribution"] == {}


class TestTypeDistribution:
    def test_counts_types(self, store: LocalStore) -> None:
        store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT))
        store.put(_claim("r2", ClaimType.RESULT))
        store.put(_claim("m1", ClaimType.METHOD))

        report = audit_dag(store)
        assert report.total_claims == 4
        assert report.type_distribution["hypothesis"] == 1
        assert report.type_distribution["result"] == 2
        assert report.type_distribution["method"] == 1


class TestHypothesisCoverage:
    def test_no_results_coverage_zero(self, store: LocalStore) -> None:
        store.put(_claim("h1", ClaimType.HYPOTHESIS))
        report = audit_dag(store)
        assert report.hypothesis_coverage == 0.0

    def test_result_with_hypothesis_parent(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))

        report = audit_dag(store)
        assert report.hypothesis_coverage == 1.0

    def test_result_without_hypothesis_parent(self, store: LocalStore) -> None:
        store.put(_claim("r1", ClaimType.RESULT))

        report = audit_dag(store)
        assert report.hypothesis_coverage == 0.0

    def test_indirect_hypothesis_ancestor(self, store: LocalStore) -> None:
        """A result linked through an intermediate node still counts as covered."""
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        m_cid = store.put(_claim("m1", ClaimType.METHOD, parents=(h_cid,)))
        store.put(_claim("r1", ClaimType.RESULT, parents=(m_cid,)))

        report = audit_dag(store)
        assert report.hypothesis_coverage == 1.0

    def test_partial_coverage(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))
        store.put(_claim("r2", ClaimType.RESULT))  # orphan result

        report = audit_dag(store)
        assert report.hypothesis_coverage == 0.5


class TestOrphans:
    def test_hypotheses_not_counted_as_orphans(self, store: LocalStore) -> None:
        store.put(_claim("h1", ClaimType.HYPOTHESIS))
        report = audit_dag(store)
        assert report.orphan_count == 0

    def test_parentless_result_is_orphan(self, store: LocalStore) -> None:
        store.put(_claim("r1", ClaimType.RESULT))
        report = audit_dag(store)
        assert report.orphan_count == 1
        assert report.orphan_rate == 1.0

    def test_result_with_parent_not_orphan(self, store: LocalStore) -> None:
        h_cid = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h_cid,)))
        report = audit_dag(store)
        assert report.orphan_count == 0


class TestBranching:
    def test_linear_chain_no_branches(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        assert report.branch_points == 0
        assert report.branch_ratio == 0.0

    def test_single_branch_point(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        store.put(_claim("r2", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        assert report.branch_points == 1
        assert report.branch_ratio == round(1 / 3, 2)


class TestLinearRun:
    def test_no_claims_zero_run(self, store: LocalStore) -> None:
        report = audit_dag(store)
        assert report.max_linear_run == 0

    def test_single_claim_no_run(self, store: LocalStore) -> None:
        """A single claim with no children isn't a chain."""
        store.put(_claim("r1", ClaimType.RESULT))
        report = audit_dag(store)
        # Single node with no children has 0 linear run (chain needs >=1 single-child link)
        assert report.max_linear_run == 0

    def test_simple_chain(self, store: LocalStore) -> None:
        """h → r1 → r2 → r3 is a linear run of 4."""
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r1 = store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        r2 = store.put(_claim("r2", ClaimType.RESULT, parents=(r1,)))
        store.put(_claim("r3", ClaimType.RESULT, parents=(r2,)))
        report = audit_dag(store)
        assert report.max_linear_run == 4

    def test_branch_breaks_chain(self, store: LocalStore) -> None:
        """h → r1, h → r2: the branch at h means no linear run > 1."""
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        store.put(_claim("r2", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        # h has 2 children, so it breaks the chain.
        # r1 and r2 are leaf nodes starting from a branch point child.
        # Each forms a run of 1 (just themselves).
        assert report.max_linear_run <= 1


class TestRefutations:
    def test_counts_refutations(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r = store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        store.put(_claim("f1", ClaimType.REFUTATION, parents=(r,)))
        store.put(_claim("f2", ClaimType.REFUTATION, parents=(r,)))
        report = audit_dag(store)
        assert report.refutation_count == 2


class TestWarnings:
    def test_no_hypotheses_warning(self, store: LocalStore) -> None:
        for i in range(6):
            store.put(_claim(f"r{i}", ClaimType.RESULT))
        report = audit_dag(store)
        assert any("No hypotheses" in w for w in report.warnings)

    def test_high_orphan_rate_warning(self, store: LocalStore) -> None:
        for i in range(4):
            store.put(_claim(f"r{i}", ClaimType.RESULT))
        store.put(_claim("h1", ClaimType.HYPOTHESIS))
        report = audit_dag(store)
        # 4 orphans out of 5 = 80%
        assert any("orphan rate" in w.lower() for w in report.warnings)

    def test_long_linear_run_warning(self, store: LocalStore) -> None:
        prev = store.put(_claim("h", ClaimType.HYPOTHESIS))
        for i in range(11):
            prev = store.put(_claim(f"r{i}", ClaimType.RESULT, parents=(prev,)))
        report = audit_dag(store)
        assert report.max_linear_run == 12
        assert any("linear chain" in w.lower() for w in report.warnings)

    def test_no_refutations_warning(self, store: LocalStore) -> None:
        h = store.put(_claim("h", ClaimType.HYPOTHESIS))
        for i in range(11):
            store.put(_claim(f"r{i}", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        assert any("No refutations" in w for w in report.warnings)

    def test_healthy_dag_no_warnings(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        r = store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        store.put(_claim("f1", ClaimType.REFUTATION, parents=(r,)))
        report = audit_dag(store)
        assert not report.warnings


class TestFormatText:
    def test_includes_all_sections(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        text = report.format_text()
        assert "Claims:" in text
        assert "Types:" in text
        assert "Hypotheses:" in text
        assert "Orphans:" in text
        assert "Branching:" in text
        assert "Linear run:" in text
        assert "Refutations:" in text


class TestToDict:
    def test_all_keys_present(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        d = report.to_dict()
        expected_keys = {
            "total_claims", "type_distribution", "hypothesis_count",
            "hypothesis_coverage", "orphan_count", "orphan_rate",
            "branch_points", "branch_ratio", "max_linear_run",
            "refutation_count", "supersession_count", "warnings",
        }
        assert set(d.keys()) == expected_keys

    def test_json_serializable(self, store: LocalStore) -> None:
        h = store.put(_claim("h1", ClaimType.HYPOTHESIS))
        store.put(_claim("r1", ClaimType.RESULT, parents=(h,)))
        report = audit_dag(store)
        serialized = json.dumps(report.to_dict())
        parsed = json.loads(serialized)
        assert parsed["total_claims"] == 2


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestAuditCLI:
    def test_audit_empty_store(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store_path), "audit"])
        assert result.exit_code == 0
        assert "Empty store" in result.output

    def test_audit_with_claims(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        # Create some claims
        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "test hypothesis",
            "--no-validate", "--repo", str(project_root),
        ])
        result = runner.invoke(main, ["--root", str(store_path), "audit"])
        assert result.exit_code == 0
        assert "Claims:" in result.output
        assert "Hypotheses:" in result.output

    def test_audit_json_output(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "test hypothesis",
            "--no-validate", "--repo", str(project_root),
        ])

        result = runner.invoke(main, ["--root", str(store_path), "audit", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_claims"] == 1
        assert data["hypothesis_count"] == 1
        assert isinstance(data["warnings"], list)

    def test_audit_json_empty_store(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store_path), "audit", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_claims"] == 0


# ---------------------------------------------------------------------------
# Site health badge tests
# ---------------------------------------------------------------------------

class TestSiteHealthBadge:
    def test_badge_rendered_on_index(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        store = LocalStore(str(store_path))
        runner = CliRunner()

        # Create claims so the badge has data
        runner.invoke(main, [
            "--root", str(store_path), "hypothesize", "test hypothesis",
            "--no-validate", "--repo", str(project_root),
        ])

        output_dir = project_root / "site"
        result = runner.invoke(main, [
            "--root", str(store_path), "render", str(output_dir),
        ])
        assert result.exit_code == 0

        index_html = (output_dir / "index.html").read_text()
        assert "health-badge" in index_html
        assert "hypotheses" in index_html
        assert "coverage" in index_html
        assert "orphans" in index_html
        assert "branching" in index_html

    def test_no_badge_on_empty_store(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        output_dir = project_root / "site"
        runner = CliRunner()
        result = runner.invoke(main, [
            "--root", str(store_path), "render", str(output_dir),
        ])
        assert result.exit_code == 0

        index_html = (output_dir / "index.html").read_text()
        # CSS class exists in stylesheet, but the actual badge div should not be rendered
        assert '<div class="health-badge">' not in index_html
