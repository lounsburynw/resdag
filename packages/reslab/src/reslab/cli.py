"""CLI entry point for reslab."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

import click

from resdag.claim import Claim, ClaimType
from resdag.storage.local import LocalStore

from resdag.sync.gossip import push as gossip_push

from reslab import workflow
from reslab.site.renderer import generate_site
from reslab.vocabulary import load_vocabulary, save_vocabulary, default_vocabulary
from reslab.profiles import (
    ProfileMode,
    dag_health_summary,
    init_profile,
    load_profile,
    save_profile,
)
from reslab.audit import audit_dag
from reslab.threads import discover_threads, thread_to_dict
from reslab.suggest import suggest_parents, format_suggestions
from reslab.validation import validate_commit
from reslab.scoring import score_hypothesis, score_hypothesis_text
from reslab.contradictions import (
    find_all_contradictions,
    find_contradictions_for,
    format_contradictions,
)
from reslab.costs import (
    estimate_cost,
    audit_costs,
    format_cost_trailer,
)


def _resolve_cid(store: LocalStore, prefix: str) -> str:
    """Resolve a full or prefix CID to a full CID.

    Raises click.UsageError on no match or ambiguous match.
    """
    if store.has(prefix):
        return prefix
    matches = [c for c in store.list_cids() if c.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise click.UsageError(
            f"Ambiguous CID prefix '{prefix}' — matches {len(matches)} claims."
        )
    raise click.UsageError(f"CID not found: {prefix}")


def _resolve_cids(store: LocalStore, prefixes: Sequence[str]) -> tuple[str, ...]:
    """Resolve a sequence of CID prefixes, raising on any failure."""
    return tuple(_resolve_cid(store, p) for p in prefixes)


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
    raise click.UsageError("Provide claim text or use --claim-file/-f <path> (use - for stdin).")


def _get_store(ctx: click.Context) -> LocalStore:
    root = ctx.obj.get("root", ".resdag")
    return LocalStore(root)


def _run_validation(
    store: LocalStore,
    claim_type: ClaimType,
    claim_text: str,
    domains: tuple,
    hypothesis_cid: str,
    no_validate: bool,
) -> bool:
    """Run commit-time validation. Returns True if commit should proceed."""
    profile = load_profile(store.root)
    if profile is None:
        return True  # No profile → no validation (backward compatible)

    vocab = load_vocabulary(store.root)
    result = validate_commit(
        claim_type=claim_type,
        claim_text=claim_text,
        domains=domains,
        hypothesis_cid=hypothesis_cid,
        profile=profile,
        vocabulary=vocab,
    )

    for issue in result.issues:
        prefix = "Error" if issue.level == "require" else "Warning"
        click.echo(f"{prefix}: {issue.message}", err=True)
        click.echo(f"  → {issue.suggestion}", err=True)

    if result.has_errors and not no_validate:
        click.echo("Commit blocked by validation. Use --no-validate to override.", err=True)
        return False

    return True


def _normalize_domains(store: LocalStore, domains: tuple) -> tuple:
    """Normalize domains through vocabulary if one exists. Returns tuple of tags."""
    vocab = load_vocabulary(store.root)
    if vocab is None:
        return domains
    normalized, warnings = vocab.normalize(domains)
    for tag, suggestions in warnings:
        msg = f"Unknown domain tag '{tag}'"
        if suggestions:
            msg += f" — did you mean: {', '.join(suggestions)}?"
        click.echo(f"Warning: {msg}", err=True)
    return tuple(normalized)


@click.group()
@click.option("--root", default=".resdag", help="Path to .resdag store.")
@click.pass_context
def main(ctx: click.Context, root: str) -> None:
    """reslab — scientific workflow platform."""
    ctx.ensure_object(dict)
    ctx.obj["root"] = root


@main.command("init")
@click.option(
    "--mode", "-m",
    type=click.Choice(["exploratory", "disciplined", "strict"]),
    required=True,
    help="Project mode.",
)
@click.option("--project", default="", help="Project name.")
@click.option("--audience", default="", help="Who should understand claims.")
@click.pass_context
def init_cmd(ctx: click.Context, mode: str, project: str, audience: str) -> None:
    """Initialize a reslab project profile."""
    store_root = ctx.obj.get("root", ".resdag")
    project_root = "."

    # Ensure .resdag store exists
    store = LocalStore(store_root)

    profile_mode = ProfileMode(mode)
    profile = init_profile(
        store_path=store_root,
        project_root=project_root,
        mode=profile_mode,
        project=project,
        audience=audience,
    )

    click.echo(f"Initialized {mode} profile → {store_root}/profile.json")

    # Report DAG health if existing store has claims
    cids = store.list_cids()
    if cids:
        health = dag_health_summary(store)
        click.echo(f"\nExisting DAG: {health['total_claims']} claims, "
                    f"{health['hypothesis_count']} hypotheses, "
                    f"{health['orphan_count']} orphans "
                    f"({int(health['orphan_rate'] * 100)}% orphan rate), "
                    f"{int(health['structure_coverage'] * 100)}% structured")
        if profile_mode in (ProfileMode.DISCIPLINED, ProfileMode.STRICT):
            click.echo("Tip: use /retrofit to restructure existing claims.")


@main.group("config")
@click.pass_context
def config_group(ctx: click.Context) -> None:
    """View or update project configuration."""
    pass


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration value (e.g., `lab config set mode strict`)."""
    store_root = ctx.obj.get("root", ".resdag")
    project_root = "."

    profile = load_profile(store_root)
    if profile is None:
        raise click.ClickException("No profile.json found. Run `lab init` first.")

    if key == "mode":
        if value not in ("exploratory", "disciplined", "strict"):
            raise click.ClickException(f"Invalid mode: {value}")
        new_mode = ProfileMode(value)
        init_profile(
            store_path=store_root,
            project_root=project_root,
            mode=new_mode,
            project=profile.project,
            audience=profile.audience,
        )
        click.echo(f"Mode updated to {value}")
    elif key == "audience":
        profile.audience = value
        save_profile(profile, store_root)
        click.echo(f"Audience updated to: {value}")
    elif key == "project":
        profile.project = value
        save_profile(profile, store_root)
        click.echo(f"Project updated to: {value}")
    else:
        raise click.ClickException(f"Unknown config key: {key}")


@main.command()
@click.argument("claim", required=False, default=None)
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tags.")
@click.option("--parent", "-p", "parents", multiple=True, help="Parent CIDs.")
@click.option("--suggest-parents", "do_suggest", is_flag=True, help="Show suggested parent claims.")
@click.option("--no-validate", is_flag=True, help="Skip validation checks.")
@click.option("--repo", default=".", help="Git repo path.")
@click.pass_context
def hypothesize(ctx: click.Context, claim: str | None, claim_file: str | None, domains: tuple, parents: tuple, do_suggest: bool, no_validate: bool, repo: str) -> None:
    """Declare a hypothesis."""
    claim = _resolve_claim_text(claim, claim_file)
    store = _get_store(ctx)
    parents = _resolve_cids(store, parents)
    domains = _normalize_domains(store, domains)
    if do_suggest:
        suggestions = suggest_parents(store, claim, domains=domains)
        click.echo(format_suggestions(suggestions))
    if not _run_validation(store, ClaimType.HYPOTHESIS, claim, domains, "", no_validate):
        ctx.exit(1)
        return
    cid = workflow.hypothesize(store, claim, domains=domains, parents=parents, repo_path=repo)
    click.echo(f"hypothesis {cid[:12]}  {claim}")

    # Print score in disciplined/strict modes
    profile = load_profile(store.root)
    if profile is not None and profile.mode in ("disciplined", "strict"):
        result = score_hypothesis(store, cid)
        click.echo(result.format_text())


@main.command()
@click.argument("claim", required=False, default=None)
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin).")
@click.option("--evidence", "-e", "evidence_paths", multiple=True, help="Evidence file paths.")
@click.option("--hypothesis", "-h", "hypothesis_cid", default="", help="Parent hypothesis CID.")
@click.option("--parent", "-p", "parents", multiple=True, help="Additional parent CID(s).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tags.")
@click.option("--command", "-c", "command", default="", help="Command that produced this result.")
@click.option("--cost-seconds", type=float, default=None, help="Experiment wall-clock time in seconds.")
@click.option("--cost-usd", type=float, default=None, help="Experiment cost in USD.")
@click.option("--suggest-parents", "do_suggest", is_flag=True, help="Show suggested parent claims.")
@click.option("--no-validate", is_flag=True, help="Skip validation checks.")
@click.option("--repo", default=".", help="Git repo path.")
@click.pass_context
def execute(
    ctx: click.Context,
    claim: str | None,
    claim_file: str | None,
    evidence_paths: tuple,
    hypothesis_cid: str,
    parents: tuple,
    domains: tuple,
    command: str,
    cost_seconds: float | None,
    cost_usd: float | None,
    do_suggest: bool,
    no_validate: bool,
    repo: str,
) -> None:
    """Record an experiment result."""
    claim = _resolve_claim_text(claim, claim_file)
    store = _get_store(ctx)
    if hypothesis_cid:
        hypothesis_cid = _resolve_cid(store, hypothesis_cid)
    extra_parents = _resolve_cids(store, parents)
    domains = _normalize_domains(store, domains)
    if do_suggest:
        suggestions = suggest_parents(store, claim, domains=domains)
        click.echo(format_suggestions(suggestions))
    if not _run_validation(store, ClaimType.RESULT, claim, domains, hypothesis_cid, no_validate):
        ctx.exit(1)
        return

    # Build cost trailers
    cost_trailers: list[str] = []
    if cost_seconds is not None:
        cost_trailers.append(f"cost_seconds: {cost_seconds}")
    if cost_usd is not None:
        cost_trailers.append(f"cost_usd: {cost_usd}")

    cid = workflow.execute(
        store,
        claim,
        evidence_paths=evidence_paths,
        hypothesis_cid=hypothesis_cid,
        extra_parents=extra_parents,
        domains=domains,
        command=command,
        repo_path=repo,
        extra_trailers=cost_trailers,
    )
    click.echo(f"result {cid[:12]}  {claim}")


@main.command()
@click.argument("claim")
@click.argument("result_cid")
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin). Overrides positional claim.")
@click.option("--parent", "-p", "parents", multiple=True, help="Additional parent CID(s).")
@click.option("--confirmed/--refuted", default=True, help="Was the hypothesis confirmed?")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tags.")
@click.option("--suggest-parents", "do_suggest", is_flag=True, help="Show suggested parent claims.")
@click.option("--no-validate", is_flag=True, help="Skip validation checks.")
@click.option("--repo", default=".", help="Git repo path.")
@click.pass_context
def interpret(
    ctx: click.Context,
    claim: str,
    result_cid: str,
    claim_file: str | None,
    parents: tuple,
    confirmed: bool,
    domains: tuple,
    do_suggest: bool,
    no_validate: bool,
    repo: str,
) -> None:
    """Interpret a result as confirmation or refutation."""
    claim = _resolve_claim_text(claim, claim_file)
    store = _get_store(ctx)
    result_cid = _resolve_cid(store, result_cid)
    extra_parents = _resolve_cids(store, parents)
    domains = _normalize_domains(store, domains)
    if do_suggest:
        suggestions = suggest_parents(store, claim, domains=domains)
        click.echo(format_suggestions(suggestions))
    claim_type = ClaimType.REPLICATION if confirmed else ClaimType.REFUTATION
    if not _run_validation(store, claim_type, claim, domains, "", no_validate):
        ctx.exit(1)
        return
    cid = workflow.interpret(
        store, claim, result_cid=result_cid, confirmed=confirmed,
        extra_parents=extra_parents, domains=domains, repo_path=repo
    )
    label = "replication" if confirmed else "refutation"
    click.echo(f"{label} {cid[:12]}  {claim}")


@main.command()
@click.argument("claim")
@click.argument("parent_cid")
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin). Overrides positional claim.")
@click.option("--parent", "-p", "parents", multiple=True, help="Additional parent CID(s).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tags.")
@click.option("--suggest-parents", "do_suggest", is_flag=True, help="Show suggested parent claims.")
@click.option("--no-validate", is_flag=True, help="Skip validation checks.")
@click.option("--repo", default=".", help="Git repo path.")
@click.pass_context
def branch(ctx: click.Context, claim: str, parent_cid: str, claim_file: str | None, parents: tuple, domains: tuple, do_suggest: bool, no_validate: bool, repo: str) -> None:
    """Fork research direction with a new hypothesis."""
    claim = _resolve_claim_text(claim, claim_file)
    store = _get_store(ctx)
    parent_cid = _resolve_cid(store, parent_cid)
    extra_parents = _resolve_cids(store, parents)
    domains = _normalize_domains(store, domains)
    if do_suggest:
        suggestions = suggest_parents(store, claim, domains=domains)
        click.echo(format_suggestions(suggestions))
    if not _run_validation(store, ClaimType.HYPOTHESIS, claim, domains, "", no_validate):
        ctx.exit(1)
        return
    cid = workflow.branch(store, claim, parent_cid=parent_cid, extra_parents=extra_parents, domains=domains, repo_path=repo)
    click.echo(f"hypothesis {cid[:12]}  {claim}")


@main.command()
@click.argument("claim")
@click.argument("original_cid")
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin). Overrides positional claim.")
@click.option("--parent", "-p", "parents", multiple=True, help="Additional parent CID(s).")
@click.option("--evidence", "-e", "evidence_paths", multiple=True, help="Evidence file paths.")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tags.")
@click.option("--command", "-c", "command", default="", help="Command that reproduced this.")
@click.option("--suggest-parents", "do_suggest", is_flag=True, help="Show suggested parent claims.")
@click.option("--no-validate", is_flag=True, help="Skip validation checks.")
@click.option("--repo", default=".", help="Git repo path.")
@click.pass_context
def replicate(
    ctx: click.Context,
    claim: str,
    original_cid: str,
    claim_file: str | None,
    parents: tuple,
    evidence_paths: tuple,
    domains: tuple,
    command: str,
    do_suggest: bool,
    no_validate: bool,
    repo: str,
) -> None:
    """Record a replication attempt."""
    claim = _resolve_claim_text(claim, claim_file)
    store = _get_store(ctx)
    original_cid = _resolve_cid(store, original_cid)
    extra_parents = _resolve_cids(store, parents)
    domains = _normalize_domains(store, domains)
    if do_suggest:
        suggestions = suggest_parents(store, claim, domains=domains)
        click.echo(format_suggestions(suggestions))
    if not _run_validation(store, ClaimType.REPLICATION, claim, domains, "", no_validate):
        ctx.exit(1)
        return
    cid = workflow.replicate(
        store,
        claim,
        original_cid=original_cid,
        extra_parents=extra_parents,
        evidence_paths=evidence_paths,
        domains=domains,
        command=command,
        repo_path=repo,
    )
    click.echo(f"replication {cid[:12]}  {claim}")


@main.command()
@click.argument("claim", required=False, default=None)
@click.option("--claim-file", "-f", "claim_file", default=None,
              help="Read claim text from file (use - for stdin).")
@click.option("--domain", "-d", "domains", multiple=True, help="Domain tags.")
@click.option("--suggest-parents", "do_suggest", is_flag=True, help="Show suggested parent claims.")
@click.option("--repo", default=".", help="Git repo path.")
@click.pass_context
def note(ctx: click.Context, claim: str | None, claim_file: str | None, domains: tuple, do_suggest: bool, repo: str) -> None:
    """Quick note — no validation, no structure required."""
    claim = _resolve_claim_text(claim, claim_file)
    store = _get_store(ctx)

    # Strict mode disables lab note entirely
    profile = load_profile(store.root)
    if profile is not None and profile.mode == "strict":
        click.echo("Error: `lab note` is disabled in strict mode. Use `lab execute` with proper structure.", err=True)
        ctx.exit(1)
        return

    domains = _normalize_domains(store, domains)
    if do_suggest:
        suggestions = suggest_parents(store, claim, domains=domains)
        click.echo(format_suggestions(suggestions))
    cid = workflow.execute(store, claim, domains=domains, repo_path=repo)
    click.echo(f"result {cid[:12]}  {claim}")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--costs", is_flag=True, help="Show cost metrics instead of structural health.")
@click.pass_context
def audit(ctx: click.Context, as_json: bool, costs: bool) -> None:
    """Report structural quality of the DAG."""
    import json as _json

    store = _get_store(ctx)

    if costs:
        cost_report = audit_costs(store)
        if as_json:
            click.echo(_json.dumps(cost_report.to_dict(), indent=2, sort_keys=True))
        else:
            click.echo(cost_report.format_text())
        return

    report = audit_dag(store)

    if as_json:
        click.echo(_json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        click.echo(report.format_text())


@main.command()
@click.argument("cid")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def score(ctx: click.Context, cid: str, as_json: bool) -> None:
    """Score a hypothesis on quality dimensions (specificity, falsifiability, grounding, novelty)."""
    import json as _json

    store = _get_store(ctx)

    # Resolve short CID prefix
    matches = [c for c in store.list_cids() if c.startswith(cid)]
    if len(matches) == 0:
        raise click.ClickException(f"No claim found matching {cid}")
    if len(matches) > 1:
        raise click.ClickException(f"Ambiguous CID prefix {cid} — matches {len(matches)} claims")

    try:
        result = score_hypothesis(store, matches[0])
    except ValueError as e:
        raise click.ClickException(str(e))

    if as_json:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format_text())


@main.command()
@click.argument("cid")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def cost(ctx: click.Context, cid: str, as_json: bool) -> None:
    """Estimate information gain for executing a hypothesis."""
    import json as _json

    store = _get_store(ctx)

    # Resolve short CID prefix
    matches = [c for c in store.list_cids() if c.startswith(cid)]
    if len(matches) == 0:
        raise click.ClickException(f"No claim found matching {cid}")
    if len(matches) > 1:
        raise click.ClickException(f"Ambiguous CID prefix {cid} — matches {len(matches)} claims")

    try:
        result = estimate_cost(store, matches[0])
    except ValueError as e:
        raise click.ClickException(str(e))

    if as_json:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.format_text())


@main.command()
@click.option("--for", "for_cid", default="", help="Check contradictions for a specific claim CID.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def contradictions(ctx: click.Context, for_cid: str, as_json: bool) -> None:
    """Detect contradictions in the DAG."""
    import json as _json

    store = _get_store(ctx)

    if for_cid:
        # Resolve short CID prefix
        matches = [c for c in store.list_cids() if c.startswith(for_cid)]
        if len(matches) == 0:
            raise click.ClickException(f"No claim found matching {for_cid}")
        if len(matches) > 1:
            raise click.ClickException(f"Ambiguous CID prefix {for_cid}")
        results = find_contradictions_for(store, matches[0])
    else:
        results = find_all_contradictions(store)

    if as_json:
        click.echo(_json.dumps([c.to_dict() for c in results], indent=2))
    else:
        click.echo(format_contradictions(results))


@main.command()
@click.option("--open", "open_only", is_flag=True, help="Show only open (unresolved) threads.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def threads(ctx: click.Context, open_only: bool, as_json: bool) -> None:
    """List research threads (hypothesis + descendants)."""
    import json as _json

    store = _get_store(ctx)
    all_threads = discover_threads(store)

    if open_only:
        all_threads = [t for t in all_threads if t.status == "open"]

    if as_json:
        click.echo(_json.dumps([thread_to_dict(t) for t in all_threads], indent=2))
    else:
        if not all_threads:
            click.echo("No threads found." if not open_only else "No open threads.")
            return

        for t in all_threads:
            status_icon = {"open": "○", "confirmed": "✓", "refuted": "✗", "mixed": "◐"}.get(t.status, "?")
            domains = f" [{', '.join(t.domains)}]" if t.domains else ""
            click.echo(f"{status_icon} {t.status:<10} {t.hypothesis_cid[:12]}  {t.hypothesis_text}")
            click.echo(f"  {t.claim_count} claims · {t.first_date[:10]}–{t.last_date[:10]}{domains}")


@main.group("vocab")
@click.pass_context
def vocab_group(ctx: click.Context) -> None:
    """Vocabulary management commands."""
    pass


@vocab_group.command("analyze")
@click.pass_context
def vocab_analyze(ctx: click.Context) -> None:
    """Report per-claim normalization diff without modifying store."""
    store = _get_store(ctx)
    vocab = load_vocabulary(store.root)
    if vocab is None:
        ctx.fail("No vocabulary.json found. Run `lab init` first.")

    changes = 0
    total = 0
    for cid in store.list_cids():
        claim = store.get(cid)
        if not claim.domain:
            continue
        total += 1
        normalized, _ = vocab.normalize(claim.domain)
        original = sorted(claim.domain)
        if normalized != original:
            changes += 1
            click.echo(f"{cid[:12]}  {list(claim.domain)} → {normalized}")

    click.echo(f"\n{changes}/{total} claims would change.")


@main.command("migrate-tags")
@click.pass_context
def migrate_tags(ctx: click.Context) -> None:
    """Normalize domain tags on all existing claims to canonical form."""
    import json as _json

    store = _get_store(ctx)
    vocab = load_vocabulary(store.root)
    if vocab is None:
        ctx.fail("No vocabulary.json found. Save one first with default_vocabulary().")

    migrated = 0
    for cid in store.list_cids():
        claim = store.get(cid)
        if not claim.domain:
            continue
        normalized, _ = vocab.normalize(claim.domain)
        if tuple(sorted(normalized)) == tuple(sorted(claim.domain)):
            continue

        # Create replacement claim with normalized domains
        new_claim = Claim(
            claim=claim.claim,
            type=claim.type,
            parents=claim.parents,
            evidence=claim.evidence,
            domain=tuple(normalized),
            author=claim.author,
            timestamp=claim.timestamp,
            signature=claim.signature,
        )
        new_cid = store.put(new_claim)

        # Create supersession refutation
        payload = _json.dumps({
            "superseded_by": new_cid,
            "reason": "Tags normalized to canonical form",
        }, sort_keys=True)
        sup = Claim(
            claim=payload,
            type=ClaimType.REFUTATION,
            parents=(cid,),
        )
        store.put(sup)
        migrated += 1

    click.echo(f"Migrated {migrated} claims to canonical tags.")


@main.command()
@click.argument("target")
@click.option("--no-site", is_flag=True, help="Skip site generation.")
@click.option("--include-evidence", is_flag=True, help="Also push evidence artifacts.")
@click.pass_context
def push(ctx: click.Context, target: str, no_site: bool, include_evidence: bool) -> None:
    """Push DAG to a target directory (incremental) and render site."""
    store = _get_store(ctx)
    target_store = LocalStore(target)
    result = gossip_push(store, target_store, include_evidence=include_evidence)

    if result.claims_pushed == 0 and result.evidence_pushed == 0:
        click.echo("Already in sync.")
    else:
        click.echo(f"Pushed {result.claims_pushed} claims, {result.evidence_pushed} evidence")

    # Copy vocabulary to target so the rendered site uses canonical tags
    vocab = load_vocabulary(store.root)
    if vocab is not None:
        save_vocabulary(vocab, target_store.root)

    if not no_site:
        site_dir = Path(target) / "site"
        count = generate_site(target_store, site_dir)
        click.echo(f"Site rendered: {count} claims → {site_dir}/index.html")


@main.command()
@click.argument("output_dir")
@click.pass_context
def render(ctx: click.Context, output_dir: str) -> None:
    """Render a browsable static site from the current store."""
    store = _get_store(ctx)
    count = generate_site(store, output_dir)
    click.echo(f"Site rendered: {count} claims → {output_dir}/index.html")
