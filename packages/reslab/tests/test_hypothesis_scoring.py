"""Tests for hypothesis quality scoring."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.scoring import (
    Grade,
    HypothesisScore,
    score_hypothesis,
    score_hypothesis_text,
    _score_specificity,
    _score_falsifiability,
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
    """Create a project root with .resdag store and git repo."""
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
# Specificity scoring
# ---------------------------------------------------------------------------

class TestSpecificity:
    def test_quantitative_prediction_scores_high(self):
        result = _score_specificity("I predict d>0.5 because CKA shows 4x structure")
        assert result.score >= 0.8

    def test_directional_only_scores_low(self):
        result = _score_specificity("I think performance will be better")
        assert result.score <= 0.3

    def test_no_prediction_scores_zero(self):
        result = _score_specificity("This seems reasonable to try")
        assert result.score == 0.0

    def test_percentage_detected(self):
        result = _score_specificity("Accuracy should exceed 85%")
        assert result.score >= 0.5

    def test_multiple_quantities_score_highest(self):
        result = _score_specificity(
            "I predict accuracy >90% at 10000 steps with 4x improvement"
        )
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# Falsifiability scoring
# ---------------------------------------------------------------------------

class TestFalsifiability:
    def test_if_wrong_section_scores_max(self):
        result = _score_falsifiability(
            "Prediction: X\nRationale: Y\nIf wrong: switch to approach B"
        )
        assert result.score == 1.0

    def test_implicit_prediction_scores_low(self):
        result = _score_falsifiability("I expect this will work")
        assert result.score <= 0.5

    def test_no_falsifiable_language_scores_zero(self):
        result = _score_falsifiability("Interesting idea to explore")
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# Full hypothesis scoring
# ---------------------------------------------------------------------------

class TestScoreHypothesis:
    def test_excellent_hypothesis_grades_a_or_b(self, store):
        cid = store.put(Claim(
            claim=(
                "Prediction: d>0.5 on cross-domain transfer because CKA shows "
                "4x population-level structure, and JEPA achieved d=0.478 in Session 74.\n"
                "Rationale: structural similarity predicts functional transfer.\n"
                "If wrong: reduce to single-domain and verify baseline."
            ),
            type=ClaimType.HYPOTHESIS,
            parents=("bafkreiaaaa",),
            domain=("grokking", "training"),
        ))
        result = score_hypothesis(store, cid)
        assert result.grade in (Grade.A, Grade.B)
        assert result.total >= 0.6

    def test_vague_hypothesis_grades_d_or_f(self, store):
        cid = store.put(Claim(
            claim="I think this approach will work because it seems reasonable",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis(store, cid)
        assert result.grade in (Grade.D, Grade.F)
        assert result.total < 0.4

    def test_medium_hypothesis_grades_b_or_c(self, store):
        cid = store.put(Claim(
            claim="I predict accuracy will improve with larger batch size. Should see >80% at 5000 steps.",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis(store, cid)
        assert result.grade in (Grade.B, Grade.C)

    def test_non_hypothesis_raises(self, store):
        cid = store.put(Claim(
            claim="Accuracy was 92%",
            type=ClaimType.RESULT,
        ))
        with pytest.raises(ValueError, match="not hypothesis"):
            score_hypothesis(store, cid)

    def test_missing_cid_raises(self, store):
        with pytest.raises((ValueError, Exception)):
            score_hypothesis(store, "bafkreinonexistent")

    def test_format_text_output(self, store):
        cid = store.put(Claim(
            claim="I predict d>0.5\nIf wrong: abandon approach",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis(store, cid)
        text = result.format_text()
        assert "Grade:" in text
        assert "specificity" in text
        assert "falsifiability" in text

    def test_to_dict_structure(self, store):
        cid = store.put(Claim(
            claim="I predict d>0.5\nIf wrong: abandon approach",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis(store, cid)
        d = result.to_dict()
        assert "grade" in d
        assert "total" in d
        assert "dimensions" in d
        assert len(d["dimensions"]) == 4

    def test_feedback_for_low_scores(self, store):
        cid = store.put(Claim(
            claim="This seems interesting to try",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis(store, cid)
        assert len(result.feedback) > 0
        # Should suggest adding quantitative prediction
        assert any("quantitative" in f.lower() for f in result.feedback)


# ---------------------------------------------------------------------------
# Novelty scoring
# ---------------------------------------------------------------------------

class TestNovelty:
    def test_first_hypothesis_is_novel(self, store):
        result = score_hypothesis_text(store, "Test something entirely new")
        novelty = next(d for d in result.dimensions if d.name == "novelty")
        assert novelty.score == 1.0

    def test_duplicate_hypothesis_not_novel(self, store):
        store.put(Claim(
            claim="I predict grokking occurs at 10000 steps with batch size 64",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis_text(
            store, "I predict grokking occurs at 10000 steps with batch size 64"
        )
        novelty = next(d for d in result.dimensions if d.name == "novelty")
        assert novelty.score <= 0.3

    def test_different_hypothesis_is_novel(self, store):
        store.put(Claim(
            claim="I predict grokking occurs at 10000 steps",
            type=ClaimType.HYPOTHESIS,
        ))
        result = score_hypothesis_text(
            store, "Learning rate decay improves convergence in transformers"
        )
        novelty = next(d for d in result.dimensions if d.name == "novelty")
        assert novelty.score >= 0.6


# ---------------------------------------------------------------------------
# Preview mode (score_hypothesis_text)
# ---------------------------------------------------------------------------

class TestScoreHypothesisText:
    def test_preview_without_committing(self, store):
        result = score_hypothesis_text(store, "I predict d>0.5\nIf wrong: stop")
        assert result.grade in (Grade.A, Grade.B, Grade.C)
        # Store should be empty — nothing committed
        assert len(store.list_cids()) == 0

    def test_parents_improve_grounding(self, store):
        without = score_hypothesis_text(store, "I predict accuracy >90%")
        with_parents = score_hypothesis_text(
            store, "I predict accuracy >90%", parents=("bafkreiaaaa",)
        )
        g_without = next(d for d in without.dimensions if d.name == "grounding")
        g_with = next(d for d in with_parents.dimensions if d.name == "grounding")
        assert g_with.score > g_without.score


# ---------------------------------------------------------------------------
# CLI: lab score
# ---------------------------------------------------------------------------

class TestScoreCLI:
    def test_lab_score_command(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        # Create a hypothesis
        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize",
            "I predict d>0.5 at 10000 steps\nIf wrong: reduce scope",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        cid = result.output.split()[1]

        # Score it
        result = runner.invoke(main, ["--root", str(store_path), "score", cid])
        assert result.exit_code == 0
        assert "Grade:" in result.output
        assert "specificity" in result.output

    def test_lab_score_json(self, project):
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

        result = runner.invoke(main, ["--root", str(store_path), "score", cid, "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert "grade" in data
        assert "dimensions" in data

    def test_lab_score_non_hypothesis_fails(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "exploratory"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "note", "just a note",
            "--repo", str(project_root),
        ])
        cid = result.output.split()[1]

        result = runner.invoke(main, ["--root", str(store_path), "score", cid])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Validation integration
# ---------------------------------------------------------------------------

class TestValidationIntegration:
    def test_strict_mode_shows_score(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "strict"])

        # Hypothesize with proper structure (strict requires template sections)
        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize",
            "Prediction: accuracy >90%\nRationale: prior work shows trend\nIf wrong: try smaller model",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "Grade:" in result.output

    def test_hypothesize_prints_score(self, project):
        project_root, store_path = project
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store_path), "init", "-m", "disciplined"])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize",
            "I predict accuracy >90% at 5000 steps\nIf wrong: try different lr",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "Grade:" in result.output
