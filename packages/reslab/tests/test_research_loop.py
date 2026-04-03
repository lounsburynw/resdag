"""Tests for /research slash command generation and content."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from resdag.storage.local import LocalStore

from reslab.profiles import (
    ProfileMode,
    _RESEARCH_COMMAND,
    generate_research_command,
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

class TestResearchCommandReferences:
    """The prompt must reference the config files the agent needs to read."""

    def test_references_profile_json(self) -> None:
        assert "profile.json" in _RESEARCH_COMMAND

    def test_references_vocabulary_json(self) -> None:
        assert "vocabulary.json" in _RESEARCH_COMMAND

    def test_references_result_template(self) -> None:
        assert "templates/result.md" in _RESEARCH_COMMAND

    def test_references_hypothesis_template(self) -> None:
        assert "templates/hypothesis.md" in _RESEARCH_COMMAND

    def test_references_audience(self) -> None:
        assert "audience" in _RESEARCH_COMMAND.lower()


# ---------------------------------------------------------------------------
# Prompt content — frontier identification
# ---------------------------------------------------------------------------

class TestResearchCommandFrontier:
    """The prompt must describe how to identify the research frontier."""

    def test_identifies_open_hypotheses(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "open hypothes" in text

    def test_identifies_refutation_patterns(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "refutation" in text

    def test_identifies_untested_implications(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "untested" in text or "implication" in text

    def test_identifies_stalled_threads(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "stalled" in text

    def test_identifies_cross_thread_connections(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "cross-thread" in text or "cross thread" in text

    def test_prioritizes_frontier_sources(self) -> None:
        """The five frontier sources should appear in priority order."""
        text = _RESEARCH_COMMAND
        open_pos = text.index("Open hypotheses")
        refutation_pos = text.index("Refutation patterns")
        assert open_pos < refutation_pos


# ---------------------------------------------------------------------------
# Prompt content — experiment proposal
# ---------------------------------------------------------------------------

class TestResearchCommandProposal:
    """The prompt must require structured experiment proposals."""

    def test_requires_hypothesis_field(self) -> None:
        assert "Hypothesis" in _RESEARCH_COMMAND

    def test_requires_rationale_field(self) -> None:
        assert "Rationale" in _RESEARCH_COMMAND

    def test_requires_method_field(self) -> None:
        assert "Method" in _RESEARCH_COMMAND

    def test_requires_success_criteria(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "success criteria" in text

    def test_requires_failure_criteria(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "failure criteria" in text

    def test_rationale_must_cite_claims(self) -> None:
        """Rationale must reference specific claim CIDs, not vague references."""
        assert "cite specific claim" in _RESEARCH_COMMAND.lower() or \
               "cite specific prior" in _RESEARCH_COMMAND.lower()

    def test_empty_frontier_handling(self) -> None:
        """The prompt must handle the case where there's nothing to do."""
        text = _RESEARCH_COMMAND.lower()
        assert "frontier is empty" in text or "empty" in text


# ---------------------------------------------------------------------------
# Prompt content — workflow commands
# ---------------------------------------------------------------------------

class TestResearchCommandWorkflow:
    """The prompt must include the exact CLI commands for each step."""

    def test_includes_lab_threads_open(self) -> None:
        assert "lab threads --open" in _RESEARCH_COMMAND

    def test_includes_lab_threads_json(self) -> None:
        assert "lab threads --json" in _RESEARCH_COMMAND

    def test_includes_lab_audit_json(self) -> None:
        assert "lab audit --json" in _RESEARCH_COMMAND

    def test_includes_res_log_type_refutation(self) -> None:
        assert "res log --type refutation" in _RESEARCH_COMMAND

    def test_includes_res_show(self) -> None:
        assert "res show" in _RESEARCH_COMMAND

    def test_includes_res_lineage(self) -> None:
        assert "res lineage" in _RESEARCH_COMMAND

    def test_includes_lab_hypothesize(self) -> None:
        assert "lab hypothesize" in _RESEARCH_COMMAND

    def test_includes_lab_execute(self) -> None:
        assert "lab execute" in _RESEARCH_COMMAND

    def test_includes_lab_interpret_confirmed(self) -> None:
        assert "--confirmed" in _RESEARCH_COMMAND

    def test_includes_lab_interpret_refuted(self) -> None:
        assert "--refuted" in _RESEARCH_COMMAND

    def test_includes_lab_branch(self) -> None:
        assert "lab branch" in _RESEARCH_COMMAND

    def test_includes_suggest_parents(self) -> None:
        assert "--suggest-parents" in _RESEARCH_COMMAND

    def test_includes_no_validate(self) -> None:
        assert "--no-validate" in _RESEARCH_COMMAND

    def test_includes_domain_flag(self) -> None:
        assert "-d <domain>" in _RESEARCH_COMMAND or "-d <tag>" in _RESEARCH_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — guard rails
# ---------------------------------------------------------------------------

class TestResearchCommandGuardRails:
    """The prompt must enforce safety limits on the research loop."""

    def test_verification_budget(self) -> None:
        """Max 3 experiments per invocation."""
        text = _RESEARCH_COMMAND.lower()
        assert "verification budget" in text or "budget" in text

    def test_max_experiments_per_invocation(self) -> None:
        assert "3 experiments" in _RESEARCH_COMMAND or "max 3" in _RESEARCH_COMMAND.lower()

    def test_thread_depth_limit(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "thread depth" in text or "depth limit" in text

    def test_scope_limit(self) -> None:
        """Each experiment must be single-session scope."""
        text = _RESEARCH_COMMAND.lower()
        assert "scope" in text

    def test_depth_threshold(self) -> None:
        """Thread depth threshold should be specified (10 claims)."""
        assert "10" in _RESEARCH_COMMAND


# ---------------------------------------------------------------------------
# Prompt content — assessment cycle
# ---------------------------------------------------------------------------

class TestResearchCommandAssessment:
    """The prompt must include continue/branch/abandon/confirm assessment."""

    def test_continue_option(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "continue" in text

    def test_branch_option(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "branch" in text

    def test_abandon_option(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "abandon" in text

    def test_confirm_option(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "confirm" in text

    def test_assessment_after_commit(self) -> None:
        """Assessment must come after committing results."""
        commit_pos = _RESEARCH_COMMAND.index("Commit results")
        assess_pos = _RESEARCH_COMMAND.index("Assess and recommend")
        assert commit_pos < assess_pos


# ---------------------------------------------------------------------------
# Prompt content — user confirmation
# ---------------------------------------------------------------------------

class TestResearchCommandConfirmation:
    """The prompt must require human approval before executing experiments."""

    def test_user_approval_required(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "approv" in text or "confirm" in text

    def test_do_not_proceed_without_approval(self) -> None:
        text = _RESEARCH_COMMAND
        assert "Do NOT proceed" in text or "Do NOT" in text

    def test_presents_proposal_before_execution(self) -> None:
        """Proposal must come before execution step."""
        proposal_pos = _RESEARCH_COMMAND.index("Propose the next experiment")
        execute_pos = _RESEARCH_COMMAND.index("Execute the experiment")
        assert proposal_pos < execute_pos


# ---------------------------------------------------------------------------
# Prompt content — before/after DAG health
# ---------------------------------------------------------------------------

class TestResearchCommandHealth:
    """The prompt must compare DAG health before and after the cycle."""

    def test_mentions_before_after(self) -> None:
        assert "Before" in _RESEARCH_COMMAND and "After" in _RESEARCH_COMMAND

    def test_mentions_hypothesis_coverage(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "hypothesis coverage" in text

    def test_mentions_orphan_rate(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "orphan rate" in text

    def test_mentions_branch_ratio(self) -> None:
        text = _RESEARCH_COMMAND.lower()
        assert "branch ratio" in text

    def test_audit_before_and_after(self) -> None:
        """lab audit --json must appear at least twice (before + after)."""
        count = _RESEARCH_COMMAND.count("lab audit --json")
        assert count >= 2


# ---------------------------------------------------------------------------
# Prompt content — completeness
# ---------------------------------------------------------------------------

class TestResearchCommandCompleteness:
    """The prompt must be a complete, actionable guide — not a stub."""

    def test_is_substantially_longer_than_stub(self) -> None:
        """The comprehensive prompt should be >2000 characters."""
        assert len(_RESEARCH_COMMAND) > 2000

    def test_has_multiple_steps(self) -> None:
        """Should have numbered steps (## Step N)."""
        assert "Step 0" in _RESEARCH_COMMAND
        assert "Step 7" in _RESEARCH_COMMAND

    def test_includes_quick_reference(self) -> None:
        assert "Quick reference" in _RESEARCH_COMMAND or "quick reference" in _RESEARCH_COMMAND.lower()

    def test_includes_frontier_analysis(self) -> None:
        """Should describe how to analyze the research frontier."""
        assert "frontier" in _RESEARCH_COMMAND.lower()

    def test_includes_experiment_proposal_table(self) -> None:
        """Should have a structured proposal format."""
        assert "Experiment proposal" in _RESEARCH_COMMAND or "proposal" in _RESEARCH_COMMAND.lower()

    def test_includes_next_cycle_recommendation(self) -> None:
        """Should propose the next cycle at the end."""
        assert "next cycle" in _RESEARCH_COMMAND.lower()


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

class TestResearchCommandGeneration:
    """Verify that lab init generates research.md correctly."""

    def test_disciplined_generates_research_md(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        research_md = project_root / ".claude" / "commands" / "research.md"
        assert research_md.exists()

    def test_strict_generates_research_md(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.STRICT)
        research_md = project_root / ".claude" / "commands" / "research.md"
        assert research_md.exists()

    def test_exploratory_does_not_generate(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)
        research_md = project_root / ".claude" / "commands" / "research.md"
        assert not research_md.exists()

    def test_generated_content_matches_constant(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        research_md = project_root / ".claude" / "commands" / "research.md"
        assert research_md.read_text() == _RESEARCH_COMMAND

    def test_does_not_overwrite_existing(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        cmd_dir = project_root / ".claude" / "commands"
        cmd_dir.mkdir(parents=True)
        custom = "My custom /research workflow"
        (cmd_dir / "research.md").write_text(custom)

        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        assert (cmd_dir / "research.md").read_text() == custom

    def test_generate_research_command_creates_directories(self, tmp_path: Path) -> None:
        project_root = tmp_path / "new_project"
        project_root.mkdir()
        generate_research_command(project_root)
        assert (project_root / ".claude" / "commands" / "research.md").exists()
