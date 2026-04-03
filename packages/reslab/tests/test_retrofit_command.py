"""Tests for /retrofit slash command generation and content."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from resdag.storage.local import LocalStore

from reslab.profiles import (
    ProfileMode,
    _RETROFIT_COMMAND,
    generate_retrofit_command,
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

class TestRetrofitCommandReferences:
    """The prompt must reference the config files the agent needs to read."""

    def test_references_profile_json(self) -> None:
        assert "profile.json" in _RETROFIT_COMMAND

    def test_references_vocabulary_json(self) -> None:
        assert "vocabulary.json" in _RETROFIT_COMMAND

    def test_references_result_template(self) -> None:
        assert "templates/result.md" in _RETROFIT_COMMAND

    def test_references_hypothesis_template(self) -> None:
        assert "templates/hypothesis.md" in _RETROFIT_COMMAND

    def test_references_audience(self) -> None:
        assert "audience" in _RETROFIT_COMMAND.lower()


# ---------------------------------------------------------------------------
# Prompt content — template sections
# ---------------------------------------------------------------------------

class TestRetrofitCommandTemplates:
    """The prompt must include the template section markers so the agent
    knows the expected structure for restructured claims."""

    def test_result_sections(self) -> None:
        assert "Question:" in _RETROFIT_COMMAND
        assert "Finding:" in _RETROFIT_COMMAND
        assert "Implication:" in _RETROFIT_COMMAND
        assert "Details:" in _RETROFIT_COMMAND

    def test_hypothesis_sections(self) -> None:
        assert "Prediction:" in _RETROFIT_COMMAND
        assert "Rationale:" in _RETROFIT_COMMAND
        assert "If wrong:" in _RETROFIT_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — workflow commands
# ---------------------------------------------------------------------------

class TestRetrofitCommandWorkflow:
    """The prompt must include the exact CLI commands for each step."""

    def test_includes_res_log(self) -> None:
        assert "res log" in _RETROFIT_COMMAND

    def test_includes_res_log_orphans(self) -> None:
        assert "res log --orphans" in _RETROFIT_COMMAND

    def test_includes_res_log_active(self) -> None:
        assert "res log --active" in _RETROFIT_COMMAND

    def test_includes_res_show(self) -> None:
        assert "res show" in _RETROFIT_COMMAND

    def test_includes_res_lineage(self) -> None:
        assert "res lineage" in _RETROFIT_COMMAND

    def test_includes_res_supersede(self) -> None:
        assert "res supersede" in _RETROFIT_COMMAND

    def test_includes_lab_hypothesize(self) -> None:
        assert "lab hypothesize" in _RETROFIT_COMMAND

    def test_includes_lab_execute(self) -> None:
        assert "lab execute" in _RETROFIT_COMMAND

    def test_includes_lab_audit_json(self) -> None:
        assert "lab audit --json" in _RETROFIT_COMMAND

    def test_includes_lab_threads(self) -> None:
        assert "lab threads" in _RETROFIT_COMMAND

    def test_includes_lab_threads_open(self) -> None:
        assert "lab threads --open" in _RETROFIT_COMMAND

    def test_includes_suggest_parents(self) -> None:
        assert "--suggest-parents" in _RETROFIT_COMMAND

    def test_includes_no_validate(self) -> None:
        assert "--no-validate" in _RETROFIT_COMMAND

    def test_includes_domain_flag(self) -> None:
        assert "-d <domain>" in _RETROFIT_COMMAND or "-d <tag>" in _RETROFIT_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — idempotency
# ---------------------------------------------------------------------------

class TestRetrofitCommandIdempotency:
    """The prompt must handle partial and fully retrofitted stores correctly."""

    def test_mentions_idempotency(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "idempoten" in text

    def test_mentions_nothing_to_do(self) -> None:
        assert "nothing to do" in _RETROFIT_COMMAND.lower()

    def test_mentions_skip_already_structured(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "already structured" in text

    def test_mentions_skip_criteria(self) -> None:
        """Prompt must describe what makes a claim already structured."""
        assert "Question/Finding/Implication" in _RETROFIT_COMMAND or \
               "already structured" in _RETROFIT_COMMAND.lower()


# ---------------------------------------------------------------------------
# Prompt content — before/after DAG health
# ---------------------------------------------------------------------------

class TestRetrofitCommandHealth:
    """The prompt must require before/after DAG health comparison."""

    def test_mentions_before_after(self) -> None:
        assert "Before" in _RETROFIT_COMMAND and "After" in _RETROFIT_COMMAND

    def test_mentions_hypothesis_coverage(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "hypothesis coverage" in text or "hypothesis" in text

    def test_mentions_orphan_rate(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "orphan rate" in text or "orphan" in text

    def test_mentions_branch_ratio(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "branch ratio" in text


# ---------------------------------------------------------------------------
# Prompt content — user confirmation
# ---------------------------------------------------------------------------

class TestRetrofitCommandConfirmation:
    """The prompt must require user approval before committing."""

    def test_user_confirmation_required(self) -> None:
        assert "confirm" in _RETROFIT_COMMAND.lower()

    def test_do_not_commit_until_confirmed(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "do not commit" in text

    def test_presents_plan_before_executing(self) -> None:
        """The plan presentation must come before the apply step."""
        plan_pos = _RETROFIT_COMMAND.index("Present the retrofit plan")
        apply_pos = _RETROFIT_COMMAND.index("Apply the plan")
        assert plan_pos < apply_pos


# ---------------------------------------------------------------------------
# Prompt content — supersession workflow
# ---------------------------------------------------------------------------

class TestRetrofitCommandSupersession:
    """Retrofit uses supersession, not deletion — protocol is append-only."""

    def test_uses_supersede_for_replacements(self) -> None:
        assert "res supersede <original_cid> <new_cid>" in _RETROFIT_COMMAND or \
               "res supersede" in _RETROFIT_COMMAND

    def test_mentions_append_only(self) -> None:
        text = _RETROFIT_COMMAND.lower()
        assert "append-only" in text

    def test_mentions_superseded_marking(self) -> None:
        assert "SUPERSEDED" in _RETROFIT_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — comprehensiveness
# ---------------------------------------------------------------------------

class TestRetrofitCommandCompleteness:
    """The prompt must be a complete, actionable guide — not a stub."""

    def test_is_substantially_longer_than_stub(self) -> None:
        """The comprehensive prompt should be >2000 characters."""
        assert len(_RETROFIT_COMMAND) > 2000

    def test_has_multiple_steps(self) -> None:
        """Should have numbered steps (## Step N)."""
        assert "Step 0" in _RETROFIT_COMMAND
        assert "Step 7" in _RETROFIT_COMMAND

    def test_includes_quick_reference(self) -> None:
        assert "Quick reference" in _RETROFIT_COMMAND or "quick reference" in _RETROFIT_COMMAND.lower()

    def test_includes_claim_classification_table(self) -> None:
        """Should have a table classifying claim categories."""
        assert "Already structured" in _RETROFIT_COMMAND
        assert "Orphan" in _RETROFIT_COMMAND
        assert "Chain start" in _RETROFIT_COMMAND

    def test_audit_before_and_after(self) -> None:
        """lab audit --json must appear at least twice (before + after)."""
        count = _RETROFIT_COMMAND.count("lab audit --json")
        assert count >= 2


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

class TestRetrofitCommandGeneration:
    """Verify that lab init generates retrofit.md correctly."""

    def test_disciplined_generates_retrofit_md(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        retrofit_md = project_root / ".claude" / "commands" / "retrofit.md"
        assert retrofit_md.exists()

    def test_strict_generates_retrofit_md(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.STRICT)
        retrofit_md = project_root / ".claude" / "commands" / "retrofit.md"
        assert retrofit_md.exists()

    def test_exploratory_does_not_generate(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)
        retrofit_md = project_root / ".claude" / "commands" / "retrofit.md"
        assert not retrofit_md.exists()

    def test_generated_content_matches_constant(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        retrofit_md = project_root / ".claude" / "commands" / "retrofit.md"
        assert retrofit_md.read_text() == _RETROFIT_COMMAND

    def test_does_not_overwrite_existing(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        cmd_dir = project_root / ".claude" / "commands"
        cmd_dir.mkdir(parents=True)
        custom = "My custom /retrofit workflow"
        (cmd_dir / "retrofit.md").write_text(custom)

        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        assert (cmd_dir / "retrofit.md").read_text() == custom

    def test_generate_retrofit_command_creates_directories(self, tmp_path: Path) -> None:
        project_root = tmp_path / "new_project"
        project_root.mkdir()
        generate_retrofit_command(project_root)
        assert (project_root / ".claude" / "commands" / "retrofit.md").exists()
