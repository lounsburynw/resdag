"""Tests for push functionality (delegates to resdag sync)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from resdag.storage.local import LocalStore
from resdag.sync.gossip import push as gossip_push

from reslab import workflow
from reslab.vocabulary import Vocabulary, load_vocabulary, save_vocabulary


@pytest.fixture()
def store_with_claims(tmp_path: Path) -> tuple[LocalStore, Path]:
    """Create a store with some claims and a git repo."""
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

    # Add some claims
    evidence_file = tmp_path / "data.json"
    evidence_file.write_text(json.dumps({"result": 42}))

    workflow.hypothesize(store, "Test hypothesis", domains=["test"], repo_path=str(repo))
    workflow.execute(
        store,
        "Test result",
        evidence_paths=[str(evidence_file)],
        domains=["test"],
        repo_path=str(repo),
    )

    return store, tmp_path


def test_push_creates_target(store_with_claims: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_claims
    target_path = tmp_path / "published"
    target = LocalStore(str(target_path))

    result = gossip_push(store, target, include_evidence=True)

    assert target_path.exists()
    assert result.claims_pushed == 2
    assert result.evidence_pushed >= 1


def test_push_incremental(store_with_claims: tuple[LocalStore, Path]) -> None:
    store, tmp_path = store_with_claims
    target_path = tmp_path / "published"
    target = LocalStore(str(target_path))

    # First push
    r1 = gossip_push(store, target)
    assert r1.claims_pushed == 2

    # Second push — nothing new
    r2 = gossip_push(store, target)
    assert r2.claims_pushed == 0

    # Add a claim, push again
    repo = tmp_path / "repo"
    workflow.hypothesize(store, "Another hypothesis", domains=["test"], repo_path=str(repo))
    r3 = gossip_push(store, target)
    assert r3.claims_pushed == 1


def test_push_copies_vocabulary(store_with_claims: tuple[LocalStore, Path]) -> None:
    """Push should copy vocabulary.json to target so rendered site uses canonical tags."""
    from click.testing import CliRunner
    from reslab.cli import main

    store, tmp_path = store_with_claims
    target_path = tmp_path / "published"

    # Save a vocabulary to source store
    vocab = Vocabulary(
        tags={"testing": "Test domain"},
        aliases={"test": ["testing"]},
    )
    save_vocabulary(vocab, store.root)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--root", str(store.root), "push", str(target_path), "--no-site"],
    )
    assert result.exit_code == 0

    # Vocabulary should exist at target
    target_vocab = load_vocabulary(target_path)
    assert target_vocab is not None
    assert "testing" in target_vocab.tags
