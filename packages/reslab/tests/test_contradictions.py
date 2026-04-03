"""Tests for contradiction detection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.contradictions import (
    Contradiction,
    find_contradictions_for,
    find_all_contradictions,
    check_new_claim,
    format_contradictions,
    _detect_signals,
    _extract_quantities,
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
# Signal detection
# ---------------------------------------------------------------------------

class TestSignalDetection:
    def test_negation_asymmetry(self):
        signals = _detect_signals(
            "Temperature increases reaction rate",
            "Temperature does not increase reaction rate",
        )
        assert "negation_asymmetry" in signals

    def test_antonym_pair(self):
        signals = _detect_signals(
            "Batch size increase improves convergence",
            "Batch size decrease improves convergence",
        )
        assert any(s.startswith("antonym:") for s in signals)

    def test_opposing_directions(self):
        signals = _detect_signals(
            "Learning rate increase improves performance",
            "Learning rate increase degrades performance",
        )
        assert any(s.startswith("antonym:") for s in signals)

    def test_quantity_mismatch(self):
        signals = _detect_signals(
            "Accuracy 92% on the benchmark",
            "Accuracy 45% on the benchmark",
        )
        assert any(s.startswith("quantity_mismatch:") for s in signals)

    def test_refutation_language(self):
        signals = _detect_signals(
            "This result contradicts prior findings",
            "Prior findings show improvement",
        )
        assert "refutation_language" in signals

    def test_no_signals_for_compatible_claims(self):
        signals = _detect_signals(
            "Grokking occurs at 10000 steps",
            "Grokking emerges after long training",
        )
        assert len(signals) == 0

    def test_failed_to_replicate(self):
        signals = _detect_signals(
            "Could not reproduce the original result",
            "Training converges after 5000 steps",
        )
        assert "refutation_language" in signals


# ---------------------------------------------------------------------------
# Quantity extraction
# ---------------------------------------------------------------------------

class TestQuantityExtraction:
    def test_percentage(self):
        results = _extract_quantities("Accuracy 92% on test set")
        assert any(ctx == "accuracy" and val == 92.0 for ctx, val in results)

    def test_equals_notation(self):
        results = _extract_quantities("d=0.478 on transfer task")
        assert any(ctx == "d" and abs(val - 0.478) < 0.001 for ctx, val in results)

    def test_empty_text(self):
        assert _extract_quantities("No numbers here") == []


# ---------------------------------------------------------------------------
# find_contradictions_for
# ---------------------------------------------------------------------------

class TestFindContradictionsFor:
    def test_detects_opposing_claims(self, store):
        cid_a = store.put(Claim(
            claim="Temperature increase improves reaction rate by 25%",
            type=ClaimType.RESULT,
            domain=("chemistry",),
        ))
        cid_b = store.put(Claim(
            claim="Temperature increase does not improve reaction rate, only 2%",
            type=ClaimType.RESULT,
            domain=("chemistry",),
        ))
        results = find_contradictions_for(store, cid_a, confidence_threshold=0.1)
        assert len(results) >= 1
        assert results[0].cid_b == cid_b

    def test_no_contradictions_for_compatible(self, store):
        cid_a = store.put(Claim(
            claim="Grokking occurs at 10000 steps",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="Learning rate affects convergence speed",
            type=ClaimType.RESULT,
        ))
        results = find_contradictions_for(store, cid_a)
        assert len(results) == 0

    def test_skips_meta_types(self, store):
        cid_a = store.put(Claim(
            claim="X increases Y",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="X does not increase Y",
            type=ClaimType.REFUTATION,  # Meta type, should be skipped
        ))
        results = find_contradictions_for(store, cid_a)
        assert len(results) == 0

    def test_missing_cid_raises(self, store):
        with pytest.raises((ValueError, Exception)):
            find_contradictions_for(store, "bafkreinonexistent")

    def test_format_line(self, store):
        cid_a = store.put(Claim(
            claim="Temperature increase improves yield by 30%",
            type=ClaimType.RESULT,
        ))
        cid_b = store.put(Claim(
            claim="Temperature increase does not improve yield, only 5%",
            type=ClaimType.RESULT,
        ))
        results = find_contradictions_for(store, cid_a, confidence_threshold=0.1)
        assert len(results) >= 1
        line = results[0].format_line()
        assert "confidence" in line

    def test_to_dict(self, store):
        cid_a = store.put(Claim(
            claim="Batch size increase improves accuracy to 90%",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="Batch size increase decreases accuracy to 60%",
            type=ClaimType.RESULT,
        ))
        results = find_contradictions_for(store, cid_a, confidence_threshold=0.1)
        assert len(results) >= 1
        d = results[0].to_dict()
        assert "cid_a" in d
        assert "signals" in d
        assert "confidence" in d


# ---------------------------------------------------------------------------
# find_all_contradictions
# ---------------------------------------------------------------------------

class TestFindAllContradictions:
    def test_finds_contradictions_across_dag(self, store):
        store.put(Claim(
            claim="Model accuracy 92% on benchmark",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="Model accuracy 45% on benchmark, not 92%",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="Unrelated claim about grokking",
            type=ClaimType.RESULT,
        ))
        results = find_all_contradictions(store, confidence_threshold=0.1)
        assert len(results) >= 1

    def test_deduplicates_pairs(self, store):
        store.put(Claim(
            claim="X increases Y by 50%",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="X does not increase Y, only 5%",
            type=ClaimType.RESULT,
        ))
        results = find_all_contradictions(store, confidence_threshold=0.1)
        # Should have exactly 1 pair, not 2 (A vs B and B vs A)
        assert len(results) == 1

    def test_empty_store(self, store):
        assert find_all_contradictions(store) == []


# ---------------------------------------------------------------------------
# check_new_claim (preview mode)
# ---------------------------------------------------------------------------

class TestCheckNewClaim:
    def test_flags_contradicting_new_claim(self, store):
        store.put(Claim(
            claim="Learning rate 0.001 increases convergence speed",
            type=ClaimType.RESULT,
        ))
        results = check_new_claim(
            store,
            "Learning rate 0.001 does not increase convergence speed",
            confidence_threshold=0.1,
        )
        assert len(results) >= 1
        assert results[0].cid_a == "(new)"

    def test_no_contradiction_for_new_topic(self, store):
        store.put(Claim(
            claim="Grokking occurs at 10000 steps",
            type=ClaimType.RESULT,
        ))
        results = check_new_claim(store, "Image classification with ResNet")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Format output
# ---------------------------------------------------------------------------

class TestFormatContradictions:
    def test_no_contradictions_message(self):
        assert "No contradictions" in format_contradictions([])

    def test_formats_contradictions(self, store):
        cid_a = store.put(Claim(
            claim="X increases Y by 50%",
            type=ClaimType.RESULT,
        ))
        store.put(Claim(
            claim="X does not increase Y, only 5%",
            type=ClaimType.RESULT,
        ))
        results = find_contradictions_for(store, cid_a, confidence_threshold=0.1)
        text = format_contradictions(results)
        assert "contradiction" in text.lower()


# ---------------------------------------------------------------------------
# CLI: lab contradictions
# ---------------------------------------------------------------------------

class TestContradictionsCLI:
    def test_lab_contradictions(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        # Create contradicting claims
        runner.invoke(main, [
            "--root", str(store_path), "note",
            "Temperature increase improves yield by 50%",
            "--repo", str(project_root),
        ])
        runner.invoke(main, [
            "--root", str(store_path), "note",
            "Temperature increase does not improve yield, only 3%",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, ["--root", str(store_path), "contradictions"])
        assert result.exit_code == 0

    def test_lab_contradictions_for_cid(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path), "note",
            "Batch size 64 improves accuracy to 92%",
            "--repo", str(project_root),
        ])
        cid = result.output.split()[1]

        runner.invoke(main, [
            "--root", str(store_path), "note",
            "Batch size 64 decreases accuracy to 45%",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, [
            "--root", str(store_path), "contradictions", "--for", cid,
        ])
        assert result.exit_code == 0

    def test_lab_contradictions_json(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        runner.invoke(main, [
            "--root", str(store_path), "note",
            "X increases Y by 50%",
            "--repo", str(project_root),
        ])
        runner.invoke(main, [
            "--root", str(store_path), "note",
            "X does not increase Y, only 5%",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, [
            "--root", str(store_path), "contradictions", "--json",
        ])
        assert result.exit_code == 0

    def test_empty_dag_no_contradictions(self, project):
        _, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, ["--root", str(store_path), "contradictions"])
        assert result.exit_code == 0
        assert "No contradictions" in result.output
