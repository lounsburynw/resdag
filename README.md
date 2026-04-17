# ResDAG

**Git for research primitives.**

An open protocol for decentralized, content-addressed research claims organized as a directed acyclic graph. Commit results like code. Verify incrementally. Discover connections across domains.

## Why

Scientific publishing is broken: AI generates hypotheses faster than humans can verify them, papers are the wrong unit of knowledge, and independent replications are disincentivized. ResDAG inverts this by making the **claim** (not the paper) the atomic unit, organizing claims in a **DAG** (not a journal), and treating **verification as a first-class node type** (not a gatekeeping step).

## The Research Commit

The entire protocol centers on one data structure:

```json
{
  "claim": "natural language assertion",
  "type": "result | method | hypothesis | replication | equivalence | refutation | supersession",
  "parents": ["cid..."],
  "evidence": ["cid..."],
  "domain": ["free.form.tags"],
  "author": "did:key:...",
  "timestamp": "ISO8601",
  "signature": "..."
}
```

Everything else — verification, equivalence, reputation, review — is built from this primitive.

## Architecture

```
Layer 0: Protocol    — content-addressed claims + DAG structure (this repo)
Layer 1: Storage     — local-first, sync via gossip (like git remotes)
Layer 2: Tools       — indexing, equivalence detection, verification
Layer 3: Applications — lab notebooks, research feeds, static sites
```

## Quick Start

```bash
# Install
pip install -e packages/resdag

# Initialize a store
res init

# Commit a claim
res commit "Grokking emerges at 2x the interpolation threshold on modular addition" -t result -d grokking -e data.json

# View the DAG
res log
res lineage <cid>

# Export a static site
res export site ./public
```

### reslab — Scientific Workflow Platform

A higher-level tool for structured research workflows, built on resdag:

```bash
pip install -e packages/reslab

lab init --mode disciplined
lab hypothesize "I predict accuracy >90% at 5000 steps" -d training
lab score <hypothesis-cid>                    # quality scoring (specificity, falsifiability, grounding, novelty)
lab execute "Accuracy was 87%" --hypothesis <cid> --cost-seconds 1800
lab interpret "Below threshold" <result-cid> --refuted
lab contradictions                            # detect conflicting claims
lab threads --open                            # unresolved research threads
lab audit --costs                             # spend by domain and thread
lab render                                    # browsable static site
```

## Design Principles

1. **Claims, not papers** — A single assertion with provenance, not a 10-page narrative.
2. **Commit first, verify later** — Anyone can commit. Verification attaches asynchronously.
3. **No retraction, only supersession** — You don't delete claims. History is permanent.
4. **Protocol owned by nobody** — Like git, HTTP, SMTP. Platforms build on top.
5. **Independent replication is visible** — Two nodes with no common ancestors making the same claim = strongest possible evidence. The DAG makes this structural.
6. **Verification is a node, not a stamp** — Verification receipts are DAG nodes with their own provenance.
7. **Local-first** — Works entirely offline. An air-gapped network gets full value.
8. **Selective export** — Any subgraph is extractable as a standalone DAG. Publish what you choose; internal context stays behind.

## Project Structure

```
packages/
├── resdag/          # Core protocol library (CLI: `res`)
│   └── src/resdag/
│       ├── claim.py       # Claim data structure + CID generation
│       ├── dag.py         # DAG operations
│       ├── evidence.py    # Evidence artifact handling
│       ├── identity.py    # DID-based author identity
│       ├── cli.py         # Command-line interface
│       ├── storage/       # Storage backends
│       ├── sync/          # Peer synchronization
│       ├── verify/        # Verification framework
│       ├── discover/      # Discovery and equivalence
│       └── export/        # Output formats (site, feed, subgraph)
│
└── reslab/          # Scientific workflow platform (CLI: `lab`)
    └── src/reslab/
        ├── cli.py             # Command-line interface
        ├── workflow.py        # Hypothesize → execute → interpret
        ├── scoring.py         # Hypothesis quality scoring
        ├── contradictions.py  # Contradiction detection
        ├── costs.py           # Cost tracking and estimation
        ├── git_binding.py     # Git state capture for provenance
        └── site/              # Interactive DAG visualization
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Status

Early-stage. The protocol spec and core implementation are working (836 tests passing). Storage, sync, verification, and discovery layers are functional. The protocol is stabilizing but not yet frozen.

## License

MIT
