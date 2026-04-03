"""Subgraph extraction and export."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from resdag.claim import Claim
from resdag.dag import ClaimStore, DAG


@dataclass
class ExportResult:
    """Result of a subgraph export operation."""

    exported_cids: set[str] = field(default_factory=set)
    external_roots: set[str] = field(default_factory=set)
    evidence_cids: set[str] = field(default_factory=set)


def select_claims(
    store: ClaimStore,
    *,
    cids: set[str] | None = None,
    domains: set[str] | None = None,
    after: str | None = None,
    before: str | None = None,
) -> set[str]:
    """Select claims from a store by criteria (intersection when multiple given).

    Args:
        cids: Only include these CIDs (must exist in store).
        domains: Include claims whose domain tags overlap with this set.
        after: Include claims with timestamp >= this ISO 8601 string.
        before: Include claims with timestamp < this ISO 8601 string.

    Returns an empty set if no criteria are provided.
    """
    if cids is None and domains is None and after is None and before is None:
        return set()

    all_cids = set(store.list_cids())
    selected = all_cids

    if cids is not None:
        selected = selected & cids

    if domains is not None:
        selected = {
            c for c in selected if set(store.get(c).domain) & domains
        }

    if after is not None:
        selected = {c for c in selected if store.get(c).timestamp >= after}

    if before is not None:
        selected = {c for c in selected if store.get(c).timestamp < before}

    return selected


def ancestor_closure(dag: DAG, cids: set[str]) -> set[str]:
    """Expand a CID set to include all transitive ancestors.

    Returns the union of the input CIDs and all their ancestors.
    """
    result = set(cids)
    for cid in cids:
        result |= dag.ancestors(cid)
    return result


def export_subgraph(
    source: ClaimStore,
    target: ClaimStore,
    cids: set[str],
    *,
    include_evidence: bool = False,
) -> ExportResult:
    """Export selected claims from source to target store.

    Claims are copied as-is (preserving CIDs). Parent references pointing
    outside the selected set are recorded as external roots.

    Evidence is only copied when include_evidence is True and the source
    store supports evidence operations.
    """
    external_roots: set[str] = set()
    evidence_exported: set[str] = set()

    for cid in sorted(cids):
        claim = source.get(cid)
        target.put(claim)

        for parent in claim.parents:
            if parent not in cids:
                external_roots.add(parent)

        if include_evidence and hasattr(source, "has_evidence") and hasattr(target, "put_evidence"):
            for ev_cid in claim.evidence:
                if ev_cid in evidence_exported:
                    continue
                if source.has_evidence(ev_cid):
                    data = source.get_evidence(ev_cid)
                    meta = (
                        source.get_evidence_meta(ev_cid)
                        if hasattr(source, "get_evidence_meta")
                        else {}
                    )
                    target.put_evidence(
                        data,
                        filename=meta.get("filename", ""),
                        media_type=meta.get("media_type", ""),
                    )
                    evidence_exported.add(ev_cid)

    return ExportResult(
        exported_cids=set(cids),
        external_roots=external_roots,
        evidence_cids=evidence_exported,
    )


def write_manifest(path: Path, result: ExportResult) -> None:
    """Write an export manifest to a directory."""
    manifest = {
        "exported_cids": sorted(result.exported_cids),
        "external_roots": sorted(result.external_roots),
        "evidence_cids": sorted(result.evidence_cids),
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def read_manifest(path: Path) -> ExportResult:
    """Read an export manifest from a file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExportResult(
        exported_cids=set(data["exported_cids"]),
        external_roots=set(data["external_roots"]),
        evidence_cids=set(data.get("evidence_cids", [])),
    )
