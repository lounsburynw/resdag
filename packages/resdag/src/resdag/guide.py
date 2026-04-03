"""ResDAG usage guide — embedded for `res init` and `res guide`."""

GUIDE = """\
# ResDAG Guide

ResDAG tracks research claims as a content-addressed DAG. Think `git` for
research results: commit claims, attach evidence, sync between peers.

## Quick Start

    res init                          # create .resdag/ in current directory
    res commit -c "..." -t result     # commit a claim
    res log                           # list all claims
    res show <cid>                    # show claim details

## Commands

    res init              Initialize a resdag repository (.resdag/)
    res commit            Create a new claim
    res note "text"       Quick-commit a result (minimal ceremony)
    res ingest file.json  Auto-generate claims from JSON
    res log               List all claims (with filters)
    res show <cid>        Show claim details (supports CID prefix)
    res lineage <cid>     Show ancestor/descendant tree
    res supersede <old> <new>  Mark a claim as superseded
    res export <dir>      Export subgraph, static site, or Atom feed
    res sync <path>       Sync with another local resdag store
    res guide             Print this guide

## Claim Types

Use the `-t` flag on `res commit`:

    result        An experimental result or finding
    method        A technique, procedure, or design decision
    hypothesis    A prediction or conjecture to be tested
    replication   A reproduction of an existing result
    equivalence   An assertion that two claims are semantically equivalent
    refutation    Evidence against an existing claim

## Committing Claims

Every claim needs text (`-c`) and a type (`-t`). Everything else is optional.

    # Simple result
    res commit -c "Model achieves 92% accuracy on test set" -t result

    # Result with evidence file
    res commit -c "Grokking at epoch 31 for (a*b+c) mod 23" -t result \\
        -e results/grokking_level2.json

    # Method with domain tags
    res commit -c "Three-tier architecture: Router → Motifs → Specialists" \\
        -t method -d architecture -d design

    # Hypothesis that builds on a previous claim
    res commit -c "Distillation will close the retrieval gap" -t hypothesis \\
        -p <parent-cid>

    # Refutation of a prior claim
    res commit -c "Distillation gap remains at 78%" -t refutation \\
        -p <refuted-claim-cid> -e results/distillation_analysis.json

## Flags

    -c, --claim TEXT      Claim text (required)
    -t, --type TYPE       Claim type (required, see types above)
    -p, --parent CID      Parent claim CID (repeatable)
    -d, --domain TAG      Domain tag (repeatable)
    -a, --author DID      Author DID
    -e, --evidence FILE   Evidence file to attach (repeatable)
    -T, --timestamp ISO   ISO 8601 timestamp (default: now)

## Parent Links

Use `-p <cid>` to link a claim to its logical predecessors:

- A replication links to the claim it reproduces
- A refutation links to the claim it refutes
- A result links to the hypothesis or method it tests
- An equivalence links to exactly two claims it equates

CID prefixes work: `res commit -p bafk3q...` resolves to the full CID.

## Evidence

Attach any file as evidence. Files are stored by content hash — duplicates
are automatic no-ops.

    res commit -c "Benchmark results" -t result \\
        -e data/benchmark.csv \\
        -e data/benchmark.json

Evidence metadata (filename, media type, size) is shown in `res show`.

## Quick Commits

For lightweight results during active work, skip the ceremony:

    res note "grokking happens at 10k steps"
    res note "distillation gap is 4.2%" -d grokking

This is sugar for `res commit -c "..." -t result`. Use full `res commit`
when you need evidence, parents, or a non-result type.

## Auto-Ingestion

Generate claims from structured experiment outputs:

    res ingest results.json --template "Accuracy: {accuracy}% at {steps} steps"
    res ingest results.json -t method -d training --template "{description}"

JSON arrays create one claim per element. The file is attached as evidence.

## Querying

Filter the log by domain, type, or date:

    res log --domain grokking
    res log --type refutation
    res log --after 2026-03-01
    res log --domain grokking --type result    # filters compose (AND)

Find structural issues:

    res log --orphans                          # claims missing parent links
    res log --unverified                       # claims with no verification
    res log --active                           # hide superseded claims

Show an ancestor/descendant tree:

    res lineage <cid>

Mark a claim as superseded by a corrected version:

    res supersede <old-cid> <new-cid> --reason "Fixed parent links"

## Syncing

Sync with another local resdag store (bidirectional by default):

    res sync /path/to/peer/.resdag
    res sync /path/to/peer/.resdag --push-only
    res sync /path/to/peer/.resdag --pull-only
    res sync /path/to/peer/.resdag --include-evidence

Content-addressing means no duplicates. Append-only DAG means no conflicts.

## Exporting

Export a subgraph to a new resdag store:

    res export ./pub --domain neuroscience --include-ancestors
    res export ./pub --cid <cid> --include-evidence

Generate a static HTML site:

    res export ./site --site

Generate an Atom feed:

    res export ./out --feed
    res export ./out --feed --feed-title "My Research" --base-url https://example.com
    res export ./out --feed -d physics          # only physics claims
    res export ./out --site --feed              # both site and feed

## When to Commit

Commit when you have something worth recording:

- **Ran an experiment** → result + evidence JSON
- **Made a design decision** → method + rationale in claim text
- **Formed a hypothesis** → hypothesis, optionally linked to motivating results
- **Reproduced something** → replication linked to the original
- **Disproved something** → refutation linked to the original + evidence
- **Found two claims say the same thing** → equivalence linking both

If you wouldn't bother writing it in a lab notebook, don't commit it.

## Content Addressing

Every claim gets a CID (Content IDentifier) derived from its content.
Same content always produces the same CID. This means:

- Duplicate commits are no-ops
- Integrity is verifiable (content matches hash)
- Sync is conflict-free (same CID = same claim)
- No central authority needed

## For AI Tools

If you're an AI assistant working in a project that uses resdag:

1. Run `res log` to see existing claims
2. After producing results, commit them with `res commit`
3. Link new claims to relevant parents with `-p`
4. Attach data files as evidence with `-e`
5. Use domain tags (`-d`) for categorization
6. Use `res show <cid>` to inspect any claim's full context
"""
