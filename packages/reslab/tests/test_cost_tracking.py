"""Tests for cost tracking and cost-aware experiment selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.costs import (
    CostData,
    CostEstimate,
    CostReport,
    parse_cost_trailer,
    format_cost_trailer,
    estimate_cost,
    audit_costs,
)
from reslab.cli import main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> LocalStore:
    return LocalStore(str(tmp_path / ".resdag"))


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    store_path = project_root / ".resdag"
    subprocess.run(["git", "init", str(project_root)], capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        capture_output=True,
        cwd=str(project_root),
    )
    return project_root, store_path


# ---------------------------------------------------------------------------
# Trailer parsing
# ---------------------------------------------------------------------------

class TestTrailerParsing:
    def test_parse_both_fields(self):
        data = parse_cost_trailer("Result achieved [cost_seconds: 1800, cost_usd: 0.45]")
        assert data.seconds == 1800.0
        assert data.usd == 0.45
        assert data.has_cost

    def test_parse_seconds_only(self):
        data = parse_cost_trailer("Result [cost_seconds: 120]")
        assert data.seconds == 120.0
        assert data.usd is None
        assert data.has_cost

    def test_parse_usd_only(self):
        data = parse_cost_trailer("Result [cost_usd: 2.50]")
        assert data.usd == 2.50
        assert data.seconds is None
        assert data.has_cost

    def test_no_trailer(self):
        data = parse_cost_trailer("Plain result with no cost data")
        assert data.seconds is None
        assert data.usd is None
        assert not data.has_cost

    def test_other_trailer_no_cost(self):
        data = parse_cost_trailer("Result [command: python train.py, git_ref: abc123]")
        assert not data.has_cost

    def test_mixed_trailer(self):
        data = parse_cost_trailer(
            "Result [command: train.py, cost_seconds: 3600, git_ref: abc123, cost_usd: 1.20]"
        )
        assert data.seconds == 3600.0
        assert data.usd == 1.20


class TestFormatCostTrailer:
    def test_both_fields(self):
        result = format_cost_trailer(seconds=1800, usd=0.45)
        assert "cost_seconds: 1800" in result
        assert "cost_usd: 0.45" in result

    def test_seconds_only(self):
        result = format_cost_trailer(seconds=120)
        assert "cost_seconds: 120" in result
        assert "cost_usd" not in result

    def test_neither(self):
        result = format_cost_trailer()
        assert result == ""


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

class TestCostEstimate:
    def test_good_hypothesis_recommended(self, store):
        cid = store.put(Claim(
            claim="Prediction: d>0.5 at 10000 steps because prior run showed d=0.478\nRationale: close to threshold\nIf wrong: reduce scope",
            type=ClaimType.HYPOTHESIS,
            parents=("bafkreiaaaa",),
        ))
        result = estimate_cost(store, cid)
        assert result.quality_grade.value in ("A", "B")
        assert result.recommendation == "recommended"

    def test_vague_hypothesis_not_recommended(self, store):
        cid = store.put(Claim(
            claim="This seems interesting to try",
            type=ClaimType.HYPOTHESIS,
        ))
        result = estimate_cost(store, cid)
        assert result.recommendation in ("not recommended", "marginal")

    def test_thread_depth_reduces_value(self, store):
        # Create hypothesis with many results
        h_cid = store.put(Claim(
            claim="I predict accuracy >80% with 5000 steps\nIf wrong: stop",
            type=ClaimType.HYPOTHESIS,
        ))
        for i in range(5):
            store.put(Claim(
                claim=f"Result {i}: accuracy was {70 + i}%",
                type=ClaimType.RESULT,
                parents=(h_cid,),
            ))

        result = estimate_cost(store, h_cid)
        assert result.thread_depth == 5
        # Value should be reduced due to diminishing returns
        assert result.estimated_value < result.quality_score

    def test_non_hypothesis_raises(self, store):
        cid = store.put(Claim(
            claim="Just a result",
            type=ClaimType.RESULT,
        ))
        with pytest.raises(ValueError, match="not hypothesis"):
            estimate_cost(store, cid)

    def test_format_text(self, store):
        cid = store.put(Claim(
            claim="I predict d>0.5\nIf wrong: stop",
            type=ClaimType.HYPOTHESIS,
        ))
        result = estimate_cost(store, cid)
        text = result.format_text()
        assert "Quality:" in text
        assert "Verdict:" in text

    def test_to_dict(self, store):
        cid = store.put(Claim(
            claim="I predict d>0.5\nIf wrong: stop",
            type=ClaimType.HYPOTHESIS,
        ))
        result = estimate_cost(store, cid)
        d = result.to_dict()
        assert "quality_grade" in d
        assert "recommendation" in d
        assert "estimated_value" in d


# ---------------------------------------------------------------------------
# Cost audit
# ---------------------------------------------------------------------------

class TestCostAudit:
    def test_empty_store(self, store):
        report = audit_costs(store)
        assert report.claims_with_costs == 0
        assert report.total_seconds == 0.0
        assert report.total_usd == 0.0

    def test_aggregates_costs(self, store):
        store.put(Claim(
            claim="Result A [cost_seconds: 1800, cost_usd: 0.50]",
            type=ClaimType.RESULT,
            domain=("training",),
        ))
        store.put(Claim(
            claim="Result B [cost_seconds: 3600, cost_usd: 1.00]",
            type=ClaimType.RESULT,
            domain=("training", "evaluation"),
        ))
        store.put(Claim(
            claim="Result C no cost",
            type=ClaimType.RESULT,
        ))

        report = audit_costs(store)
        assert report.claims_with_costs == 2
        assert report.total_result_claims == 3
        assert report.total_seconds == 5400.0
        assert report.total_usd == 1.50
        assert report.seconds_by_domain["training"] == 5400.0

    def test_cost_by_domain(self, store):
        store.put(Claim(
            claim="Training result [cost_usd: 2.00]",
            type=ClaimType.RESULT,
            domain=("training",),
        ))
        store.put(Claim(
            claim="Eval result [cost_usd: 0.50]",
            type=ClaimType.RESULT,
            domain=("evaluation",),
        ))
        report = audit_costs(store)
        assert report.cost_by_domain["training"] == 2.00
        assert report.cost_by_domain["evaluation"] == 0.50

    def test_format_text_with_costs(self, store):
        store.put(Claim(
            claim="Result [cost_seconds: 3600, cost_usd: 1.25]",
            type=ClaimType.RESULT,
            domain=("training",),
        ))
        report = audit_costs(store)
        text = report.format_text()
        assert "Cost tracking:" in text
        assert "$1.25" in text

    def test_format_text_no_costs(self, store):
        report = audit_costs(store)
        text = report.format_text()
        assert "No cost data" in text

    def test_to_dict(self, store):
        store.put(Claim(
            claim="Result [cost_seconds: 60, cost_usd: 0.10]",
            type=ClaimType.RESULT,
            domain=("training",),
        ))
        report = audit_costs(store)
        d = report.to_dict()
        assert "total_seconds" in d
        assert "total_usd" in d
        assert "cost_by_domain" in d

    def test_skips_non_results(self, store):
        store.put(Claim(
            claim="Hypothesis [cost_seconds: 100]",
            type=ClaimType.HYPOTHESIS,
        ))
        report = audit_costs(store)
        assert report.claims_with_costs == 0


# ---------------------------------------------------------------------------
# CLI: lab cost
# ---------------------------------------------------------------------------

class TestCostCLI:
    def test_lab_cost_command(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize",
            "I predict d>0.5 at 10000 steps\nIf wrong: try smaller model",
            "--repo", str(project_root),
        ])
        cid = result.output.split()[1]

        result = runner.invoke(main, ["--root", str(store_path), "cost", cid])
        assert result.exit_code == 0
        assert "Quality:" in result.output
        assert "Verdict:" in result.output

    def test_lab_cost_json(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize",
            "I predict d>0.5\nIf wrong: stop",
            "--repo", str(project_root),
        ])
        cid = result.output.split()[1]

        result = runner.invoke(main, ["--root", str(store_path), "cost", cid, "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "recommendation" in data


# ---------------------------------------------------------------------------
# CLI: lab execute --cost-seconds --cost-usd
# ---------------------------------------------------------------------------

class TestExecuteWithCost:
    def test_execute_with_cost_seconds(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "execute",
            "Training completed with accuracy 92%",
            "--cost-seconds", "1800",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0

        # Verify cost is in the stored claim
        store = LocalStore(str(store_path))
        cid = result.output.split()[1]
        matches = [c for c in store.list_cids() if c.startswith(cid)]
        claim = store.get(matches[0])
        assert "cost_seconds: 1800" in claim.claim

    def test_execute_with_both_costs(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "execute",
            "GPU training done",
            "--cost-seconds", "3600",
            "--cost-usd", "1.25",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0

        store = LocalStore(str(store_path))
        cid = result.output.split()[1]
        matches = [c for c in store.list_cids() if c.startswith(cid)]
        claim = store.get(matches[0])
        assert "cost_seconds: 3600" in claim.claim
        assert "cost_usd: 1.25" in claim.claim

    def test_execute_without_cost(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "execute",
            "Plain result no cost",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0

        store = LocalStore(str(store_path))
        cid = result.output.split()[1]
        matches = [c for c in store.list_cids() if c.startswith(cid)]
        claim = store.get(matches[0])
        assert "cost_seconds" not in claim.claim
        assert "cost_usd" not in claim.claim


# ---------------------------------------------------------------------------
# CLI: lab audit --costs
# ---------------------------------------------------------------------------

class TestAuditCosts:
    def test_audit_costs_flag(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        runner.invoke(main, [
            "--root", str(store_path),
            "execute", "Training result",
            "-d", "training",
            "--cost-seconds", "1800",
            "--cost-usd", "0.50",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, ["--root", str(store_path), "audit", "--costs"])
        assert result.exit_code == 0
        assert "Cost tracking:" in result.output

    def test_audit_costs_json(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        runner.invoke(main, [
            "--root", str(store_path),
            "execute", "Result [cost_seconds: 60]",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, [
            "--root", str(store_path), "audit", "--costs", "--json",
        ])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "total_seconds" in data

    def test_audit_costs_empty(self, project):
        _, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, ["--root", str(store_path), "audit", "--costs"])
        assert result.exit_code == 0
        assert "No cost data" in result.output
