"""Structured claim text parsing and render-time heuristics.

Provides three capabilities for the site renderer:

1. **Section parsing** — Extract template sections (Question/Finding/Implication/
   Details for results, Prediction/Rationale/If wrong for hypotheses, Approach/
   Differs/Limitations for methods) from structured claim text.

2. **Title extraction** — Heuristic title for unstructured claims: ``[Session N]``
   prefix or first sentence.

3. **Implicit thread inference** — Walk linear chains (single-parent/single-child
   sequences) and group by domain overlap, producing thread-like navigation for
   stores that lack explicit hypothesis nodes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from resdag.claim import ClaimType
from resdag.dag import ClaimStore


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

# Ordered section markers per claim type (same as validation.py)
_SECTION_MARKERS: dict[str, list[str]] = {
    "result": ["Question:", "Finding:", "Implication:", "Details:"],
    "hypothesis": ["Prediction:", "Rationale:", "If wrong:"],
    "method": ["Approach:", "Differs from prior work:", "Limitations:"],
}


@dataclass
class ParsedClaim:
    """Result of parsing a claim's text."""

    is_structured: bool = False
    sections: dict[str, str] = field(default_factory=dict)
    # For unstructured claims:
    title: str = ""
    body: str = ""
    # For card list: primary display text
    summary: str = ""


def parse_sections(claim_text: str, claim_type: str) -> ParsedClaim:
    """Parse template sections from claim text.

    Returns a ParsedClaim with is_structured=True if at least the primary
    section marker is found (Finding: for results, Prediction: for hypotheses,
    Approach: for methods).
    """
    markers = _SECTION_MARKERS.get(claim_type, [])
    if not markers:
        return _parse_unstructured(claim_text)

    # Check if the primary marker is present
    primary = markers[0]
    if primary not in claim_text:
        return _parse_unstructured(claim_text)

    # Extract sections: each marker starts a section that runs until the next
    # marker or end-of-text
    sections: dict[str, str] = {}
    positions: list[tuple[int, str]] = []
    for marker in markers:
        idx = claim_text.find(marker)
        if idx >= 0:
            positions.append((idx, marker))

    # Sort by position in text
    positions.sort(key=lambda x: x[0])

    for i, (pos, marker) in enumerate(positions):
        start = pos + len(marker)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(claim_text)
        section_key = marker.rstrip(":")
        sections[section_key] = claim_text[start:end].strip()

    # Primary summary for card list
    summary_key = {
        "result": "Finding",
        "hypothesis": "Prediction",
        "method": "Approach",
    }.get(claim_type, "")

    summary = sections.get(summary_key, "")

    return ParsedClaim(
        is_structured=True,
        sections=sections,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Title extraction for unstructured claims
# ---------------------------------------------------------------------------

_SESSION_RE = re.compile(r"^\[Session\s+\d+\]\s*")


def _parse_unstructured(claim_text: str) -> ParsedClaim:
    """Extract a title and body from unstructured claim text."""
    text = claim_text.strip()
    title = ""
    body = text

    # Try [Session N] prefix
    m = _SESSION_RE.match(text)
    if m:
        title = m.group(0).strip()
        remainder = text[m.end():].strip()
        # Use remainder's first sentence as extended title
        first_sent = _first_sentence(remainder)
        if first_sent:
            title = f"{title} {first_sent}"
        body = remainder
    else:
        # Use first sentence as title
        title = _first_sentence(text)
        body = text

    # Summary = first sentence (for card list)
    summary = _first_sentence(body) if body else title

    return ParsedClaim(
        is_structured=False,
        title=title,
        body=body,
        summary=summary,
    )


def _first_sentence(text: str) -> str:
    """Extract the first sentence (up to period, newline, or 120 chars)."""
    if not text:
        return ""
    # Split on sentence-ending punctuation followed by space/newline, or on newline
    m = re.match(r"^(.+?[.!?])(?:\s|$)", text)
    if m and len(m.group(1)) <= 120:
        return m.group(1)
    # Fall back to first line
    first_line = text.split("\n", 1)[0].strip()
    if len(first_line) <= 120:
        return first_line
    return first_line[:117] + "..."


# ---------------------------------------------------------------------------
# Implicit thread inference
# ---------------------------------------------------------------------------

@dataclass
class ImplicitThread:
    """A linear chain of claims inferred from DAG structure."""

    root_cid: str
    root_text: str
    cids: list[str]  # ordered chain (root first)
    domains: list[str]
    first_date: str
    last_date: str


def infer_implicit_threads(
    store: ClaimStore,
    *,
    min_length: int = 2,
    exclude_hypothesis_threads: bool = True,
) -> list[ImplicitThread]:
    """Infer threads from linear chains in the DAG.

    A linear chain is a maximal sequence of claims where each has exactly
    one parent and that parent has exactly one child (within the chain).
    Chains starting from hypothesis claims are excluded by default since
    they already have explicit threads via ``discover_threads()``.

    Parameters
    ----------
    store : ClaimStore
        The claim store to analyze.
    min_length : int
        Minimum chain length to report (default 2).
    exclude_hypothesis_threads : bool
        Skip chains rooted at hypothesis claims (default True).
    """
    cids = store.list_cids()
    if not cids:
        return []

    # Build parent → children and child → parents maps
    children_map: dict[str, list[str]] = {}
    parents_map: dict[str, list[str]] = {}
    for cid in cids:
        claim = store.get(cid)
        parents_map[cid] = list(claim.parents)
        for pcid in claim.parents:
            children_map.setdefault(pcid, []).append(cid)

    # Find chain roots: claims that are NOT the single-child of their parent
    # (either no parents, or their parent has multiple children)
    visited: set[str] = set()
    threads: list[ImplicitThread] = []

    for cid in cids:
        if cid in visited:
            continue
        claim = store.get(cid)

        # Skip if this claim's parent has only one child — not a root
        parent_list = parents_map.get(cid, [])
        is_chain_root = False
        if not parent_list:
            is_chain_root = True
        else:
            # Check if any parent has multiple children (making this a branch point)
            for pcid in parent_list:
                if pcid in children_map and len(children_map[pcid]) != 1:
                    is_chain_root = True
                    break
            # Also a root if parent has one child but parent isn't in the store
            if not is_chain_root:
                for pcid in parent_list:
                    if pcid not in set(cids):
                        is_chain_root = True
                        break
            # If all parents have exactly one child, this is mid-chain
            if not is_chain_root:
                continue

        if exclude_hypothesis_threads and claim.type is ClaimType.HYPOTHESIS:
            visited.add(cid)
            continue

        # Walk the chain forward: follow single-child links
        chain = [cid]
        visited.add(cid)
        current = cid
        while True:
            kids = children_map.get(current, [])
            if len(kids) != 1:
                break
            child = kids[0]
            child_parents = parents_map.get(child, [])
            if len(child_parents) != 1:
                break
            if child in visited:
                break
            # Skip hypothesis children (they start their own explicit threads)
            child_claim = store.get(child)
            if exclude_hypothesis_threads and child_claim.type is ClaimType.HYPOTHESIS:
                break
            chain.append(child)
            visited.add(child)
            current = child

        if len(chain) < min_length:
            continue

        # Collect metadata
        all_domains: set[str] = set()
        timestamps: list[str] = []
        for c in chain:
            cl = store.get(c)
            all_domains.update(cl.domain)
            if cl.timestamp:
                timestamps.append(cl.timestamp)
        timestamps.sort()

        root_claim = store.get(chain[0])
        threads.append(ImplicitThread(
            root_cid=chain[0],
            root_text=root_claim.claim,
            cids=chain,
            domains=sorted(all_domains),
            first_date=timestamps[0] if timestamps else "",
            last_date=timestamps[-1] if timestamps else "",
        ))

    # Sort by last activity (most recent first)
    threads.sort(key=lambda t: t.last_date, reverse=True)
    return threads
