"""Tests for workflow primitives."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from resdag.storage.local import LocalStore

from reslab import workflow


@pytest.fixture()
def store_and_repo(tmp_path: Path) -> tuple[LocalStore, Path]:
    """Create a resdag store and a git repo in tmp_path."""
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
    # Need at least one commit for HEAD to exist
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


def test_hypothesize(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo
    cid = workflow.hypothesize(
        store,
        "L1 specialist groks at 128-dim",
        domains=["grokking"],
        repo_path=str(repo),
    )
    assert cid
    claim = store.get(cid)
    assert claim.type.value == "hypothesis"
    assert "L1 specialist groks at 128-dim" in claim.claim
    assert "grokking" in claim.domain
    # Git ref trailer should be present
    assert "git_ref:" in claim.claim


def test_execute_with_evidence(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    # Create evidence file
    evidence = repo / "results.json"
    evidence.write_text(json.dumps({"accuracy": 0.95}))

    cid = workflow.execute(
        store,
        "Accuracy reached 95%",
        evidence_paths=[str(evidence)],
        domains=["training"],
        command="python train.py --dim 128",
        repo_path=str(repo),
    )
    claim = store.get(cid)
    assert claim.type.value == "result"
    assert len(claim.evidence) == 1
    assert "command: python train.py --dim 128" in claim.claim


def test_interpret_confirmed(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    result_cid = workflow.execute(
        store, "Got 95% accuracy", domains=["training"], repo_path=str(repo)
    )
    cid = workflow.interpret(
        store,
        "Hypothesis confirmed at 128-dim",
        result_cid=result_cid,
        confirmed=True,
        repo_path=str(repo),
    )
    claim = store.get(cid)
    assert claim.type.value == "replication"
    assert result_cid in claim.parents


def test_interpret_refuted(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    result_cid = workflow.execute(
        store, "Got 30% accuracy", domains=["training"], repo_path=str(repo)
    )
    cid = workflow.interpret(
        store,
        "64-dim insufficient for depth-2",
        result_cid=result_cid,
        confirmed=False,
        repo_path=str(repo),
    )
    claim = store.get(cid)
    assert claim.type.value == "refutation"
    assert result_cid in claim.parents


def test_branch(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    h_cid = workflow.hypothesize(store, "Original hypothesis", repo_path=str(repo))
    r_cid = workflow.execute(store, "Result", repo_path=str(repo))
    i_cid = workflow.interpret(
        store, "Refuted", result_cid=r_cid, confirmed=False, repo_path=str(repo)
    )
    b_cid = workflow.branch(
        store,
        "Try 256-dim instead",
        parent_cid=i_cid,
        domains=["capacity"],
        repo_path=str(repo),
    )
    claim = store.get(b_cid)
    assert claim.type.value == "hypothesis"
    assert i_cid in claim.parents


def test_replicate(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    original_cid = workflow.execute(
        store, "Original result", domains=["grokking"], repo_path=str(repo)
    )

    evidence = repo / "replication.json"
    evidence.write_text(json.dumps({"accuracy": 0.94}))

    cid = workflow.replicate(
        store,
        "Reproduced within 1%",
        original_cid=original_cid,
        evidence_paths=[str(evidence)],
        command="python train.py --seed 42",
        repo_path=str(repo),
    )
    claim = store.get(cid)
    assert claim.type.value == "replication"
    assert original_cid in claim.parents
    assert len(claim.evidence) == 1


def test_full_workflow_chain(store_and_repo: tuple[LocalStore, Path]) -> None:
    """Test the full hypothesize -> execute -> interpret -> branch cycle."""
    store, repo = store_and_repo

    h1 = workflow.hypothesize(
        store, "128-dim sufficient for depth-1", domains=["capacity"], repo_path=str(repo)
    )
    r1 = workflow.execute(
        store,
        "97.5% at depth-1",
        hypothesis_cid=h1,
        domains=["capacity"],
        repo_path=str(repo),
    )
    i1 = workflow.interpret(
        store, "Confirmed", result_cid=r1, confirmed=True, domains=["capacity"], repo_path=str(repo)
    )
    h2 = workflow.branch(
        store,
        "Test 128-dim on depth-2",
        parent_cid=i1,
        domains=["capacity"],
        repo_path=str(repo),
    )

    # Verify the chain
    assert h1 in store.get(r1).parents
    assert r1 in store.get(i1).parents
    assert i1 in store.get(h2).parents


# ---------------------------------------------------------------------------
# extra_parents support (secondary parent links)
# ---------------------------------------------------------------------------


def test_execute_with_extra_parents(store_and_repo: tuple[LocalStore, Path]) -> None:
    """execute should combine hypothesis_cid and extra_parents into parents."""
    store, repo = store_and_repo

    h = workflow.hypothesize(store, "primary hypothesis", repo_path=str(repo))
    related = workflow.hypothesize(store, "related context", repo_path=str(repo))

    result = workflow.execute(
        store,
        "finding",
        hypothesis_cid=h,
        extra_parents=[related],
        repo_path=str(repo),
    )

    claim = store.get(result)
    assert h in claim.parents
    assert related in claim.parents
    assert len(claim.parents) == 2


def test_execute_extra_parents_without_hypothesis(
    store_and_repo: tuple[LocalStore, Path],
) -> None:
    """execute should support parents even without a hypothesis (orphan-fix case)."""
    store, repo = store_and_repo

    parent = workflow.hypothesize(store, "orphan's new home", repo_path=str(repo))

    result = workflow.execute(
        store,
        "rehomed finding",
        extra_parents=[parent],
        repo_path=str(repo),
    )

    claim = store.get(result)
    assert claim.parents == (parent,)


def test_interpret_with_extra_parents(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    h = workflow.hypothesize(store, "hyp", repo_path=str(repo))
    r = workflow.execute(store, "res", hypothesis_cid=h, repo_path=str(repo))
    other = workflow.hypothesize(store, "related", repo_path=str(repo))

    i = workflow.interpret(
        store,
        "confirmed + related",
        result_cid=r,
        confirmed=True,
        extra_parents=[other],
        repo_path=str(repo),
    )

    claim = store.get(i)
    assert r in claim.parents
    assert other in claim.parents


def test_branch_with_extra_parents(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    p = workflow.hypothesize(store, "root", repo_path=str(repo))
    sibling = workflow.hypothesize(store, "sibling context", repo_path=str(repo))

    h = workflow.branch(
        store,
        "new direction",
        parent_cid=p,
        extra_parents=[sibling],
        repo_path=str(repo),
    )

    claim = store.get(h)
    assert p in claim.parents
    assert sibling in claim.parents


def test_execute_dedupes_parents(store_and_repo: tuple[LocalStore, Path]) -> None:
    """If hypothesis_cid == an extra_parent, parents should not contain duplicates."""
    store, repo = store_and_repo

    h = workflow.hypothesize(store, "shared", repo_path=str(repo))

    result = workflow.execute(
        store,
        "finding",
        hypothesis_cid=h,
        extra_parents=[h, h],  # duplicate with hypothesis
        repo_path=str(repo),
    )

    claim = store.get(result)
    assert claim.parents == (h,)


def test_replicate_with_extra_parents(store_and_repo: tuple[LocalStore, Path]) -> None:
    store, repo = store_and_repo

    original = workflow.execute(store, "original finding", repo_path=str(repo))
    context = workflow.hypothesize(store, "replication context", repo_path=str(repo))

    rep = workflow.replicate(
        store,
        "reproduced",
        original_cid=original,
        extra_parents=[context],
        repo_path=str(repo),
    )

    claim = store.get(rep)
    assert original in claim.parents
    assert context in claim.parents
