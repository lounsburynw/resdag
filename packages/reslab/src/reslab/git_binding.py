"""Capture git state and bind it to resdag claims."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class GitSnapshot:
    """Immutable snapshot of git state at claim time."""

    ref: str  # HEAD commit hash
    branch: str  # Current branch name (or "HEAD" if detached)
    dirty: bool  # True if worktree has uncommitted changes
    remote_url: str  # Origin remote URL (empty if none)

    def to_dict(self) -> dict:
        return {
            "git_ref": self.ref,
            "git_branch": self.branch,
            "git_dirty": self.dirty,
            "git_remote_url": self.remote_url,
        }


def capture(repo_path: str = ".") -> GitSnapshot:
    """Capture current git state from a repository."""

    def _run(args: list[str]) -> str:
        result = subprocess.run(
            ["git", "-C", repo_path] + args,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    ref = _run(["rev-parse", "HEAD"])
    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    dirty = _run(["status", "--porcelain"]) != ""

    remote_url = _run(["remote", "get-url", "origin"])
    # remote get-url fails if no origin; that's fine
    if not remote_url or "fatal" in remote_url:
        remote_url = ""

    return GitSnapshot(ref=ref, branch=branch, dirty=dirty, remote_url=remote_url)
