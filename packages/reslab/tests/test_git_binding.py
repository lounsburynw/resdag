"""Tests for git binding."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reslab.git_binding import capture


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
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
    return repo


def test_capture_clean(git_repo: Path) -> None:
    snap = capture(str(git_repo))
    assert len(snap.ref) == 40  # full SHA
    assert snap.branch == "main" or snap.branch == "master"
    assert snap.dirty is False
    assert snap.remote_url == ""


def test_capture_dirty(git_repo: Path) -> None:
    (git_repo / "new_file.txt").write_text("change")
    snap = capture(str(git_repo))
    assert snap.dirty is True


def test_to_dict(git_repo: Path) -> None:
    snap = capture(str(git_repo))
    d = snap.to_dict()
    assert "git_ref" in d
    assert "git_branch" in d
    assert "git_dirty" in d
    assert "git_remote_url" in d
