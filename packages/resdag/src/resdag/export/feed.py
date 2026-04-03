"""Atom feed generation.

Generates an Atom (RFC 4287) feed from claims in a local DAG.
Each claim becomes a feed entry with type badge, domain categories,
and optional links to a static site. No external dependencies — uses
stdlib xml.etree.ElementTree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent

from resdag.dag import ClaimStore


def generate_feed(
    store: ClaimStore,
    output_path: str | Path,
    *,
    title: str = "ResDAG Feed",
    base_url: str = "",
    domain_filter: set[str] | None = None,
) -> int:
    """Generate an Atom feed from claims in the store.

    Args:
        store: A ClaimStore to read claims from.
        output_path: Path to write the feed XML file.
        title: Feed title.
        base_url: Optional base URL for linking to a static site.
        domain_filter: If set, only include claims with at least one matching domain tag.

    Returns the number of entries written.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Collect and filter claims
    all_cids = store.list_cids()
    claims = [(cid, store.get(cid)) for cid in all_cids]

    if domain_filter:
        claims = [
            (cid, claim) for cid, claim in claims
            if domain_filter & set(claim.domain)
        ]

    # Sort by timestamp descending (newest first)
    claims.sort(key=lambda x: x[1].timestamp, reverse=True)

    # Build Atom feed
    feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")

    SubElement(feed, "title").text = title
    SubElement(feed, "id").text = f"urn:resdag:{title.lower().replace(' ', '-')}"

    if claims:
        SubElement(feed, "updated").text = claims[0][1].timestamp
    else:
        SubElement(feed, "updated").text = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    if base_url:
        SubElement(feed, "link", href=base_url, rel="alternate")
        SubElement(feed, "link", href=f"{base_url}/feed.xml", rel="self")

    for cid, claim in claims:
        entry = SubElement(feed, "entry")
        SubElement(entry, "title").text = f"[{claim.type.value}] {claim.claim}"
        SubElement(entry, "id").text = f"urn:resdag:{cid}"
        SubElement(entry, "updated").text = claim.timestamp

        if base_url:
            SubElement(
                entry, "link",
                href=f"{base_url}/claims/{cid}.html",
                rel="alternate",
            )

        if claim.author:
            author_el = SubElement(entry, "author")
            SubElement(author_el, "name").text = claim.author

        for tag in claim.domain:
            SubElement(entry, "category", term=tag)

    indent(feed)
    tree = ElementTree(feed)
    tree.write(str(output), xml_declaration=True, encoding="unicode")

    return len(claims)
