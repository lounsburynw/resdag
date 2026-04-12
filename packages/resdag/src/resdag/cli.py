"""ResDAG command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from resdag.claim import Claim, ClaimType
from resdag.dag import DAG
from resdag.guide import GUIDE
from resdag.discover.equivalence import equivalence_cluster, parse_equivalence
from resdag.export.subgraph import (
    ancestor_closure,
    export_subgraph,
    select_claims,
    write_manifest,
)
from resdag.storage.local import LocalStore
from resdag.sync.gossip import push as gossip_push, sync as gossip_sync
from resdag.verify.receipt import verification_status

RESDAG_DIR = ".resdag"

_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}


def _resolve_claim_text(claim_text: str | None, claim_file: str | None) -> str:
    """Resolve claim text from argument/option or --claim-file.

    Accepts a file path or ``-`` for stdin.  Bypasses shell expansion
    issues (e.g. zsh command-substituting backticks in ``-c "..."``).
    """
    # When both are given, -f wins (needed for commands with required
    # positional args where the user must pass a placeholder).
    if claim_file:
        if claim_file == "-":
            text = sys.stdin.read().strip()
        else:
            text = Path(claim_file).read_text(encoding="utf-8").strip()
        if not text:
            raise click.UsageError("Claim file is empty.")
        return text
    if claim_text:
        return claim_text
    raise click.UsageError("Provide claim text (-c) or --claim-file/-f <path> (use - for stdin).")


def _guess_media_type(filename: str) -> str:
    """Guess media type from file extension."""
    suffix = Path(filename).suffix.lower()
    return _MEDIA_TYPES.get(suffix, "application/octet-stream")


def _get_store(ctx: click.Context) -> LocalStore:
    """Get the LocalStore for the current directory, failing if not initialized."""
    root = Path.cwd() / RESDAG_DIR
    if not root.exists():
        ctx.fail(f"Not a resdag repository (no {RESDAG_DIR}/ directory). Run `res init` first.")
    return LocalStore(root)


def _short_cid(cid: str, length: int = 12) -> str:
    """Return a shortened CID for display."""
    return cid[:length]


def _superseded_cids(store: LocalStore, children_map: dict[str, list[str]]) -> set[str]:
    """Return the set of CIDs that have been superseded by a REFUTATION child."""
    import json
    superseded = set()
    for cid in store.list_cids():
        for child_cid in children_map.get(cid, []):
            child = store.get(child_cid)
            if child.type != ClaimType.REFUTATION:
                continue
            try:
                data = json.loads(child.claim)
                if "superseded_by" in data:
                    superseded.add(cid)
            except (json.JSONDecodeError, TypeError):
                continue
    return superseded


@click.group()
def main():
    """ResDAG — commit research results like code.

    Run `res guide` for full usage guide, or see .resdag/GUIDE.md.
    """
    pass


@main.command()
def init():
    """Initialize a new resdag repository in the current directory."""
    root = Path.cwd() / RESDAG_DIR
    if root.exists():
        click.echo(f"Already initialized: {RESDAG_DIR}/")
        return
    store = LocalStore(root)
    store.init()
    (root / "GUIDE.md").write_text(GUIDE, encoding="utf-8")
    click.echo(f"Initialized empty resdag repository in {RESDAG_DIR}/")


@main.command("guide")
def guide_cmd():
    """Print the ResDAG usage guide."""
    click.echo(GUIDE)


@main.command("commit")
@click.option("--claim", "-c", "claim_text", default=None, help="The claim text.")
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin).")
@click.option(
    "--type", "-t", "claim_type",
    required=True,
    type=click.Choice([t.value for t in ClaimType], case_sensitive=False),
    help="Claim type.",
)
@click.option("--parent", "-p", "parents", multiple=True, help="Parent CID(s).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tag(s).")
@click.option("--author", "-a", default="", help="Author DID.")
@click.option("--evidence", "-e", "evidence_files", multiple=True,
              type=click.Path(exists=True), help="Evidence file(s) to attach.")
@click.option("--timestamp", "-T", default=None, help="ISO 8601 timestamp (default: now).")
@click.pass_context
def commit_cmd(ctx, claim_text, claim_file, claim_type, parents, domains, author, evidence_files, timestamp):
    """Create a new claim and add it to the DAG."""
    claim_text = _resolve_claim_text(claim_text, claim_file)
    store = _get_store(ctx)
    dag = DAG(store)

    # Store evidence files and collect CIDs
    evidence_cids = []
    for filepath in evidence_files:
        path = Path(filepath)
        data = path.read_bytes()
        media_type = _guess_media_type(path.name)
        cid = store.put_evidence(data, filename=path.name, media_type=media_type)
        evidence_cids.append(cid)
        click.echo(f"  evidence: {path.name} -> {_short_cid(cid)}")

    # Resolve parent CID prefixes
    resolved_parents = []
    for prefix in parents:
        matched = _resolve_cid(store, prefix)
        if matched is None:
            ctx.fail(f"Parent not found: {prefix}")
        if isinstance(matched, list):
            ctx.fail(f"Ambiguous parent prefix '{prefix}', matches {len(matched)} claims.")
        resolved_parents.append(matched)

    kwargs = dict(
        claim=claim_text,
        type=ClaimType(claim_type),
        parents=tuple(resolved_parents),
        evidence=tuple(evidence_cids),
        domain=tuple(domains),
        author=author,
    )
    if timestamp:
        kwargs["timestamp"] = timestamp
    claim = Claim(**kwargs)
    try:
        cid = dag.add(claim)
    except KeyError as e:
        ctx.fail(f"Parent not found: {e}")
    click.echo(f"[{_short_cid(cid)}] {claim.type.value}: {claim.claim}")


@main.command("note")
@click.argument("claim_text", required=False, default=None)
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tag(s).")
@click.option("--parent", "-p", "parents", multiple=True, help="Parent CID(s).")
@click.pass_context
def note_cmd(ctx, claim_text, claim_file, domains, parents):
    """Quick-commit a result claim with minimal ceremony."""
    claim_text = _resolve_claim_text(claim_text, claim_file)
    ctx.invoke(
        commit_cmd,
        claim_text=claim_text,
        claim_file=None,
        claim_type="result",
        parents=parents,
        domains=domains,
        author="",
        evidence_files=(),
        timestamp=None,
    )


@main.command("ingest")
@click.argument("json_file", type=click.Path(exists=True))
@click.option("--template", "-t", default=None,
              help="Python format string using JSON keys, e.g. 'Accuracy: {accuracy}%'.")
@click.option("--type", "claim_type", default="result",
              type=click.Choice([t.value for t in ClaimType], case_sensitive=False),
              help="Claim type (default: result).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tag(s).")
@click.option("--parent", "-p", "parents", multiple=True, help="Parent CID(s).")
@click.pass_context
def ingest_cmd(ctx, json_file, template, claim_type, domains, parents):
    """Auto-generate claims from a JSON file.

    The JSON file can be a single object or an array of objects.
    Each object becomes a claim with the file attached as evidence.
    """
    import json

    store = _get_store(ctx)
    dag = DAG(store)

    # Resolve parent CID prefixes
    resolved_parents = []
    for prefix in parents:
        matched = _resolve_cid(store, prefix)
        if matched is None:
            ctx.fail(f"Parent not found: {prefix}")
        if isinstance(matched, list):
            ctx.fail(f"Ambiguous parent prefix '{prefix}', matches {len(matched)} claims.")
        resolved_parents.append(matched)

    # Read and parse JSON
    path = Path(json_file)
    raw = path.read_bytes()
    data = json.loads(raw)

    # Normalize to list
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        ctx.fail("JSON file must contain an object or array of objects.")

    # Store the file as evidence
    media_type = _guess_media_type(path.name)
    evidence_cid = store.put_evidence(raw, filename=path.name, media_type=media_type)

    count = 0
    for item in items:
        if template:
            try:
                claim_text = template.format(**item)
            except KeyError as e:
                ctx.fail(f"Template key {e} not found in JSON object: {item}")
        else:
            claim_text = json.dumps(item, sort_keys=True)

        claim = Claim(
            claim=claim_text,
            type=ClaimType(claim_type),
            parents=tuple(resolved_parents),
            evidence=(evidence_cid,),
            domain=tuple(domains),
        )
        try:
            cid = dag.add(claim)
        except KeyError as e:
            ctx.fail(f"Parent not found: {e}")
        click.echo(f"[{_short_cid(cid)}] {claim.type.value}: {claim_text}")
        count += 1

    click.echo(f"Ingested {count} claim(s) from {path.name}")


@main.command("log")
@click.option("--domain", "-d", "domains", multiple=True, help="Filter by domain tag(s).")
@click.option(
    "--type", "-t", "claim_type",
    type=click.Choice([t.value for t in ClaimType], case_sensitive=False),
    default=None,
    help="Filter by claim type.",
)
@click.option("--after", default=None, help="Show claims with timestamp >= this (ISO 8601).")
@click.option("--before", default=None, help="Show claims with timestamp < this (ISO 8601).")
@click.option("--orphans", is_flag=True, help="Show claims with no parents (likely missing parent links).")
@click.option("--unverified", is_flag=True, help="Show claims with no verification receipts.")
@click.option("--active", is_flag=True, help="Hide superseded claims.")
@click.option("--sort", "sort_key", type=click.Choice(["date", "cid"]), default="date",
              help="Sort order (default: date, newest first).")
@click.pass_context
def log_cmd(ctx, domains, claim_type, after, before, orphans, unverified, active, sort_key):
    """List claims in the repository, with optional filters."""
    store = _get_store(ctx)
    cids = store.list_cids()
    if not cids:
        click.echo("No claims yet.")
        return

    # Pre-compute children map for --unverified and --active filters
    children_map = None
    if unverified or active:
        dag = DAG(store)
        children_map = dag._children_map()

    # Pre-compute superseded set for --active filter
    superseded = set()
    if active:
        superseded = _superseded_cids(store, children_map)

    # Collect matching (cid, claim) pairs, then sort
    results = []
    for cid in cids:
        claim = store.get(cid)
        if claim_type and claim.type.value != claim_type:
            continue
        if domains and not any(d in claim.domain for d in domains):
            continue
        if after and claim.timestamp < after:
            continue
        if before and claim.timestamp >= before:
            continue
        if orphans and (claim.parents or claim.type == ClaimType.HYPOTHESIS):
            continue
        if unverified:
            has_verification = any(
                store.get(c).type == ClaimType.VERIFICATION
                for c in children_map.get(cid, [])
            )
            if has_verification:
                continue
        if active and cid in superseded:
            continue
        results.append((cid, claim))

    if not results:
        click.echo("No claims match the filters.")
        return

    if sort_key == "date":
        results.sort(key=lambda r: r[1].timestamp, reverse=True)
    # sort_key == "cid" keeps the original CID-alphabetical order

    for cid, claim in results:
        click.echo(f"{_short_cid(cid)}  {claim.type.value:<12}  {claim.claim}")


@main.command("lineage")
@click.argument("cid")
@click.pass_context
def lineage_cmd(ctx, cid):
    """Show the full ancestor/descendant tree for a claim."""
    store = _get_store(ctx)

    matched = _resolve_cid(store, cid)
    if isinstance(matched, list):
        ctx.fail(f"Ambiguous prefix '{cid}', matches {len(matched)} claims. Be more specific.")
    if matched is None:
        ctx.fail(f"No claim found matching: {cid}")

    dag = DAG(store)
    children_map = dag._children_map()

    # Collect ancestors as rows: (depth, cid) — roots at depth 0.
    # Iterative to avoid Python's recursion limit on deep chains, and to
    # correctly handle diamond DAGs where a parent is reachable via multiple
    # paths (the previous recursive version raised ValueError on diamonds
    # because already-visited parents returned [], leaving max() empty).
    def _collect_ancestors(focal):
        # Phase 1: BFS the closure of focal + transitive parents, caching
        # parent lists so we hit storage at most once per node.
        parents_of: dict[str, list[str]] = {}
        work = [focal]
        while work:
            c = work.pop()
            if c in parents_of:
                continue
            parents_of[c] = list(store.get(c).parents)
            for p in parents_of[c]:
                if p not in parents_of:
                    work.append(p)

        # Phase 2: Compute depth (longest path from a root) via iterative
        # post-order DFS. The (node, ready) marker pattern processes a node
        # only after all its parents have been resolved.
        depth: dict[str, int] = {}
        for start in parents_of:
            if start in depth:
                continue
            stack: list[tuple[str, bool]] = [(start, False)]
            while stack:
                node, ready = stack.pop()
                if ready:
                    parent_depths = [depth[p] for p in parents_of[node] if p in depth]
                    depth[node] = (max(parent_depths) + 1) if parent_depths else 0
                    continue
                if node in depth:
                    continue
                stack.append((node, True))
                for p in parents_of[node]:
                    if p not in depth:
                        stack.append((p, False))

        return sorted(((depth[c], c) for c in parents_of), key=lambda r: (r[0], r[1]))

    ancestor_rows = _collect_ancestors(matched)
    focal_depth = 0
    for depth, c in ancestor_rows:
        if c == matched:
            focal_depth = depth
            continue
        claim = store.get(c)
        click.echo(f"{'  ' * depth}^ {_short_cid(c)}  {claim.type.value:<12}  {claim.claim}")

    # Print the focal claim
    focal = store.get(matched)
    click.echo(f"{'  ' * focal_depth}* {_short_cid(matched)}  {focal.type.value:<12}  {focal.claim}")

    # Walk descendants top-down
    def _print_descendants(c, depth, visited=None):
        if visited is None:
            visited = set()
        for child_cid in children_map.get(c, []):
            if child_cid in visited:
                continue
            visited.add(child_cid)
            child = store.get(child_cid)
            click.echo(f"{'  ' * depth}v {_short_cid(child_cid)}  {child.type.value:<12}  {child.claim}")
            _print_descendants(child_cid, depth + 1, visited)

    _print_descendants(matched, focal_depth + 1)


@main.command("children")
@click.argument("cid")
@click.pass_context
def children_cmd(ctx, cid):
    """List claims that have CID as a parent (direct children)."""
    store = _get_store(ctx)

    matched = _resolve_cid(store, cid)
    if isinstance(matched, list):
        ctx.fail(f"Ambiguous prefix '{cid}', matches {len(matched)} claims. Be more specific.")
    if matched is None:
        ctx.fail(f"No claim found matching: {cid}")

    dag = DAG(store)
    child_cids = dag.children(matched)
    if not child_cids:
        click.echo("No children.")
        return
    for child_cid in child_cids:
        child = store.get(child_cid)
        click.echo(f"{_short_cid(child_cid)}  {child.type.value:<12}  {child.claim}")


@main.command("supersede")
@click.argument("old_cid")
@click.argument("new_cid")
@click.option("--reason", "-r", default="", help="Reason for supersession.")
@click.pass_context
def supersede_cmd(ctx, old_cid, new_cid, reason):
    """Mark a claim as superseded by another claim."""
    store = _get_store(ctx)
    dag = DAG(store)

    # Resolve both CID prefixes
    old_matched = _resolve_cid(store, old_cid)
    if old_matched is None:
        ctx.fail(f"No claim found matching: {old_cid}")
    if isinstance(old_matched, list):
        ctx.fail(f"Ambiguous prefix '{old_cid}', matches {len(old_matched)} claims.")

    new_matched = _resolve_cid(store, new_cid)
    if new_matched is None:
        ctx.fail(f"No claim found matching: {new_cid}")
    if isinstance(new_matched, list):
        ctx.fail(f"Ambiguous prefix '{new_cid}', matches {len(new_matched)} claims.")

    import json
    payload = json.dumps({
        "superseded_by": new_matched,
        "reason": reason or "Superseded by corrected claim",
    }, sort_keys=True)

    claim = Claim(
        claim=payload,
        type=ClaimType.REFUTATION,
        parents=(old_matched,),
    )
    cid = dag.add(claim)
    old_claim = store.get(old_matched)
    new_claim = store.get(new_matched)
    click.echo(f"Superseded {_short_cid(old_matched)} -> {_short_cid(new_matched)}")
    click.echo(f"  old: {old_claim.claim}")
    click.echo(f"  new: {new_claim.claim}")
    click.echo(f"  receipt: {_short_cid(cid)}")


@main.command("show")
@click.argument("cid")
@click.pass_context
def show_cmd(ctx, cid):
    """Show details of a claim by CID (full or prefix)."""
    store = _get_store(ctx)

    # Support CID prefix matching
    matched = _resolve_cid(store, cid)
    if isinstance(matched, list):
        ctx.fail(f"Ambiguous prefix '{cid}', matches {len(matched)} claims. Be more specific.")
    if matched is None:
        ctx.fail(f"No claim found matching: {cid}")
    claim = store.get(matched)

    # Build children list
    dag = DAG(store)
    children = dag.children(matched)

    click.echo(f"CID:       {matched}")
    click.echo(f"Type:      {claim.type.value}")
    click.echo(f"Claim:     {claim.claim}")
    click.echo(f"Author:    {claim.author or '(none)'}")
    click.echo(f"Timestamp: {claim.timestamp}")
    if claim.domain:
        click.echo(f"Domain:    {', '.join(claim.domain)}")
    if claim.parents:
        click.echo("Parents:")
        for p in claim.parents:
            parent = store.get(p)
            click.echo(f"  {_short_cid(p)}  {parent.claim}")
    if children:
        click.echo("Children:")
        for c in children:
            child = store.get(c)
            click.echo(f"  {_short_cid(c)}  {child.claim}")
    if claim.evidence:
        click.echo("Evidence:")
        for e in claim.evidence:
            meta = store.get_evidence_meta(e)
            if meta:
                name = meta.get("filename", "")
                mtype = meta.get("media_type", "")
                size = meta.get("size", 0)
                click.echo(f"  {_short_cid(e)}  {name} ({mtype}, {size} bytes)")
            else:
                click.echo(f"  {e}")
    if claim.signature:
        click.echo(f"Signature: {claim.signature}")
    # Show verification status (receipts attached to this claim)
    if claim.type != ClaimType.VERIFICATION:
        receipts = verification_status(matched, dag)
        if receipts:
            click.echo("Verification:")
            for r in receipts:
                conf = f" (confidence: {r.confidence})" if r.confidence is not None else ""
                click.echo(f"  {r.result.value:<12}  {r.method}{conf}")
                if r.description:
                    click.echo(f"               {r.description}")
    # Show supersession status
    children_map = dag._children_map()
    superseded = _superseded_cids(store, children_map)
    if matched in superseded:
        import json
        for child_cid in children_map.get(matched, []):
            child = store.get(child_cid)
            if child.type == ClaimType.REFUTATION:
                try:
                    data = json.loads(child.claim)
                    if "superseded_by" in data:
                        replacement = data["superseded_by"]
                        reason = data.get("reason", "")
                        click.echo(f"SUPERSEDED by {_short_cid(replacement)}  {reason}")
                except (json.JSONDecodeError, TypeError):
                    pass
    # Show equivalence cluster
    if claim.type != ClaimType.EQUIVALENCE:
        cluster = equivalence_cluster(matched, dag)
        cluster.discard(matched)  # Don't show self
        if cluster:
            click.echo("Equivalent claims:")
            for eq_cid in sorted(cluster):
                eq_claim = store.get(eq_cid)
                click.echo(f"  {_short_cid(eq_cid)}  {eq_claim.claim}")
    else:
        # For equivalence claims themselves, show the parsed scope
        try:
            assertion = parse_equivalence(claim)
            click.echo(f"Scope:     {assertion.scope}")
            if assertion.description:
                click.echo(f"Detail:    {assertion.description}")
        except ValueError:
            pass


@main.command("export")
@click.argument("output_dir", type=click.Path())
@click.option("--cid", "-c", "cids", multiple=True, help="CID(s) to export.")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tag(s) to select.")
@click.option("--after", default=None, help="Include claims with timestamp >= this (ISO 8601).")
@click.option("--before", default=None, help="Include claims with timestamp < this (ISO 8601).")
@click.option("--include-ancestors", is_flag=True, help="Include all ancestors of selected claims.")
@click.option("--include-evidence", is_flag=True, help="Copy evidence artifacts.")
@click.option("--site", is_flag=True, help="Generate a static HTML site instead of a subgraph export.")
@click.option("--feed", is_flag=True, help="Generate an Atom feed (feed.xml in output dir).")
@click.option("--feed-title", default="ResDAG Feed", help="Feed title (used with --feed).")
@click.option("--base-url", default="", help="Base URL for feed links (used with --feed).")
@click.pass_context
def export_cmd(ctx, output_dir, cids, domains, after, before, include_ancestors, include_evidence, site, feed, feed_title, base_url):
    """Export a subgraph to a new resdag repository, or generate a static site/feed."""
    store = _get_store(ctx)

    if feed:
        from resdag.export.feed import generate_feed
        domain_filter = set(domains) if domains else None
        feed_path = Path(output_dir) / "feed.xml"
        count = generate_feed(
            store, feed_path,
            title=feed_title,
            base_url=base_url,
            domain_filter=domain_filter,
        )
        click.echo(f"Generated feed with {count} entr{'ies' if count != 1 else 'y'} at {feed_path}")
        if not site:
            return

    if site:
        from resdag.export.site import generate_site
        count = generate_site(store, output_dir)
        click.echo(f"Generated site with {count} claim page{'s' if count != 1 else ''} in {output_dir}/")
        return

    dag = DAG(store)

    # Resolve CID prefixes
    resolved_cids = set()
    for prefix in cids:
        matched = _resolve_cid(store, prefix)
        if matched is None:
            ctx.fail(f"No claim found matching: {prefix}")
        if isinstance(matched, list):
            ctx.fail(f"Ambiguous prefix '{prefix}', matches {len(matched)} claims.")
        resolved_cids.add(matched)

    # Build selection
    selected = select_claims(
        store,
        cids=resolved_cids if resolved_cids else None,
        domains=set(domains) if domains else None,
        after=after,
        before=before,
    )

    if not selected:
        ctx.fail("No claims matched the selection criteria.")

    if include_ancestors:
        selected = ancestor_closure(dag, selected)

    # Create target store and export
    target_path = Path(output_dir)
    target = LocalStore(target_path)
    target.init()

    result = export_subgraph(store, target, selected, include_evidence=include_evidence)
    write_manifest(target_path / "manifest.json", result)

    click.echo(f"Exported {len(result.exported_cids)} claims to {output_dir}/")
    if result.external_roots:
        click.echo(f"  {len(result.external_roots)} external root(s)")
    if result.evidence_cids:
        click.echo(f"  {len(result.evidence_cids)} evidence artifact(s)")


@main.command("sync")
@click.argument("peer_path", type=click.Path(exists=True))
@click.option("--push-only", is_flag=True, help="Only push local claims to peer.")
@click.option("--pull-only", is_flag=True, help="Only pull claims from peer.")
@click.option("--include-evidence", is_flag=True, help="Also sync evidence artifacts.")
@click.pass_context
def sync_cmd(ctx, peer_path, push_only, pull_only, include_evidence):
    """Sync claims with another local resdag store."""
    store = _get_store(ctx)
    peer = LocalStore(Path(peer_path))

    if not (Path(peer_path) / "objects").exists():
        ctx.fail(f"Not a resdag repository: {peer_path}")

    if push_only and pull_only:
        ctx.fail("Cannot use both --push-only and --pull-only.")

    if push_only:
        result = gossip_push(store, peer, include_evidence=include_evidence)
    elif pull_only:
        result = gossip_push(peer, store, include_evidence=include_evidence)
    else:
        result = gossip_sync(store, peer, include_evidence=include_evidence)

    if result.claims_pushed == 0 and result.evidence_pushed == 0:
        click.echo("Already in sync.")
    else:
        click.echo(
            f"Synced {result.claims_pushed} claim(s)"
            f", {result.evidence_pushed} evidence artifact(s)."
        )


def _resolve_cid(store: LocalStore, prefix: str) -> str | list[str] | None:
    """Resolve a full or prefix CID to a full CID.

    Returns the full CID string on unique match, a list on ambiguous match,
    or None if no match.
    """
    if store.has(prefix):
        return prefix
    matches = [c for c in store.list_cids() if c.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return matches
    return None
