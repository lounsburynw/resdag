"""Tests for commit-time validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import ClaimType
from resdag.storage.local import LocalStore

from reslab.cli import main
from reslab.profiles import (
    Profile,
    ProfileMode,
    ValidationRules,
    mode_defaults,
    save_profile,
)
from reslab.validation import ValidationResult, validate_commit
from reslab.vocabulary import Vocabulary, default_vocabulary, save_vocabulary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a project root with .resdag store and git repo."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    store_path = project_root / ".resdag"

    # Init git so workflow commands work
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

    # Create store
    LocalStore(str(store_path))
    return store_path, project_root


def _make_profile(mode: str = "disciplined") -> Profile:
    return Profile(
        mode=mode,
        project="Test",
        audience="ML researchers",
        validation=mode_defaults(ProfileMode(mode)),
    )


def _make_vocab() -> Vocabulary:
    return default_vocabulary()


# ---------------------------------------------------------------------------
# Unit tests: validate_commit
# ---------------------------------------------------------------------------

class TestHypothesisParentRule:
    def test_off_no_issue(self) -> None:
        profile = _make_profile("exploratory")
        assert profile.validation.hypothesis_parent == "off"
        result = validate_commit(ClaimType.RESULT, "some result", (), "", profile)
        assert not result.issues

    def test_warn_result_without_hypothesis(self) -> None:
        profile = _make_profile("disciplined")
        result = validate_commit(ClaimType.RESULT, "some result", (), "", profile)
        hp_issues = [i for i in result.issues if i.rule == "hypothesis_parent"]
        assert len(hp_issues) == 1
        assert hp_issues[0].level == "warn"
        assert not result.has_errors
        assert result.has_warnings

    def test_warn_result_with_hypothesis(self) -> None:
        profile = _make_profile("disciplined")
        result = validate_commit(ClaimType.RESULT, "some result", (), "bafk123", profile)
        hp_issues = [i for i in result.issues if i.rule == "hypothesis_parent"]
        assert not hp_issues

    def test_require_result_without_hypothesis(self) -> None:
        profile = _make_profile("strict")
        result = validate_commit(ClaimType.RESULT, "some result", (), "", profile)
        assert result.has_errors
        assert result.issues[0].level == "require"

    def test_hypothesis_type_not_checked(self) -> None:
        """Hypotheses themselves don't need a hypothesis parent."""
        profile = _make_profile("strict")
        result = validate_commit(ClaimType.HYPOTHESIS, "prediction", (), "", profile)
        hp_issues = [i for i in result.issues if i.rule == "hypothesis_parent"]
        assert not hp_issues

    def test_suggestion_is_actionable(self) -> None:
        profile = _make_profile("disciplined")
        result = validate_commit(ClaimType.RESULT, "result", (), "", profile)
        assert "lab hypothesize" in result.issues[0].suggestion


class TestClaimStructureRule:
    def test_off_no_issue(self) -> None:
        profile = _make_profile("exploratory")
        result = validate_commit(ClaimType.RESULT, "no template", (), "", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert not cs_issues

    def test_warn_result_missing_sections(self) -> None:
        profile = _make_profile("disciplined")
        result = validate_commit(ClaimType.RESULT, "plain text result", (), "hyp", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert len(cs_issues) == 1
        assert cs_issues[0].level == "warn"
        assert "Question:" in cs_issues[0].message

    def test_result_with_all_sections(self) -> None:
        profile = _make_profile("disciplined")
        text = "Question: What? Finding: This. Implication: That."
        result = validate_commit(ClaimType.RESULT, text, (), "hyp", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert not cs_issues

    def test_hypothesis_missing_sections(self) -> None:
        profile = _make_profile("strict")
        result = validate_commit(ClaimType.HYPOTHESIS, "just a guess", (), "", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert len(cs_issues) == 1
        assert "Prediction:" in cs_issues[0].message

    def test_hypothesis_with_all_sections(self) -> None:
        profile = _make_profile("strict")
        text = "Prediction: X will happen. Rationale: Because Y. If wrong: Try Z."
        result = validate_commit(ClaimType.HYPOTHESIS, text, (), "", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert not cs_issues

    def test_method_missing_sections(self) -> None:
        profile = _make_profile("disciplined")
        result = validate_commit(ClaimType.METHOD, "some method", (), "", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert len(cs_issues) == 1
        assert "Approach:" in cs_issues[0].message

    def test_replication_no_structure_check(self) -> None:
        """Replication/refutation types don't have template sections."""
        profile = _make_profile("strict")
        result = validate_commit(ClaimType.REPLICATION, "replicated it", (), "", profile)
        cs_issues = [i for i in result.issues if i.rule == "claim_structure"]
        assert not cs_issues

    def test_require_blocks_commit(self) -> None:
        profile = _make_profile("strict")
        result = validate_commit(ClaimType.RESULT, "plain text", (), "hyp", profile)
        assert result.has_errors


class TestVocabularyRule:
    def test_off_no_issue(self) -> None:
        profile = Profile(
            mode="custom",
            project="T",
            audience="A",
            validation=ValidationRules(vocabulary="off"),
        )
        vocab = _make_vocab()
        result = validate_commit(ClaimType.RESULT, "r", ("foobar",), "", profile, vocab)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert not v_issues

    def test_warn_unknown_tag(self) -> None:
        profile = _make_profile("disciplined")
        vocab = _make_vocab()
        result = validate_commit(ClaimType.RESULT, "r", ("foobar",), "hyp", profile, vocab)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert len(v_issues) == 1
        assert v_issues[0].level == "warn"
        assert "foobar" in v_issues[0].message

    def test_require_unknown_tag(self) -> None:
        profile = _make_profile("strict")
        vocab = _make_vocab()
        result = validate_commit(ClaimType.RESULT, "r", ("xyz",), "hyp", profile, vocab)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert v_issues[0].level == "require"

    def test_canonical_tag_passes(self) -> None:
        profile = _make_profile("strict")
        vocab = _make_vocab()
        result = validate_commit(ClaimType.RESULT, "r", ("training",), "hyp", profile, vocab)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert not v_issues

    def test_alias_passes(self) -> None:
        profile = _make_profile("strict")
        vocab = _make_vocab()
        result = validate_commit(ClaimType.RESULT, "r", ("finetuning",), "hyp", profile, vocab)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert not v_issues

    def test_no_domains_no_issue(self) -> None:
        profile = _make_profile("strict")
        vocab = _make_vocab()
        result = validate_commit(ClaimType.RESULT, "r", (), "hyp", profile, vocab)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert not v_issues

    def test_no_vocabulary_no_issue(self) -> None:
        """If no vocabulary loaded, vocabulary check is skipped."""
        profile = _make_profile("strict")
        result = validate_commit(ClaimType.RESULT, "r", ("unknown",), "hyp", profile, None)
        v_issues = [i for i in result.issues if i.rule == "vocabulary"]
        assert not v_issues


class TestMultipleRules:
    def test_multiple_issues_compose(self) -> None:
        """All three rules can fire simultaneously."""
        profile = _make_profile("strict")
        vocab = _make_vocab()
        result = validate_commit(
            ClaimType.RESULT, "plain text", ("xyz",), "", profile, vocab,
        )
        rules = {i.rule for i in result.issues}
        assert "hypothesis_parent" in rules
        assert "claim_structure" in rules
        assert "vocabulary" in rules
        assert result.has_errors


class TestValidationResultProperties:
    def test_empty_result(self) -> None:
        r = ValidationResult()
        assert not r.has_errors
        assert not r.has_warnings
        assert not r.issues


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestExecuteValidation:
    def test_warn_prints_but_commits(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("disciplined"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "some result",
             "--repo", str(project_root)],
        )
        # Warning printed but commit succeeds
        assert "Warning:" in result.output or "Warning:" in (result.stderr if hasattr(result, 'stderr') else "")
        assert result.exit_code == 0
        assert "result " in result.output

    def test_require_blocks_without_hypothesis(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "some result",
             "--repo", str(project_root)],
        )
        assert result.exit_code != 0
        assert "blocked" in result.output.lower() or "error" in result.output.lower()

    def test_no_validate_overrides_require(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "some result",
             "--no-validate", "--repo", str(project_root)],
        )
        assert result.exit_code == 0
        assert "result " in result.output

    def test_execute_with_hypothesis_passes_strict(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        # First create a hypothesis
        h_result = runner.invoke(
            main,
            ["--root", str(store_path), "hypothesize",
             "Prediction: X. Rationale: Y. If wrong: Z.",
             "-d", "training", "--no-validate",
             "--repo", str(project_root)],
        )
        assert h_result.exit_code == 0
        hyp_cid = h_result.output.split()[1]

        # Execute with hypothesis + structured text
        text = "Question: Does X? Finding: Yes. Implication: Good."
        e_result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", text,
             "--hypothesis", hyp_cid, "-d", "training",
             "--repo", str(project_root)],
        )
        assert e_result.exit_code == 0
        assert "result " in e_result.output


class TestNoteExempt:
    def test_note_no_validation_in_disciplined(self, project: tuple[Path, Path]) -> None:
        """lab note never triggers validation warnings."""
        store_path, project_root = project
        save_profile(_make_profile("disciplined"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "note", "quick finding",
             "--repo", str(project_root)],
        )
        assert result.exit_code == 0
        assert "result " in result.output
        # No warnings should appear
        assert "Warning:" not in result.output
        assert "Error:" not in result.output

    def test_note_disabled_in_strict(self, project: tuple[Path, Path]) -> None:
        """lab note is disabled in strict mode."""
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "note", "quick finding",
             "--repo", str(project_root)],
        )
        assert result.exit_code != 0
        assert "disabled" in result.output.lower() or "disabled" in (result.stderr if hasattr(result, 'stderr') else "")

    def test_note_works_in_exploratory(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("exploratory"), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "note", "quick finding",
             "--repo", str(project_root)],
        )
        assert result.exit_code == 0
        assert "result " in result.output


class TestNoProfileBackwardCompat:
    def test_no_profile_execute_works(self, project: tuple[Path, Path]) -> None:
        """Without profile.json, all commands work as before (no validation)."""
        store_path, project_root = project
        # Do NOT save a profile

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "some result",
             "--repo", str(project_root)],
        )
        assert result.exit_code == 0
        assert "result " in result.output
        assert "Warning:" not in result.output

    def test_no_profile_hypothesize_works(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "hypothesize", "some hypothesis",
             "--repo", str(project_root)],
        )
        assert result.exit_code == 0
        assert "hypothesis " in result.output

    def test_no_profile_note_works(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "note", "quick note",
             "--repo", str(project_root)],
        )
        assert result.exit_code == 0
        assert "result " in result.output


class TestActionableSuggestions:
    def test_hypothesis_parent_suggestion(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "plain result",
             "--repo", str(project_root)],
        )
        assert "lab hypothesize" in result.output

    def test_claim_structure_suggestion(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "plain result",
             "--hypothesis", "fake", "--no-validate",
             "--repo", str(project_root)],
            catch_exceptions=False,
        )
        # Even with --no-validate, errors are printed (just not blocking)
        assert ".resdag/templates/" in result.output

    def test_vocabulary_suggestion(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "plain result",
             "--hypothesis", "fake", "-d", "unknowntag", "--no-validate",
             "--repo", str(project_root)],
            catch_exceptions=False,
        )
        assert "vocabulary.json" in result.output


class TestOtherCommandsValidation:
    def test_branch_validates(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        # First create a parent claim
        h = runner.invoke(
            main,
            ["--root", str(store_path), "hypothesize", "h", "--no-validate",
             "--repo", str(project_root)],
        )
        parent_cid = h.output.split()[1]

        # Branch with unstructured text should get a warning
        result = runner.invoke(
            main,
            ["--root", str(store_path), "branch", "plain branch", parent_cid,
             "--repo", str(project_root)],
        )
        assert result.exit_code != 0
        assert "Prediction:" in result.output

    def test_replicate_validates_vocabulary(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        save_profile(_make_profile("strict"), store_path)
        save_vocabulary(_make_vocab(), store_path)

        runner = CliRunner()
        # Create a result to replicate
        r = runner.invoke(
            main,
            ["--root", str(store_path), "execute", "original", "--no-validate",
             "--repo", str(project_root)],
        )
        original_cid = r.output.split()[1]

        result = runner.invoke(
            main,
            ["--root", str(store_path), "replicate", "replicated",
             original_cid, "-d", "unknowntag",
             "--repo", str(project_root)],
        )
        assert result.exit_code != 0
        assert "unknowntag" in result.output
