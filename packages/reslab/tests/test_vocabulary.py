"""Tests for controlled vocabulary system."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.vocabulary import (
    Vocabulary,
    default_vocabulary,
    load_vocabulary,
    save_vocabulary,
)


@pytest.fixture()
def vocab() -> Vocabulary:
    """A small test vocabulary."""
    return Vocabulary(
        tags={
            "lean": "Lean theorem prover",
            "verification": "Formal verification",
            "training": "Model training",
            "grokking": "Delayed generalization",
            "data": "Datasets and preprocessing",
        },
        aliases={
            "lean-verification": ["lean", "verification"],
            "lean-traces": ["lean", "training"],
            "finetuning": ["training"],
            "dataset": ["data"],
        },
        subtags={
            "pantograph": ["lean"],
            "mathlib": ["lean"],
            "lora": ["training"],
        },
    )


# -------------------------------------------------------------------
# Vocabulary.normalize
# -------------------------------------------------------------------


class TestNormalize:
    def test_canonical_tag_passes_through(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["lean"])
        assert tags == ["lean"]
        assert warnings == []

    def test_multiple_canonical_tags(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["training", "grokking"])
        assert tags == ["grokking", "training"]
        assert warnings == []

    def test_alias_expands_to_canonical(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["finetuning"])
        assert tags == ["training"]
        assert warnings == []

    def test_multi_tag_alias(self, vocab: Vocabulary) -> None:
        """lean-verification expands to ['lean', 'verification']."""
        tags, warnings = vocab.normalize(["lean-verification"])
        assert tags == ["lean", "verification"]
        assert warnings == []

    def test_unknown_tag_warns_with_suggestions(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["foobar"])
        assert "foobar" in tags  # unknown tags still included
        assert len(warnings) == 1
        assert warnings[0][0] == "foobar"

    def test_unknown_tag_near_match(self, vocab: Vocabulary) -> None:
        """An unknown tag close to a canonical tag gets suggestions."""
        tags, warnings = vocab.normalize(["trainingg"])
        assert len(warnings) == 1
        assert "training" in warnings[0][1]

    def test_deduplication(self, vocab: Vocabulary) -> None:
        """Duplicate canonical tags are deduplicated."""
        tags, warnings = vocab.normalize(["lean", "lean-verification"])
        assert tags == ["lean", "verification"]
        assert warnings == []

    def test_mixed_canonical_alias_unknown(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["grokking", "finetuning", "foobar"])
        assert "grokking" in tags
        assert "training" in tags
        assert "foobar" in tags
        assert len(warnings) == 1

    def test_empty_input(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize([])
        assert tags == []
        assert warnings == []

    def test_results_are_sorted(self, vocab: Vocabulary) -> None:
        tags, _ = vocab.normalize(["training", "data", "lean"])
        assert tags == sorted(tags)


# -------------------------------------------------------------------
# Subtag normalization (vocabulary_hierarchy)
# -------------------------------------------------------------------


class TestSubtagNormalize:
    """Subtags preserve the original tag and add parent canonical tag(s)."""

    def test_subtag_preserves_original_and_adds_parent(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["pantograph"])
        assert "pantograph" in tags
        assert "lean" in tags
        assert warnings == []

    def test_subtag_stores_both_tags_sorted(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["pantograph"])
        assert tags == ["lean", "pantograph"]

    def test_alias_replaces_original(self, vocab: Vocabulary) -> None:
        """Aliases still replace — finetuning disappears, training appears."""
        tags, warnings = vocab.normalize(["finetuning"])
        assert tags == ["training"]
        assert "finetuning" not in tags

    def test_subtag_with_parent_already_present(self, vocab: Vocabulary) -> None:
        """If the parent is already in domains, no duplicate."""
        tags, warnings = vocab.normalize(["lean", "pantograph"])
        assert tags == ["lean", "pantograph"]

    def test_multiple_subtags_same_parent(self, vocab: Vocabulary) -> None:
        tags, warnings = vocab.normalize(["pantograph", "mathlib"])
        assert tags == ["lean", "mathlib", "pantograph"]

    def test_subtag_and_alias_together(self, vocab: Vocabulary) -> None:
        """Subtag pantograph + alias finetuning."""
        tags, warnings = vocab.normalize(["pantograph", "finetuning"])
        assert "pantograph" in tags
        assert "lean" in tags
        assert "training" in tags
        assert "finetuning" not in tags

    def test_subtag_no_warning(self, vocab: Vocabulary) -> None:
        """Subtags are recognized — no unknown-tag warning."""
        _, warnings = vocab.normalize(["pantograph"])
        assert warnings == []

    def test_subtag_fuzzy_match(self, vocab: Vocabulary) -> None:
        """Near-miss of a subtag gets suggestion."""
        tags, warnings = vocab.normalize(["pantograpp"])
        assert len(warnings) == 1
        assert "pantograph" in warnings[0][1]

    def test_subtag_with_multiple_parents(self) -> None:
        """A subtag can map to multiple parent tags."""
        v = Vocabulary(
            tags={"lean": "Lean", "tooling": "Tools"},
            aliases={},
            subtags={"pantograph": ["lean", "tooling"]},
        )
        tags, warnings = v.normalize(["pantograph"])
        assert tags == ["lean", "pantograph", "tooling"]
        assert warnings == []


class TestBackwardCompatibility:
    """Vocabulary without subtags still works (alias-only config)."""

    def test_alias_only_vocabulary(self) -> None:
        v = Vocabulary(
            tags={"training": "Training", "lean": "Lean"},
            aliases={"finetuning": ["training"]},
        )
        tags, warnings = v.normalize(["finetuning"])
        assert tags == ["training"]
        assert warnings == []

    def test_from_dict_without_subtags(self) -> None:
        data = {"tags": {"lean": "Lean"}, "aliases": {"l": ["lean"]}}
        v = Vocabulary.from_dict(data)
        assert v.subtags == {}
        tags, _ = v.normalize(["l"])
        assert tags == ["lean"]

    def test_to_dict_omits_empty_subtags(self) -> None:
        v = Vocabulary(tags={"lean": "Lean"}, aliases={})
        d = v.to_dict()
        assert "subtags" not in d

    def test_to_dict_includes_subtags_when_present(self, vocab: Vocabulary) -> None:
        d = vocab.to_dict()
        assert "subtags" in d
        assert "pantograph" in d["subtags"]


# -------------------------------------------------------------------
# Persistence
# -------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load(self, tmp_path: Path, vocab: Vocabulary) -> None:
        save_vocabulary(vocab, tmp_path)
        loaded = load_vocabulary(tmp_path)
        assert loaded is not None
        assert loaded.tags == vocab.tags
        assert loaded.aliases == vocab.aliases
        assert loaded.subtags == vocab.subtags

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_vocabulary(tmp_path) is None

    def test_round_trip_normalization(self, tmp_path: Path, vocab: Vocabulary) -> None:
        """Saved and loaded vocab normalizes identically."""
        save_vocabulary(vocab, tmp_path)
        loaded = load_vocabulary(tmp_path)
        assert loaded is not None
        original = vocab.normalize(["lean-verification", "finetuning"])
        reloaded = loaded.normalize(["lean-verification", "finetuning"])
        assert original == reloaded


# -------------------------------------------------------------------
# Default vocabulary
# -------------------------------------------------------------------


class TestDefaultVocabulary:
    def test_has_12_to_15_tags(self) -> None:
        vocab = default_vocabulary()
        count = len(vocab.tags)
        assert 12 <= count <= 15, f"Expected 12-15 canonical tags, got {count}"

    def test_aliases_resolve_to_canonical_tags(self) -> None:
        vocab = default_vocabulary()
        for alias, targets in vocab.aliases.items():
            for target in targets:
                assert target in vocab.tags, (
                    f"Alias '{alias}' maps to '{target}' which is not a canonical tag"
                )

    def test_subtags_resolve_to_canonical_parents(self) -> None:
        vocab = default_vocabulary()
        for subtag, parents in vocab.subtags.items():
            for parent in parents:
                assert parent in vocab.tags, (
                    f"Subtag '{subtag}' maps to parent '{parent}' which is not a canonical tag"
                )

    def test_lean_verification_alias(self) -> None:
        vocab = default_vocabulary()
        tags, warnings = vocab.normalize(["lean-verification"])
        assert tags == ["lean", "verification"]
        assert warnings == []

    def test_pantograph_subtag(self) -> None:
        vocab = default_vocabulary()
        tags, warnings = vocab.normalize(["pantograph"])
        assert tags == ["lean", "pantograph"]
        assert warnings == []

    def test_has_subtags(self) -> None:
        vocab = default_vocabulary()
        assert len(vocab.subtags) > 0

    def test_no_overlap_aliases_subtags(self) -> None:
        """Aliases and subtags should not share keys."""
        vocab = default_vocabulary()
        overlap = set(vocab.aliases.keys()) & set(vocab.subtags.keys())
        assert overlap == set(), f"Overlap between aliases and subtags: {overlap}"


# -------------------------------------------------------------------
# Vocabulary.canonical_tags
# -------------------------------------------------------------------


def test_canonical_tags_sorted(vocab: Vocabulary) -> None:
    result = vocab.canonical_tags()
    assert result == sorted(vocab.tags.keys())


# -------------------------------------------------------------------
# CLI integration
# -------------------------------------------------------------------


@pytest.fixture()
def store_and_repo(tmp_path: Path) -> tuple[LocalStore, Path]:
    """Create a resdag store and git repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    dummy = repo / "README.md"
    dummy.write_text("init")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True,
        check=True,
    )

    store_path = tmp_path / ".resdag"
    store = LocalStore(str(store_path))
    return store, repo


class TestCLINormalization:
    def test_hypothesize_normalizes_domains(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "hypothesize", "--domain", "lean-verification",
             "--repo", str(repo), "Test hypothesis"],
        )
        assert result.exit_code == 0

        # Check the stored claim has normalized domains
        cids = store.list_cids()
        assert len(cids) == 1
        claim = store.get(cids[0])
        assert "lean" in claim.domain
        assert "verification" in claim.domain

    def test_unknown_domain_prints_warning(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "hypothesize", "--domain", "foobar",
             "--repo", str(repo), "Test hypothesis"],
        )
        assert result.exit_code == 0
        assert "foobar" in result.output
        assert "unknown" in result.output.lower() or "Unknown" in result.output

    def test_no_vocab_passthrough(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        """Without vocabulary, domains pass through unchanged."""
        from reslab.cli import main

        store, repo = store_and_repo
        # No vocabulary saved

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "hypothesize", "--domain", "my-custom-tag",
             "--repo", str(repo), "Test hypothesis"],
        )
        assert result.exit_code == 0
        cids = store.list_cids()
        claim = store.get(cids[0])
        assert claim.domain == ("my-custom-tag",)


class TestMigrateTags:
    def test_migrate_normalizes_tags(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo

        # Create claims with non-canonical tags
        c1 = Claim(claim="result one", type=ClaimType.RESULT, domain=("finetuning",))
        c2 = Claim(claim="result two", type=ClaimType.RESULT, domain=("lean-verification",))
        c3 = Claim(claim="result three", type=ClaimType.RESULT, domain=("training",))  # already canonical
        store.put(c1)
        store.put(c2)
        store.put(c3)

        # Save vocabulary
        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "migrate-tags"],
        )
        assert result.exit_code == 0
        assert "2" in result.output  # 2 claims needed migration (c1 and c2)

    def test_migrate_creates_supersession(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo

        c1 = Claim(claim="result one", type=ClaimType.RESULT, domain=("finetuning",))
        old_cid = store.put(c1)

        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "migrate-tags"],
        )
        assert result.exit_code == 0

        # Should have 3 claims: original + new + supersession refutation
        cids = store.list_cids()
        assert len(cids) == 3

        # Find the refutation
        refutations = [store.get(c) for c in cids if store.get(c).type == ClaimType.REFUTATION]
        assert len(refutations) == 1
        assert old_cid in refutations[0].parents

    def test_migrate_no_vocab_fails(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "migrate-tags"],
        )
        assert result.exit_code != 0

    def test_migrate_already_canonical(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        """Claims with already-canonical tags are not migrated."""
        from reslab.cli import main

        store, repo = store_and_repo

        c1 = Claim(claim="result one", type=ClaimType.RESULT, domain=("training",))
        store.put(c1)

        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "migrate-tags"],
        )
        assert result.exit_code == 0
        assert "0" in result.output  # nothing to migrate
        assert len(store.list_cids()) == 1  # no new claims created


# -------------------------------------------------------------------
# CLI: lab vocab analyze
# -------------------------------------------------------------------


class TestVocabAnalyze:
    def test_analyze_reports_changes(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo

        # Create claims: one with subtag, one with alias, one canonical
        store.put(Claim(claim="subtag claim", type=ClaimType.RESULT, domain=("pantograph",)))
        store.put(Claim(claim="alias claim", type=ClaimType.RESULT, domain=("finetuning",)))
        store.put(Claim(claim="canonical claim", type=ClaimType.RESULT, domain=("training",)))

        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store.root), "vocab", "analyze"])
        assert result.exit_code == 0
        assert "2/3" in result.output  # pantograph and finetuning change

    def test_analyze_does_not_modify_store(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        store.put(Claim(claim="subtag claim", type=ClaimType.RESULT, domain=("pantograph",)))

        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        cids_before = set(store.list_cids())
        runner = CliRunner()
        runner.invoke(main, ["--root", str(store.root), "vocab", "analyze"])
        cids_after = set(store.list_cids())
        assert cids_before == cids_after

    def test_analyze_no_vocab_fails(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store.root), "vocab", "analyze"])
        assert result.exit_code != 0

    def test_analyze_shows_subtag_expansion(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        store.put(Claim(claim="pantograph claim", type=ClaimType.RESULT, domain=("pantograph",)))

        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store.root), "vocab", "analyze"])
        assert result.exit_code == 0
        assert "pantograph" in result.output
        assert "lean" in result.output

    def test_analyze_all_canonical_no_changes(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        store.put(Claim(claim="canonical", type=ClaimType.RESULT, domain=("training",)))

        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(main, ["--root", str(store.root), "vocab", "analyze"])
        assert result.exit_code == 0
        assert "0/1" in result.output


# -------------------------------------------------------------------
# CLI: subtag normalization through commands
# -------------------------------------------------------------------


class TestCLISubtagNormalization:
    def test_hypothesize_subtag_preserves_original(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "hypothesize", "--domain", "pantograph",
             "--repo", str(repo), "Test pantograph hypothesis"],
        )
        assert result.exit_code == 0

        cids = store.list_cids()
        assert len(cids) == 1
        claim = store.get(cids[0])
        assert "pantograph" in claim.domain
        assert "lean" in claim.domain

    def test_hypothesize_alias_replaces(self, store_and_repo: tuple[LocalStore, Path]) -> None:
        from reslab.cli import main

        store, repo = store_and_repo
        vocab = default_vocabulary()
        save_vocabulary(vocab, store.root)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--root", str(store.root), "hypothesize", "--domain", "finetuning",
             "--repo", str(repo), "Test finetuning hypothesis"],
        )
        assert result.exit_code == 0

        cids = store.list_cids()
        claim = store.get(cids[0])
        assert claim.domain == ("training",)
        assert "finetuning" not in claim.domain
