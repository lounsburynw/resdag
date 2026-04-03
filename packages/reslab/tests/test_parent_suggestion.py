"""Tests for parent suggestion via TF-IDF cosine similarity."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.suggest import (
    Suggestion,
    suggest_parents,
    suggest_parents_embedding,
    format_suggestions,
    _tokenize,
    _cosine,
    _idf,
    _tfidf_vector,
)
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


def _claim(text: str, ctype: ClaimType = ClaimType.RESULT, parents: tuple = (), domains: tuple = ()) -> Claim:
    return Claim(claim=text, type=ctype, parents=parents, domain=domains)


# ---------------------------------------------------------------------------
# Unit tests: tokenizer
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_strips_git_trailers(self):
        text = "Grokking happens at 10k steps [command: train.py, git_ref: abc123def456]"
        tokens = _tokenize(text)
        assert "command" not in tokens
        assert "git_ref" not in tokens
        assert "grokking" in tokens
        assert "10k" in tokens

    def test_empty(self):
        assert _tokenize("") == []

    def test_punctuation_split(self):
        assert _tokenize("loss=0.5, accuracy=95%") == ["loss", "0", "5", "accuracy", "95"]


# ---------------------------------------------------------------------------
# Unit tests: TF-IDF internals
# ---------------------------------------------------------------------------

class TestTfIdf:
    def test_idf_single_doc(self):
        docs = [["hello", "world"]]
        result = _idf(docs)
        # Smooth IDF: log(1 + 1/1) = log(2) > 0
        assert result["hello"] > 0
        assert result["world"] > 0

    def test_idf_discriminative(self):
        docs = [["hello", "world"], ["hello", "python"], ["hello", "code"]]
        result = _idf(docs)
        # "hello" in all 3: log(1 + 3/3) = log(2)
        # "world" in 1: log(1 + 3/1) = log(4) — more discriminative
        assert result["world"] > result["hello"]

    def test_cosine_identical(self):
        a = {"x": 1.0, "y": 2.0}
        assert abs(_cosine(a, a) - 1.0) < 1e-9

    def test_cosine_orthogonal(self):
        a = {"x": 1.0}
        b = {"y": 1.0}
        assert _cosine(a, b) == 0.0

    def test_cosine_empty(self):
        assert _cosine({}, {"x": 1.0}) == 0.0


# ---------------------------------------------------------------------------
# Unit tests: suggest_parents
# ---------------------------------------------------------------------------

class TestSuggestParents:
    def test_empty_store(self, store: LocalStore):
        result = suggest_parents(store, "some claim text")
        assert result == []

    def test_single_claim(self, store: LocalStore):
        cid = store.put(_claim("Grokking happens at 10k steps"))
        result = suggest_parents(store, "Grokking threshold at 10k training steps")
        assert len(result) == 1
        assert result[0].cid == cid
        assert result[0].score > 0.0

    def test_ranks_by_similarity(self, store: LocalStore):
        cid_relevant = store.put(_claim("Grokking happens at 10k training steps"))
        cid_tangent = store.put(_claim("Loss converges after 1000 epochs of training"))
        cid_unrelated = store.put(_claim("The weather is sunny today"))

        result = suggest_parents(store, "Grokking threshold observed at 10k steps")
        assert len(result) >= 1
        # Most relevant should be first
        assert result[0].cid == cid_relevant
        # Unrelated claim should not appear (or rank last)
        result_cids = [s.cid for s in result]
        assert cid_unrelated not in result_cids

    def test_respects_n_limit(self, store: LocalStore):
        for i in range(10):
            store.put(_claim(f"Experiment {i} on grokking threshold"))

        result = suggest_parents(store, "Grokking threshold analysis", n=3)
        assert len(result) <= 3

    def test_excludes_cids(self, store: LocalStore):
        cid1 = store.put(_claim("Grokking at 10k steps"))
        cid2 = store.put(_claim("Grokking at 20k steps"))

        result = suggest_parents(store, "Grokking threshold", exclude_cids={cid1})
        cids = {s.cid for s in result}
        assert cid1 not in cids
        assert cid2 in cids

    def test_domain_boost(self, store: LocalStore):
        cid_same_domain = store.put(
            _claim("Loss curve shows transition", domains=("grokking",))
        )
        cid_diff_domain = store.put(
            _claim("Loss curve shows transition", domains=("scaling",))
        )

        result = suggest_parents(
            store, "Loss curve transition point", domains=("grokking",)
        )
        assert len(result) == 2
        # Same domain should score higher due to boost
        assert result[0].cid == cid_same_domain

    def test_no_query_tokens(self, store: LocalStore):
        store.put(_claim("Some claim"))
        result = suggest_parents(store, "!@#$%^&*()")
        assert result == []

    def test_returns_suggestion_dataclass(self, store: LocalStore):
        store.put(_claim("Test claim"))
        result = suggest_parents(store, "Test claim text")
        assert len(result) == 1
        s = result[0]
        assert isinstance(s, Suggestion)
        assert isinstance(s.cid, str)
        assert isinstance(s.score, float)
        assert isinstance(s.claim, Claim)

    def test_git_trailers_ignored(self, store: LocalStore):
        cid = store.put(
            _claim("Grokking happens at 10k steps [command: train.py, git_ref: abc123def456]")
        )
        result = suggest_parents(store, "Grokking at 10k steps")
        assert len(result) == 1
        assert result[0].cid == cid

    def test_multiple_domains_boost(self, store: LocalStore):
        cid_two = store.put(
            _claim("Neural network training result", domains=("grokking", "training"))
        )
        cid_one = store.put(
            _claim("Neural network training result", domains=("grokking",))
        )
        cid_none = store.put(
            _claim("Neural network training result", domains=())
        )

        result = suggest_parents(
            store, "Neural network training result",
            domains=("grokking", "training"),
        )
        assert len(result) == 3
        # Two shared domains > one shared domain > no domains
        assert result[0].cid == cid_two
        assert result[1].cid == cid_one


# ---------------------------------------------------------------------------
# Unit tests: suggest_parents_embedding fallback
# ---------------------------------------------------------------------------

class TestEmbeddingFallback:
    def test_falls_back_to_tfidf(self, store: LocalStore):
        """Without sentence-transformers, should use TF-IDF."""
        cid = store.put(_claim("Grokking happens at 10k steps"))
        result = suggest_parents_embedding(store, "Grokking at 10k steps")
        # Should return results (via TF-IDF fallback)
        assert len(result) >= 1
        assert result[0].cid == cid

    def test_empty_store(self, store: LocalStore):
        result = suggest_parents_embedding(store, "anything")
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests: format_suggestions
# ---------------------------------------------------------------------------

class TestFormatSuggestions:
    def test_empty(self):
        assert format_suggestions([]) == "No similar claims found."

    def test_formatting(self):
        claim = _claim("Test finding about grokking")
        suggestions = [Suggestion(cid="abcdef123456789", score=0.85, claim=claim)]
        text = format_suggestions(suggestions)
        assert "Suggested parents:" in text
        assert "abcdef123456" in text
        assert "0.850" in text
        assert "RESULT" in text
        assert "Test finding about grokking" in text

    def test_truncates_long_text(self):
        long_text = "A" * 200
        claim = _claim(long_text)
        suggestions = [Suggestion(cid="abc123456789", score=0.5, claim=claim)]
        text = format_suggestions(suggestions)
        assert "..." in text

    def test_strips_trailers(self):
        claim = _claim("Finding [command: train.py, git_ref: abc123def456]")
        suggestions = [Suggestion(cid="abc123456789", score=0.5, claim=claim)]
        text = format_suggestions(suggestions)
        assert "command:" not in text
        assert "git_ref:" not in text
        assert "Finding" in text

    def test_numbered(self):
        suggestions = [
            Suggestion(cid="aaa111222333", score=0.9, claim=_claim("First")),
            Suggestion(cid="bbb111222333", score=0.8, claim=_claim("Second")),
            Suggestion(cid="ccc111222333", score=0.7, claim=_claim("Third")),
        ]
        text = format_suggestions(suggestions)
        assert "1." in text
        assert "2." in text
        assert "3." in text


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLISuggestParents:
    def test_hypothesize_suggest_parents(self, project):
        store_path, project_root = project
        runner = CliRunner()

        # Seed the store with claims
        runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize", "Grokking requires 10k steps minimum",
            "-d", "grokking",
            "--repo", str(project_root),
        ])
        runner.invoke(main, [
            "--root", str(store_path),
            "note", "Loss plateau observed at 5k steps",
            "-d", "grokking",
            "--repo", str(project_root),
        ])

        # Now hypothesize with --suggest-parents
        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize", "Grokking threshold depends on step count",
            "-d", "grokking",
            "--suggest-parents",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "Suggested parents:" in result.output

    def test_execute_suggest_parents(self, project):
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize", "Training converges after 10k steps",
            "-d", "training",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "execute", "Convergence observed at 12k steps",
            "-d", "training",
            "--suggest-parents",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "Suggested parents:" in result.output

    def test_note_suggest_parents(self, project):
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path),
            "note", "Grokking happens at 10k steps",
            "-d", "grokking",
            "--repo", str(project_root),
        ])

        result = runner.invoke(main, [
            "--root", str(store_path),
            "note", "Grokking also at 20k steps",
            "-d", "grokking",
            "--suggest-parents",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "Suggested parents:" in result.output

    def test_suggest_parents_empty_store(self, project):
        store_path, project_root = project
        runner = CliRunner()

        result = runner.invoke(main, [
            "--root", str(store_path),
            "hypothesize", "Some new hypothesis",
            "--suggest-parents",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "No similar claims found." in result.output

    def test_suggest_parents_without_flag(self, project):
        store_path, project_root = project
        runner = CliRunner()

        runner.invoke(main, [
            "--root", str(store_path),
            "note", "Grokking at 10k",
            "--repo", str(project_root),
        ])

        # Without --suggest-parents, no suggestions shown
        result = runner.invoke(main, [
            "--root", str(store_path),
            "note", "Grokking at 20k",
            "--repo", str(project_root),
        ])
        assert result.exit_code == 0
        assert "Suggested parents:" not in result.output
