"""Tests for reslab CLI parent linking: -p flag and CID prefix resolution.

Regression tests for two bugs that caused a flat DAG in real-world use:
  1. ``lab execute`` (and interpret/branch/replicate) silently dropped
     ``-p <parent>`` flags because the option didn't exist.
  2. None of the claim-creation commands resolved short CID prefixes, so
     ``-h bagaaiera...`` would be stored verbatim as a dangling reference.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from resdag.storage.local import LocalStore

from reslab.cli import main


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a project root with a .resdag store and an initialized git repo."""
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

    return store_path, project_root


def _extract_short_cid(output: str) -> str:
    """Extract the 12-char prefix the CLI prints on commit."""
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("hypothesis", "result", "replication", "refutation"):
            return parts[1]
    raise ValueError(f"No CID in output: {output!r}")


def _resolve_full(store: LocalStore, short: str) -> str:
    """Expand a short CID prefix to the full CID stored on disk."""
    matches = [c for c in store.list_cids() if c.startswith(short)]
    if len(matches) != 1:
        raise ValueError(f"Expected unique match for {short!r}, got {matches}")
    return matches[0]


def _extract_cid(output: str, store: LocalStore | None = None) -> str:
    """Extract the committed CID from CLI output.

    When ``store`` is provided, the short prefix is expanded to the full CID
    so callers can pass it straight to ``store.get``.
    """
    short = _extract_short_cid(output)
    if store is None:
        return short
    return _resolve_full(store, short)


def _invoke(runner: CliRunner, store_path: Path, repo: Path, *args: str):
    return runner.invoke(
        main,
        ["--root", str(store_path), *args, "--repo", str(repo)],
    )


# ---------------------------------------------------------------------------
# CID prefix resolution
# ---------------------------------------------------------------------------


def test_hypothesize_resolves_short_parent_prefix(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h1 = _invoke(runner, store_path, repo, "hypothesize", "first hypothesis")
    assert h1.exit_code == 0
    full_parent = _extract_cid(h1.output, store)
    short = full_parent[:12]

    h2 = _invoke(runner, store_path, repo, "hypothesize", "second hypothesis", "-p", short)
    assert h2.exit_code == 0, h2.output

    # The stored claim should reference the FULL cid, not the short prefix
    child = store.get(_extract_cid(h2.output, store))
    assert full_parent in child.parents
    assert short not in child.parents  # ensure no dangling short ref


def test_execute_resolves_short_hypothesis_prefix(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _invoke(runner, store_path, repo, "hypothesize", "parent hypothesis")
    full_hyp = _extract_cid(h.output, store)
    short = full_hyp[:12]

    r = _invoke(runner, store_path, repo, "execute", "result", "-h", short)
    assert r.exit_code == 0, r.output

    result = store.get(_extract_cid(r.output, store))
    assert full_hyp in result.parents


def test_interpret_resolves_short_result_prefix(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _invoke(runner, store_path, repo, "hypothesize", "hyp")
    r = _invoke(runner, store_path, repo, "execute", "res", "-h", _extract_cid(h.output))
    full_result = _extract_cid(r.output, store)
    short = full_result[:12]

    i = _invoke(runner, store_path, repo, "interpret", "confirmed", short, "--confirmed")
    assert i.exit_code == 0, i.output

    interp = store.get(_extract_cid(i.output, store))
    assert full_result in interp.parents


def test_branch_resolves_short_parent_prefix(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _invoke(runner, store_path, repo, "hypothesize", "root")
    full_parent = _extract_cid(h.output, store)
    short = full_parent[:12]

    b = _invoke(runner, store_path, repo, "branch", "new direction", short)
    assert b.exit_code == 0, b.output

    new_h = store.get(_extract_cid(b.output, store))
    assert full_parent in new_h.parents


def test_replicate_resolves_short_original_prefix(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _invoke(runner, store_path, repo, "hypothesize", "hyp")
    r = _invoke(runner, store_path, repo, "execute", "original", "-h", _extract_cid(h.output))
    full_original = _extract_cid(r.output, store)
    short = full_original[:12]

    rep = _invoke(runner, store_path, repo, "replicate", "reproduced", short)
    assert rep.exit_code == 0, rep.output

    replication = store.get(_extract_cid(rep.output, store))
    assert full_original in replication.parents


def test_unknown_cid_prefix_fails(project: tuple[Path, Path]) -> None:
    """Bogus CIDs should be rejected, not stored as dangling references."""
    store_path, repo = project
    runner = CliRunner()

    # Create at least one real claim so the store isn't empty
    _invoke(runner, store_path, repo, "hypothesize", "real")

    result = _invoke(runner, store_path, repo, "execute", "result", "-h", "bogus999")
    assert result.exit_code != 0
    assert "bogus999" in result.output


def test_ambiguous_cid_prefix_fails(project: tuple[Path, Path]) -> None:
    """If a prefix matches multiple CIDs, fail loudly rather than pick one."""
    store_path, repo = project
    runner = CliRunner()

    # Resdag CIDs all start with 'bagaaiera' → this prefix matches many
    _invoke(runner, store_path, repo, "hypothesize", "first")
    _invoke(runner, store_path, repo, "hypothesize", "second")

    result = _invoke(runner, store_path, repo, "execute", "res", "-h", "bagaaiera")
    assert result.exit_code != 0
    assert "ambiguous" in result.output.lower() or "Ambiguous" in result.output


# ---------------------------------------------------------------------------
# -p / --parent flag on commands that previously lacked it
# ---------------------------------------------------------------------------


def test_execute_accepts_extra_parents(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "primary").output, store)
    related = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "related").output, store)

    r = _invoke(
        runner, store_path, repo,
        "execute", "finding", "-h", h, "-p", related,
    )
    assert r.exit_code == 0, r.output

    result = store.get(_extract_cid(r.output, store))
    assert h in result.parents
    assert related in result.parents


def test_execute_multiple_extra_parents(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "primary").output, store)
    p1 = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "first").output, store)
    p2 = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "second").output, store)

    r = _invoke(
        runner, store_path, repo,
        "execute", "finding", "-h", h, "-p", p1, "-p", p2,
    )
    assert r.exit_code == 0, r.output

    result = store.get(_extract_cid(r.output, store))
    assert set(result.parents) == {h, p1, p2}


def test_interpret_accepts_extra_parents(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "hyp").output, store)
    r = _extract_cid(_invoke(runner, store_path, repo, "execute", "res", "-h", h).output, store)
    other = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "sibling").output, store)

    i = _invoke(
        runner, store_path, repo,
        "interpret", "confirmed", r, "--confirmed", "-p", other,
    )
    assert i.exit_code == 0, i.output

    interp = store.get(_extract_cid(i.output, store))
    assert r in interp.parents
    assert other in interp.parents


def test_branch_accepts_extra_parents(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    parent = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "root").output, store)
    sibling = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "sibling").output, store)

    b = _invoke(
        runner, store_path, repo,
        "branch", "new", parent, "-p", sibling,
    )
    assert b.exit_code == 0, b.output

    new_h = store.get(_extract_cid(b.output, store))
    assert parent in new_h.parents
    assert sibling in new_h.parents


def test_replicate_accepts_extra_parents(project: tuple[Path, Path]) -> None:
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "hyp").output, store)
    orig = _extract_cid(_invoke(runner, store_path, repo, "execute", "original", "-h", h).output, store)
    context = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "context").output, store)

    rep = _invoke(
        runner, store_path, repo,
        "replicate", "reproduced", orig, "-p", context,
    )
    assert rep.exit_code == 0, rep.output

    replication = store.get(_extract_cid(rep.output, store))
    assert orig in replication.parents
    assert context in replication.parents


def test_execute_extra_parent_with_short_cid(project: tuple[Path, Path]) -> None:
    """The new -p flag should also resolve short CID prefixes."""
    store_path, repo = project
    runner = CliRunner()
    store = LocalStore(str(store_path))

    h = _extract_cid(_invoke(runner, store_path, repo, "hypothesize", "primary").output, store)
    related_full = _extract_cid(
        _invoke(runner, store_path, repo, "hypothesize", "related").output, store,
    )
    related_short = related_full[:12]

    r = _invoke(
        runner, store_path, repo,
        "execute", "finding", "-h", h, "-p", related_short,
    )
    assert r.exit_code == 0, r.output

    result = store.get(_extract_cid(r.output, store))
    assert related_full in result.parents
    assert related_short not in result.parents  # no dangling short ref
