"""Tests for /claim slash command generation and content."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.profiles import (
    ProfileMode,
    _CLAIM_COMMAND,
    generate_claim_command,
    init_profile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Prompt content — file references
# ---------------------------------------------------------------------------

class TestClaimCommandReferences:
    """The prompt must reference the config files the agent needs to read."""

    def test_references_profile_json(self) -> None:
        assert "profile.json" in _CLAIM_COMMAND

    def test_references_vocabulary_json(self) -> None:
        assert "vocabulary.json" in _CLAIM_COMMAND

    def test_references_result_template(self) -> None:
        assert "templates/result.md" in _CLAIM_COMMAND

    def test_references_hypothesis_template(self) -> None:
        assert "templates/hypothesis.md" in _CLAIM_COMMAND

    def test_references_audience(self) -> None:
        assert "audience" in _CLAIM_COMMAND.lower()


# ---------------------------------------------------------------------------
# Prompt content — template sections
# ---------------------------------------------------------------------------

class TestClaimCommandTemplates:
    """The prompt must include the template section markers so the agent
    knows the expected structure without needing to read template files."""

    def test_result_sections(self) -> None:
        assert "Question:" in _CLAIM_COMMAND
        assert "Finding:" in _CLAIM_COMMAND
        assert "Implication:" in _CLAIM_COMMAND
        assert "Details:" in _CLAIM_COMMAND

    def test_hypothesis_sections(self) -> None:
        assert "Prediction:" in _CLAIM_COMMAND
        assert "Rationale:" in _CLAIM_COMMAND
        assert "If wrong:" in _CLAIM_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — workflow commands
# ---------------------------------------------------------------------------

class TestClaimCommandWorkflow:
    """The prompt must include the exact CLI commands for each step."""

    def test_includes_hypothesize_command(self) -> None:
        assert "lab hypothesize" in _CLAIM_COMMAND

    def test_includes_execute_command(self) -> None:
        assert "lab execute" in _CLAIM_COMMAND

    def test_includes_hypothesis_flag(self) -> None:
        # The execute command must link to a hypothesis
        assert "-h <hypothesis_cid>" in _CLAIM_COMMAND or "--hypothesis" in _CLAIM_COMMAND

    def test_includes_interpret_command(self) -> None:
        assert "lab interpret" in _CLAIM_COMMAND

    def test_includes_confirmed_and_refuted(self) -> None:
        assert "--confirmed" in _CLAIM_COMMAND
        assert "--refuted" in _CLAIM_COMMAND

    def test_includes_branch_command(self) -> None:
        assert "lab branch" in _CLAIM_COMMAND

    def test_includes_suggest_parents(self) -> None:
        assert "--suggest-parents" in _CLAIM_COMMAND

    def test_includes_evidence_flag(self) -> None:
        assert "-e" in _CLAIM_COMMAND

    def test_includes_domain_flag(self) -> None:
        assert "-d <domain>" in _CLAIM_COMMAND or "-d <tag>" in _CLAIM_COMMAND

    def test_includes_threads_open(self) -> None:
        assert "lab threads --open" in _CLAIM_COMMAND

    def test_includes_note_command(self) -> None:
        assert "lab note" in _CLAIM_COMMAND

    def test_includes_no_validate(self) -> None:
        assert "--no-validate" in _CLAIM_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — hypothesis-first workflow
# ---------------------------------------------------------------------------

class TestClaimCommandHypothesisFirst:
    """The core requirement: hypothesis before result."""

    def test_hypothesis_step_before_result_step(self) -> None:
        """Hypothesis creation must appear before result creation."""
        hyp_pos = _CLAIM_COMMAND.index("lab hypothesize")
        exe_pos = _CLAIM_COMMAND.index("lab execute")
        assert hyp_pos < exe_pos

    def test_user_confirmation_before_commit(self) -> None:
        """The prompt must ask the user to confirm before committing."""
        assert "confirm" in _CLAIM_COMMAND.lower()

    def test_interpret_and_branch_offered(self) -> None:
        """After result, the prompt must offer interpretation and branching."""
        exe_pos = _CLAIM_COMMAND.index("lab execute")
        assert "interpret" in _CLAIM_COMMAND[exe_pos:].lower()
        assert "branch" in _CLAIM_COMMAND[exe_pos:].lower()


# ---------------------------------------------------------------------------
# Prompt content — comprehensiveness
# ---------------------------------------------------------------------------

class TestClaimCommandCompleteness:
    """The prompt must be a complete, actionable guide — not a stub."""

    def test_is_substantially_longer_than_stub(self) -> None:
        """The comprehensive prompt should be >1000 characters."""
        assert len(_CLAIM_COMMAND) > 1000

    def test_has_multiple_steps(self) -> None:
        """Should have numbered steps (## Step N)."""
        assert "Step 0" in _CLAIM_COMMAND or "Step 1" in _CLAIM_COMMAND
        assert "Step 5" in _CLAIM_COMMAND or "Step 6" in _CLAIM_COMMAND

    def test_includes_audit_command(self) -> None:
        assert "lab audit" in _CLAIM_COMMAND

    def test_includes_quick_reference(self) -> None:
        assert "quick reference" in _CLAIM_COMMAND.lower() or "Quick reference" in _CLAIM_COMMAND


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

class TestClaimCommandGeneration:
    """Verify that lab init generates claim.md correctly."""

    def test_disciplined_generates_claim_md(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        claim_md = project_root / ".claude" / "commands" / "claim.md"
        assert claim_md.exists()

    def test_strict_generates_claim_md(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.STRICT)
        claim_md = project_root / ".claude" / "commands" / "claim.md"
        assert claim_md.exists()

    def test_exploratory_does_not_generate(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)
        claim_md = project_root / ".claude" / "commands" / "claim.md"
        assert not claim_md.exists()

    def test_generated_content_matches_constant(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        claim_md = project_root / ".claude" / "commands" / "claim.md"
        assert claim_md.read_text() == _CLAIM_COMMAND

    def test_does_not_overwrite_existing(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        cmd_dir = project_root / ".claude" / "commands"
        cmd_dir.mkdir(parents=True)
        custom = "My custom /claim workflow"
        (cmd_dir / "claim.md").write_text(custom)

        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        assert (cmd_dir / "claim.md").read_text() == custom

    def test_generate_claim_command_creates_directories(self, tmp_path: Path) -> None:
        project_root = tmp_path / "new_project"
        project_root.mkdir()
        generate_claim_command(project_root)
        assert (project_root / ".claude" / "commands" / "claim.md").exists()
