"""Core workflow primitives for scientific research.

Five primitives that compose resdag claims with git state:
  hypothesize — declare what you expect and what you'd do if wrong
  execute     — run an experiment, capture evidence
  interpret   — decide what a result means (confirm or refute)
  branch      — fork research direction based on interpretation
  replicate   — reproduce a result from its recorded state
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from reslab.git_binding import GitSnapshot, capture


def _make_claim(
    claim_text: str,
    claim_type: ClaimType,
    parents: Sequence[str] = (),
    evidence: Sequence[str] = (),
    domains: Sequence[str] = (),
    git: GitSnapshot | None = None,
    command: str = "",
    extra_trailers: Sequence[str] = (),
) -> Claim:
    """Build a Claim with git metadata baked into the claim text as a trailer."""
    # Attach git + command context as structured trailer
    trailers: list[str] = []
    if command:
        trailers.append(f"command: {command}")
    if git:
        trailers.append(f"git_ref: {git.ref[:12]}")
        if git.dirty:
            trailers.append("git_dirty: true")
    trailers.extend(extra_trailers)

    full_text = claim_text
    if trailers:
        full_text = claim_text + " [" + ", ".join(trailers) + "]"

    return Claim(
        claim=full_text,
        type=claim_type,
        parents=tuple(parents),
        evidence=tuple(evidence),
        domain=tuple(domains),
    )


def hypothesize(
    store: LocalStore,
    claim: str,
    *,
    domains: Sequence[str] = (),
    parents: Sequence[str] = (),
    repo_path: str = ".",
) -> str:
    """Declare a hypothesis. Returns CID."""
    git = capture(repo_path)
    obj = _make_claim(claim, ClaimType.HYPOTHESIS, parents=parents, domains=domains, git=git)
    return store.put(obj)


def execute(
    store: LocalStore,
    claim: str,
    *,
    evidence_paths: Sequence[str | Path] = (),
    hypothesis_cid: str = "",
    domains: Sequence[str] = (),
    command: str = "",
    repo_path: str = ".",
    extra_trailers: Sequence[str] = (),
) -> str:
    """Record an experiment result with evidence. Returns CID."""
    git = capture(repo_path)

    evidence_cids: list[str] = []
    for path in evidence_paths:
        p = Path(path)
        data = p.read_bytes()
        cid = store.put_evidence(data, filename=p.name)
        evidence_cids.append(cid)

    parents = [hypothesis_cid] if hypothesis_cid else []

    obj = _make_claim(
        claim,
        ClaimType.RESULT,
        parents=parents,
        evidence=evidence_cids,
        domains=domains,
        git=git,
        command=command,
        extra_trailers=extra_trailers,
    )
    return store.put(obj)


def interpret(
    store: LocalStore,
    claim: str,
    *,
    result_cid: str,
    confirmed: bool,
    domains: Sequence[str] = (),
    repo_path: str = ".",
) -> str:
    """Interpret a result as confirmation or refutation. Returns CID."""
    git = capture(repo_path)
    claim_type = ClaimType.REPLICATION if confirmed else ClaimType.REFUTATION
    obj = _make_claim(claim, claim_type, parents=[result_cid], domains=domains, git=git)
    return store.put(obj)


def branch(
    store: LocalStore,
    claim: str,
    *,
    parent_cid: str,
    domains: Sequence[str] = (),
    repo_path: str = ".",
) -> str:
    """Fork research direction — new hypothesis branching from an interpretation. Returns CID."""
    git = capture(repo_path)
    obj = _make_claim(claim, ClaimType.HYPOTHESIS, parents=[parent_cid], domains=domains, git=git)
    return store.put(obj)


def replicate(
    store: LocalStore,
    claim: str,
    *,
    original_cid: str,
    evidence_paths: Sequence[str | Path] = (),
    domains: Sequence[str] = (),
    command: str = "",
    repo_path: str = ".",
) -> str:
    """Record a replication attempt of a prior result. Returns CID."""
    git = capture(repo_path)

    evidence_cids: list[str] = []
    for path in evidence_paths:
        p = Path(path)
        data = p.read_bytes()
        cid = store.put_evidence(data, filename=p.name)
        evidence_cids.append(cid)

    obj = _make_claim(
        claim,
        ClaimType.REPLICATION,
        parents=[original_cid],
        evidence=evidence_cids,
        domains=domains,
        git=git,
        command=command,
    )
    return store.put(obj)
