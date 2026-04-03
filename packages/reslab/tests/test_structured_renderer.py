"""Tests for structured claim rendering and render-time heuristics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from resdag.storage.local import LocalStore

from reslab import workflow
from reslab.site.renderer import generate_site
from reslab.site.structured import (
    ParsedClaim,
    ImplicitThread,
    parse_sections,
    infer_implicit_threads,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo(tmp_path: Path) -> str:
    """Create a git repo and return its path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    dummy = repo / "README.md"
    dummy.write_text("init")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return str(repo)


# ---------------------------------------------------------------------------
# parse_sections tests
# ---------------------------------------------------------------------------

class TestParseSections:
    def test_structured_result(self) -> None:
        text = (
            "Question: Does 128-dim suffice?\n"
            "Finding: Yes, 97.5% accuracy.\n"
            "Implication: Smaller models viable.\n"
            "Details: Tested on depth-1 only."
        )
        parsed = parse_sections(text, "result")
        assert parsed.is_structured is True
        assert "Question" in parsed.sections
        assert "Finding" in parsed.sections
        assert "Implication" in parsed.sections
        assert "Details" in parsed.sections
        assert parsed.summary == "Yes, 97.5% accuracy."
        assert parsed.sections["Question"] == "Does 128-dim suffice?"

    def test_structured_hypothesis(self) -> None:
        text = (
            "Prediction: Grokking occurs at 10k steps.\n"
            "Rationale: Based on prior scaling results.\n"
            "If wrong: Try longer training."
        )
        parsed = parse_sections(text, "hypothesis")
        assert parsed.is_structured is True
        assert parsed.summary == "Grokking occurs at 10k steps."
        assert "Rationale" in parsed.sections
        assert "If wrong" in parsed.sections

    def test_structured_method(self) -> None:
        text = (
            "Approach: Fine-tune with LoRA.\n"
            "Differs from prior work: Uses rank-4 instead of rank-16.\n"
            "Limitations: Only tested on small models."
        )
        parsed = parse_sections(text, "method")
        assert parsed.is_structured is True
        assert parsed.summary == "Fine-tune with LoRA."

    def test_partial_sections(self) -> None:
        """Primary marker present but not all sections — still structured."""
        text = "Question: Is 128-dim enough?\nFinding: Yes."
        parsed = parse_sections(text, "result")
        assert parsed.is_structured is True
        assert parsed.summary == "Yes."

    def test_unstructured_result(self) -> None:
        """Result without template sections falls back to unstructured."""
        text = "97.5% accuracy at depth-1"
        parsed = parse_sections(text, "result")
        assert parsed.is_structured is False
        assert parsed.summary == "97.5% accuracy at depth-1"

    def test_unrecognized_type(self) -> None:
        """Types without section markers always parse as unstructured."""
        text = "Some replication text"
        parsed = parse_sections(text, "replication")
        assert parsed.is_structured is False
        assert parsed.summary == "Some replication text"

    def test_session_prefix_extraction(self) -> None:
        text = "[Session 42] Grokking happens at 10k steps. More details follow."
        parsed = parse_sections(text, "result")
        assert parsed.is_structured is False
        assert "[Session 42]" in parsed.title
        assert "Grokking happens at 10k steps." in parsed.title

    def test_session_prefix_short_text(self) -> None:
        text = "[Session 5] Quick note"
        parsed = parse_sections(text, "result")
        assert "[Session 5]" in parsed.title

    def test_no_session_prefix_first_sentence(self) -> None:
        text = "Loss converges at 10k steps. The model generalizes well."
        parsed = parse_sections(text, "result")
        assert parsed.is_structured is False
        assert parsed.title == "Loss converges at 10k steps."
        assert parsed.summary == "Loss converges at 10k steps."

    def test_long_text_truncated(self) -> None:
        text = "A" * 200
        parsed = parse_sections(text, "result")
        assert len(parsed.title) <= 120

    def test_empty_text(self) -> None:
        parsed = parse_sections("", "result")
        assert parsed.is_structured is False
        assert parsed.summary == ""


# ---------------------------------------------------------------------------
# infer_implicit_threads tests
# ---------------------------------------------------------------------------

class TestImplicitThreads:
    def test_linear_chain(self, tmp_path: Path) -> None:
        """A→B→C forms one implicit thread."""
        rp = _init_repo(tmp_path)
        store = LocalStore(str(tmp_path / ".resdag"))
        cid_a = workflow.execute(store, "Step A", domains=["test"], repo_path=rp)
        cid_b = workflow.execute(
            store, "Step B", hypothesis_cid=cid_a, domains=["test"], repo_path=rp,
        )
        cid_c = workflow.execute(
            store, "Step C", hypothesis_cid=cid_b, domains=["test"], repo_path=rp,
        )
        threads = infer_implicit_threads(store)
        assert len(threads) == 1
        assert threads[0].root_cid == cid_a
        assert len(threads[0].cids) == 3

    def test_branching_breaks_chain(self, tmp_path: Path) -> None:
        """A→B and A→C produces two chains of length 1 each (below min_length)."""
        rp = _init_repo(tmp_path)
        store = LocalStore(str(tmp_path / ".resdag"))
        cid_a = workflow.execute(store, "Root", domains=["test"], repo_path=rp)
        workflow.execute(
            store, "Branch 1", hypothesis_cid=cid_a, domains=["test"], repo_path=rp,
        )
        workflow.execute(
            store, "Branch 2", hypothesis_cid=cid_a, domains=["test"], repo_path=rp,
        )
        threads = infer_implicit_threads(store, min_length=2)
        # A has 2 children so no single-child chain; B and C are length 1 each
        assert len(threads) == 0

    def test_hypothesis_excluded(self, tmp_path: Path) -> None:
        """Hypothesis chains are excluded by default (they have explicit threads)."""
        rp = _init_repo(tmp_path)
        store = LocalStore(str(tmp_path / ".resdag"))
        h = workflow.hypothesize(store, "Test hypothesis", domains=["test"], repo_path=rp)
        workflow.execute(
            store, "Result", hypothesis_cid=h, domains=["test"], repo_path=rp,
        )
        threads = infer_implicit_threads(store, exclude_hypothesis_threads=True)
        assert len(threads) == 0

    def test_hypothesis_included(self, tmp_path: Path) -> None:
        """With exclude_hypothesis_threads=False, hypothesis chains are included."""
        rp = _init_repo(tmp_path)
        store = LocalStore(str(tmp_path / ".resdag"))
        h = workflow.hypothesize(store, "Test hypothesis", domains=["test"], repo_path=rp)
        workflow.execute(
            store, "Result", hypothesis_cid=h, domains=["test"], repo_path=rp,
        )
        threads = infer_implicit_threads(store, exclude_hypothesis_threads=False)
        assert len(threads) == 1

    def test_empty_store(self, tmp_path: Path) -> None:
        store = LocalStore(str(tmp_path / ".resdag"))
        assert infer_implicit_threads(store) == []

    def test_single_claim(self, tmp_path: Path) -> None:
        rp = _init_repo(tmp_path)
        store = LocalStore(str(tmp_path / ".resdag"))
        workflow.execute(store, "Alone", domains=["test"], repo_path=rp)
        threads = infer_implicit_threads(store, min_length=2)
        assert len(threads) == 0

    def test_domains_collected(self, tmp_path: Path) -> None:
        rp = _init_repo(tmp_path)
        store = LocalStore(str(tmp_path / ".resdag"))
        cid_a = workflow.execute(store, "A", domains=["alpha"], repo_path=rp)
        workflow.execute(
            store, "B", hypothesis_cid=cid_a, domains=["beta"], repo_path=rp,
        )
        threads = infer_implicit_threads(store)
        assert "alpha" in threads[0].domains
        assert "beta" in threads[0].domains


# ---------------------------------------------------------------------------
# Site renderer integration tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def git_repo(tmp_path: Path) -> str:
    return _init_repo(tmp_path)


class TestStructuredSiteRendering:
    def test_structured_claim_renders_sections(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Structured claim detail page shows section blocks."""
        store = LocalStore(str(tmp_path / ".resdag"))
        text = (
            "Question: Does 128-dim suffice?\n"
            "Finding: Yes, 97.5% accuracy.\n"
            "Implication: Smaller models viable."
        )
        cid = workflow.execute(store, text, domains=["test"], repo_path=git_repo)

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "claims" / f"{cid}.html").read_text()
        assert "section-block" in html
        assert "Question" in html
        assert "Finding" in html
        assert "Implication" in html

    def test_structured_summary_in_card_list(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Index shows Finding as primary text for structured claims."""
        store = LocalStore(str(tmp_path / ".resdag"))
        text = (
            "Question: Does X work?\n"
            "Finding: X works at 95% accuracy.\n"
            "Implication: Use X."
        )
        workflow.execute(store, text, domains=["test"], repo_path=git_repo)

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "index.html").read_text()
        # Summary (Finding) should appear as the link text
        assert "X works at 95% accuracy." in html

    def test_unstructured_session_prefix_in_card(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Unstructured claim with [Session N] prefix shows title in card."""
        store = LocalStore(str(tmp_path / ".resdag"))
        cid = workflow.execute(
            store, "[Session 42] Grokking happens at 10k steps.",
            domains=["test"], repo_path=git_repo,
        )

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "index.html").read_text()
        assert "Session 42" in html

        # Detail page should use title in header
        detail = (output / "claims" / f"{cid}.html").read_text()
        assert "Session 42" in detail

    def test_unstructured_claim_renders_body(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Unstructured claim detail page shows full text."""
        store = LocalStore(str(tmp_path / ".resdag"))
        cid = workflow.execute(
            store, "Simple result text",
            domains=["test"], repo_path=git_repo,
        )

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "claims" / f"{cid}.html").read_text()
        assert "Simple result text" in html

    def test_mixed_store_renders(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Store with both structured and unstructured claims renders all."""
        store = LocalStore(str(tmp_path / ".resdag"))
        structured = (
            "Question: Does 128-dim suffice?\n"
            "Finding: Yes.\n"
            "Implication: Good."
        )
        workflow.execute(store, structured, domains=["test"], repo_path=git_repo)
        workflow.execute(
            store, "[Session 1] Unstructured note",
            domains=["test"], repo_path=git_repo,
        )
        workflow.execute(
            store, "Plain claim text",
            domains=["test"], repo_path=git_repo,
        )

        output = tmp_path / "site"
        count = generate_site(store, output)
        assert count == 3

        html = (output / "index.html").read_text()
        # All three should appear
        assert "Yes." in html  # structured summary
        assert "Session 1" in html  # session prefix title
        assert "Plain claim text" in html  # plain fallback

    def test_implicit_threads_on_index(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Linear chain produces implicit thread section on index."""
        store = LocalStore(str(tmp_path / ".resdag"))
        cid_a = workflow.execute(store, "Step A", domains=["test"], repo_path=git_repo)
        cid_b = workflow.execute(
            store, "Step B", hypothesis_cid=cid_a,
            domains=["test"], repo_path=git_repo,
        )
        workflow.execute(
            store, "Step C", hypothesis_cid=cid_b,
            domains=["test"], repo_path=git_repo,
        )

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "index.html").read_text()
        assert "Implicit Threads" in html
        assert "3 claims" in html

    def test_no_implicit_threads_when_none(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Single claim produces no implicit threads section."""
        store = LocalStore(str(tmp_path / ".resdag"))
        workflow.execute(store, "Alone", domains=["test"], repo_path=git_repo)

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "index.html").read_text()
        assert "Implicit Threads" not in html

    def test_implicit_thread_nav_on_detail(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Claims in an implicit thread show thread navigation on detail page."""
        store = LocalStore(str(tmp_path / ".resdag"))
        cid_a = workflow.execute(store, "Step A", domains=["test"], repo_path=git_repo)
        cid_b = workflow.execute(
            store, "Step B", hypothesis_cid=cid_a,
            domains=["test"], repo_path=git_repo,
        )

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "claims" / f"{cid_b}.html").read_text()
        assert "implicit-thread-nav" in html

    def test_health_badge_on_index(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Health badge renders on index page (pre-existing feature)."""
        store = LocalStore(str(tmp_path / ".resdag"))
        workflow.hypothesize(store, "Test hypo", domains=["test"], repo_path=git_repo)

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "index.html").read_text()
        assert "health-badge" in html

    def test_structured_detail_header_uses_summary(
        self, tmp_path: Path, git_repo: str
    ) -> None:
        """Structured claim detail page uses summary (Finding) as header."""
        store = LocalStore(str(tmp_path / ".resdag"))
        text = (
            "Question: Test?\n"
            "Finding: Answer is 42.\n"
            "Implication: Universe explained."
        )
        cid = workflow.execute(store, text, domains=["test"], repo_path=git_repo)

        output = tmp_path / "site"
        generate_site(store, output)

        html = (output / "claims" / f"{cid}.html").read_text()
        # Header h1 should have the summary
        assert "<h1>Answer is 42.</h1>" in html
