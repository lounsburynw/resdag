"""Tests for project profiles (lab init --mode)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.cli import main
from reslab.profiles import (
    Profile,
    ProfileMode,
    ValidationRules,
    dag_health_summary,
    generate_claude_fragment,
    generate_templates,
    init_profile,
    load_profile,
    mode_defaults,
    save_profile,
    update_claude_md,
)
from reslab.vocabulary import load_vocabulary


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


# ---------------------------------------------------------------------------
# mode_defaults
# ---------------------------------------------------------------------------

class TestModeDefaults:
    def test_exploratory_defaults(self) -> None:
        rules = mode_defaults(ProfileMode.EXPLORATORY)
        assert rules.hypothesis_parent == "off"
        assert rules.claim_structure == "off"
        assert rules.vocabulary == "warn"

    def test_disciplined_defaults(self) -> None:
        rules = mode_defaults(ProfileMode.DISCIPLINED)
        assert rules.hypothesis_parent == "warn"
        assert rules.claim_structure == "warn"
        assert rules.vocabulary == "warn"

    def test_strict_defaults(self) -> None:
        rules = mode_defaults(ProfileMode.STRICT)
        assert rules.hypothesis_parent == "require"
        assert rules.claim_structure == "require"
        assert rules.vocabulary == "require"


# ---------------------------------------------------------------------------
# Profile persistence
# ---------------------------------------------------------------------------

class TestProfilePersistence:
    def test_save_and_load(self, tmp_path: Path) -> None:
        profile = Profile(
            mode="disciplined",
            project="Test",
            audience="ML researchers",
            validation=ValidationRules(
                hypothesis_parent="warn",
                claim_structure="warn",
                vocabulary="warn",
            ),
        )
        save_profile(profile, tmp_path)
        loaded = load_profile(tmp_path)
        assert loaded is not None
        assert loaded.mode == "disciplined"
        assert loaded.project == "Test"
        assert loaded.audience == "ML researchers"
        assert loaded.validation.hypothesis_parent == "warn"

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_profile(tmp_path) is None

    def test_profile_json_is_valid(self, tmp_path: Path) -> None:
        profile = Profile(
            mode="strict",
            project="P",
            audience="A",
            validation=mode_defaults(ProfileMode.STRICT),
        )
        save_profile(profile, tmp_path)
        raw = json.loads((tmp_path / "profile.json").read_text())
        assert raw["mode"] == "strict"
        assert "validation" in raw
        assert raw["validation"]["hypothesis_parent"] == "require"


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_generates_three_templates(self, tmp_path: Path) -> None:
        generate_templates(tmp_path)
        assert (tmp_path / "templates" / "hypothesis.md").exists()
        assert (tmp_path / "templates" / "result.md").exists()
        assert (tmp_path / "templates" / "method.md").exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        generate_templates(tmp_path)
        custom = "Custom template content"
        (tmp_path / "templates" / "result.md").write_text(custom)
        generate_templates(tmp_path)
        assert (tmp_path / "templates" / "result.md").read_text() == custom

    def test_templates_contain_section_markers(self, tmp_path: Path) -> None:
        generate_templates(tmp_path)
        result = (tmp_path / "templates" / "result.md").read_text()
        assert "Question:" in result
        assert "Finding:" in result
        hyp = (tmp_path / "templates" / "hypothesis.md").read_text()
        assert "Prediction:" in hyp


# ---------------------------------------------------------------------------
# CLAUDE.md fragment
# ---------------------------------------------------------------------------

class TestClaudeFragment:
    def test_exploratory_fragment(self) -> None:
        frag = generate_claude_fragment(ProfileMode.EXPLORATORY, "", ["training", "lean"])
        assert "lab execute" in frag
        assert "lab note" in frag
        assert "training" in frag

    def test_disciplined_fragment(self) -> None:
        frag = generate_claude_fragment(ProfileMode.DISCIPLINED, "ML researchers", ["lean"])
        assert "/claim" in frag
        assert "ML researchers" in frag

    def test_strict_fragment(self) -> None:
        frag = generate_claude_fragment(ProfileMode.STRICT, "reviewers", ["lean"])
        assert "required" in frag
        assert "templates" in frag
        assert "rejected" in frag

    def test_update_claude_md_creates_file(self, tmp_path: Path) -> None:
        update_claude_md(tmp_path, "## Research Claims (reslab)\nContent here.\n")
        assert (tmp_path / "CLAUDE.md").exists()
        assert "Content here" in (tmp_path / "CLAUDE.md").read_text()

    def test_update_claude_md_appends(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nExisting content.\n")
        update_claude_md(tmp_path, "## Research Claims (reslab)\nNew section.\n")
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Existing content" in content
        assert "New section" in content

    def test_update_claude_md_replaces_existing_section(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text(
            "# My Project\n\n## Research Claims (reslab)\nOld content.\n\n## Other Section\nKept.\n"
        )
        update_claude_md(tmp_path, "## Research Claims (reslab)\nUpdated content.\n")
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Old content" not in content
        assert "Updated content" in content
        assert "Other Section" in content
        assert "Kept" in content


# ---------------------------------------------------------------------------
# DAG health
# ---------------------------------------------------------------------------

class TestDAGHealth:
    def test_empty_store(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        store = LocalStore(str(store_path))
        health = dag_health_summary(store)
        assert health["total_claims"] == 0
        assert health["orphan_rate"] == 0.0

    def test_with_claims(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        store = LocalStore(str(store_path))

        # 1 hypothesis (root — not an orphan)
        h = Claim(claim="H1", type=ClaimType.HYPOTHESIS)
        h_cid = store.put(h)

        # 1 result with parent (not orphan)
        r1 = Claim(claim="R1", type=ClaimType.RESULT, parents=(h_cid,))
        store.put(r1)

        # 1 orphan result (no parents, not hypothesis)
        r2 = Claim(claim="R2", type=ClaimType.RESULT)
        store.put(r2)

        health = dag_health_summary(store)
        assert health["total_claims"] == 3
        assert health["hypothesis_count"] == 1
        assert health["orphan_count"] == 1
        assert health["orphan_rate"] == 0.33

    def test_structure_coverage(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        store = LocalStore(str(store_path))

        # Structured result
        store.put(Claim(
            claim="Question: X\nFinding: Y\nImplication: Z",
            type=ClaimType.RESULT,
        ))
        # Unstructured result
        store.put(Claim(claim="Just a result", type=ClaimType.RESULT))

        health = dag_health_summary(store)
        assert health["structure_coverage"] == 0.5


# ---------------------------------------------------------------------------
# init_profile (high-level)
# ---------------------------------------------------------------------------

class TestInitProfile:
    def test_exploratory_creates_profile_and_vocab_only(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)

        assert (store_path / "profile.json").exists()
        assert (store_path / "vocabulary.json").exists()
        # No templates or slash commands for exploratory
        assert not (store_path / "templates").exists()
        assert not (project_root / ".claude" / "commands" / "claim.md").exists()

    def test_disciplined_creates_all_artifacts(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED, audience="ML researchers")

        assert (store_path / "profile.json").exists()
        assert (store_path / "vocabulary.json").exists()
        assert (store_path / "templates" / "hypothesis.md").exists()
        assert (store_path / "templates" / "result.md").exists()
        assert (store_path / "templates" / "method.md").exists()
        assert (project_root / ".claude" / "commands" / "claim.md").exists()
        assert (project_root / ".claude" / "commands" / "retrofit.md").exists()
        assert (project_root / "CLAUDE.md").exists()
        # No critic for disciplined
        assert not (project_root / ".critics" / "claims.review.critic.md").exists()

    def test_strict_creates_critic(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.STRICT)

        assert (store_path / "templates").exists()
        assert (project_root / ".claude" / "commands" / "claim.md").exists()
        assert (project_root / ".claude" / "commands" / "retrofit.md").exists()
        assert (project_root / ".critics" / "claims.review.critic.md").exists()

    def test_reinit_updates_profile_without_deleting_claims(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        store = LocalStore(str(store_path))

        # Add a claim
        c = Claim(claim="Existing claim", type=ClaimType.RESULT)
        cid = store.put(c)

        # Init exploratory
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)
        assert load_profile(store_path).mode == "exploratory"

        # Re-init as disciplined
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)
        assert load_profile(store_path).mode == "disciplined"

        # Claim still exists
        assert store.has(cid)
        assert store.get(cid).claim == "Existing claim"

    def test_preserves_existing_vocabulary(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        from reslab.vocabulary import Vocabulary, save_vocabulary

        custom_vocab = Vocabulary(
            tags={"custom": "A custom tag"},
            aliases={"c": ["custom"]},
        )
        save_vocabulary(custom_vocab, store_path)

        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)

        loaded = load_vocabulary(store_path)
        assert "custom" in loaded.tags  # preserved, not overwritten


# ---------------------------------------------------------------------------
# CLI: lab init
# ---------------------------------------------------------------------------

class TestCLIInit:
    def test_init_exploratory(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "init", "--mode", "exploratory"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "exploratory" in result.output
        assert (store_path / "profile.json").exists()

    def test_init_disciplined(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()

        # cd to project root so CLAUDE.md lands there
        with runner.isolated_filesystem(temp_dir=project_root) as td:
            result = runner.invoke(
                main,
                ["--root", str(store_path), "init", "--mode", "disciplined", "--audience", "ML researchers"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "disciplined" in result.output

    def test_init_strict(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=project_root) as td:
            result = runner.invoke(
                main,
                ["--root", str(store_path), "init", "--mode", "strict"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "strict" in result.output

    def test_init_existing_store_reports_health(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        store = LocalStore(str(store_path))

        # Add some claims
        h = Claim(claim="H1", type=ClaimType.HYPOTHESIS)
        h_cid = store.put(h)
        store.put(Claim(claim="R1", type=ClaimType.RESULT, parents=(h_cid,)))
        store.put(Claim(claim="R2 orphan", type=ClaimType.RESULT))

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=project_root) as td:
            result = runner.invoke(
                main,
                ["--root", str(store_path), "init", "--mode", "disciplined"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "3 claims" in result.output
        assert "1 hypotheses" in result.output
        assert "1 orphans" in result.output
        assert "/retrofit" in result.output

    def test_init_empty_store_no_health(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "init", "--mode", "exploratory"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "Existing DAG" not in result.output


# ---------------------------------------------------------------------------
# CLI: lab config set
# ---------------------------------------------------------------------------

class TestCLIConfig:
    def test_config_set_mode(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project

        # First init
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=project_root) as td:
            result = runner.invoke(
                main,
                ["--root", str(store_path), "config", "set", "mode", "strict"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "strict" in result.output

        profile = load_profile(store_path)
        assert profile.mode == "strict"
        assert profile.validation.hypothesis_parent == "require"

    def test_config_set_audience(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.DISCIPLINED)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "config", "set", "audience", "PhD committee"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        profile = load_profile(store_path)
        assert profile.audience == "PhD committee"

    def test_config_set_no_profile_fails(self, project: tuple[Path, Path]) -> None:
        store_path, _ = project
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "config", "set", "mode", "strict"],
        )
        assert result.exit_code != 0
        assert "No profile.json" in result.output

    def test_config_set_invalid_mode_fails(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "config", "set", "mode", "invalid"],
        )
        assert result.exit_code != 0

    def test_config_set_unknown_key_fails(self, project: tuple[Path, Path]) -> None:
        store_path, project_root = project
        init_profile(store_path, project_root, ProfileMode.EXPLORATORY)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store_path), "config", "set", "unknown", "value"],
        )
        assert result.exit_code != 0
