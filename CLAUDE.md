# CLAUDE.md

**ResDAG** — An open protocol for decentralized, content-addressed research claims organized as a directed acyclic graph. Commit results like code. Verify incrementally. Discover connections across domains.

## Vision

Scientific publishing is broken: AI generates hypotheses faster than humans can verify them, papers are the wrong unit of knowledge, and independent replications are disincentivized. ResDAG inverts this by making the **claim** (not the paper) the atomic unit, organizing claims in a **DAG** (not a journal), and treating **verification as a first-class node type** (not a gatekeeping step).

### Core Architecture

```
Layer 0: Protocol (open standard — content-addressed claims + DAG structure)
         - Claims, evidence, verification receipts, equivalence assertions
         - Content-addressed (CID/hash), self-describing, no central authority

Layer 1: Storage & Sync (decentralized — peers gossip, hubs index)
         - Local-first: commit without permission
         - Sync via gossip protocol (like git remotes)
         - Hubs are convenient, not authoritative

Layer 2: Tools (AI-powered — indexing, equivalence detection, verification)
         - Embedding-based candidate surfacing
         - Formal verification where domain permits
         - Contradiction detection, replication tracking

Layer 3: Applications (user-facing — microblogs, lab notebooks, journals)
         - Static site generators, research feeds
         - Domain-specific UIs
         - Integration with existing platforms (arXiv, GitHub, OSF)
```

### The Research Commit

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

### Key Design Principles

1. **Claims, not papers** — The atomic unit is a single assertion with provenance, not a 10-page narrative.
2. **Commit first, verify later** — Anyone can commit. Verification attaches asynchronously, like CI on a git push.
3. **Equivalence is a claim, not preprocessing** — Semantic deduplication is itself a scientific assertion with scope and provenance.
4. **No retraction, only supersession** — You don't delete claims, you create refutation or supersession nodes. History is permanent.
5. **Protocol owned by nobody** — Like git, HTTP, SMTP. Platforms build on top. The protocol is not a product.
6. **Independent replication is visible** — Two nodes with no common ancestors making the same claim = strongest possible evidence. The DAG makes this structural.
7. **Verification is a node, not a stamp** — Verification receipts are DAG nodes with their own provenance, methods, and verifiability.
8. **Firewalled by default** — No network required. Sync is opt-in, not opt-out. An isolated DAG on an air-gapped network gets full value. This enables private or sensitive research where IP or confidentiality concerns apply.

### Use Cases

**Open research (personal/academic):**
Commit experiment results as claims → attach data/code as evidence → export as a microblog or static site → sync to public hubs. Independent replications become visible in the graph structure.

**Private research (teams/organizations):**
Internal DAG on a private network → teams commit results, negative findings, intermediate data → "did anyone already try this?" becomes a query, not a Slack message → audit trail for free (every claim has timestamp, author, evidence, provenance chain). When results become publishable, selectively export a subgraph to a public DAG — provenance travels with it, internal context stays behind.

**Dual-use (one researcher, two contexts):**
A researcher's local node sees both their public and private DAGs. They control what syncs where. The protocol doesn't distinguish public from private — isolation is just "who are your sync peers."

## Quick Start

```bash
cat features.json          # Feature checklist
cat claude-progress.txt    # Where we are
```

## Session Protocol

1. Run `/start` — check environment, find next work item
2. Work on ONE item per session
3. Run `/commit` — runs critics, then commits if they pass
4. Run `/nextsesh` — prepare handoff notes before ending

## Priority Levels

| Priority | Meaning | Rule |
|----------|---------|------|
| **P0** | Immediate/blocking | **At most ONE P0 at a time** |
| **P1** | Current sprint | Active work |
| **P2** | Planned | Upcoming |
| **P3** | Nice to have | Backlog |

Sessions must assign exactly 1 P0 before ending. `/start` picks the highest-priority item. `/nextsesh` will fail if no P0 is set.

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/start` | Begin session, find next item |
| `/commit` | Run critics on staged changes, then commit |
| `/critic [name]` | Run codebase critics |
| `/nextsesh` | Prepare handoff notes |

## Codebase Critics

LLM-based review prompts in `.critics/`. Run with `/critic`. Critics output JSON with `pass`, `issues`, `severity`. Critical failures block commit.

| Critic | Purpose |
|--------|---------|
| `protocol.critic.md` | Protocol invariants: content-addressing, DAG consistency, no central authority |
| `claims.critic.md` | Claims about the protocol/system are well-scoped and evidence-backed |
| `simplicity.critic.md` | Protocol stays minimal; complexity belongs in layers above |

## Testing

```bash
uv run --package resdag pytest packages/resdag/tests -q   # resdag tests
uv run --package reslab pytest packages/reslab/tests -q   # reslab tests
```

## Project Structure

This is a **uv workspace monorepo** with two packages:

```
CLAUDE.md                           # Project instructions (this file)
features.json                       # Feature checklist with priorities and status
claude-progress.txt                 # Session state (append-only)
pyproject.toml                      # Workspace root (virtual, not publishable)
.critics/                           # LLM code review prompts
.claude/commands/                   # Slash command definitions
docs/                               # Architecture and decision records

packages/
├── resdag/                         # Layer 0-2: Core protocol library
│   ├── pyproject.toml              # Package config (CLI: `res`)
│   ├── src/resdag/
│   │   ├── __init__.py
│   │   ├── claim.py                # Claim data structure + serialization
│   │   ├── dag.py                  # DAG operations (add, query, traverse)
│   │   ├── evidence.py             # Evidence artifact handling
│   │   ├── identity.py             # DID-based author identity
│   │   ├── guide.py                # Embedded usage guide
│   │   ├── cli.py                  # Command-line interface (`res`)
│   │   ├── storage/                # Storage backends
│   │   ├── sync/                   # Peer synchronization
│   │   ├── verify/                 # Verification framework
│   │   ├── discover/               # Discovery and equivalence
│   │   └── export/                 # Output formats (site, feed, subgraph)
│   └── tests/
│
└── reslab/                         # Layer 3: Scientific workflow platform
    ├── pyproject.toml              # Package config (CLI: `lab`)
    ├── src/reslab/
    │   ├── __init__.py
    │   ├── cli.py                  # Command-line interface (`lab`)
    │   ├── workflow.py             # Workflow primitives (hypothesize, execute, interpret)
    │   ├── git_binding.py          # Git state capture for provenance
    │   └── site/                   # Interactive DAG visualization
    └── tests/
```

## Design Constraints

1. **The protocol is the product** — Every design decision must be evaluated as "does this belong in the protocol, or in a layer above?" When in doubt, leave it out.
2. **Content-addressing is non-negotiable** — Every object is identified by its content hash. This enables dedup, integrity verification, and decentralized storage without coordination.
3. **Local-first** — Must work entirely offline. Network is for sync, not for function. A private deployment on an air-gapped network must get full value from the protocol.
4. **No financial layer in the protocol** — Tokens, incentives, and monetization are application-layer concerns. Mixing them into the base protocol is how DeSci projects fail.
5. **Natural language claims** — Claims are human-readable text, not RDF triples or formal logic. Structure comes from the DAG and metadata, not from constraining what people can say.
6. **Git-compatible** — The local storage format should be git-friendly so claims can live in repos naturally.
7. **Selective export** — Any subgraph must be extractable as a standalone DAG. This enables: publishing a subset of internal claims, sharing results without context, and bridging firewalled and public DAGs. Export strips what you don't include; it never leaks what you didn't select.

## Related Work & Context

- **Git** — Core inspiration. Content-addressed DAG, local-first, protocol vs. platform separation. ResDAG is "git for research claims."
- **Nanopublications** — Smallest publishable unit (RDF assertions + provenance). Right idea, wrong format (RDF is too rigid). ResDAG uses natural language claims.
- **Octopus.ac** — Breaks papers into 8 research stages. Right direction but still paper-shaped. ResDAG is claim-shaped.
- **ResearchHub** — Token incentives for peer review. Incentive layer collapsed (RSC -91%). Validates: keep financial layer out of protocol.
- **Knowledge Provenance Protocol** — SEC submission proposing DAG + blockchain for research. Closest to ResDAG's architecture but adds unnecessary financial complexity.
- **IPFS / Content-Addressing** — Foundation technology. ResDAG uses CIDs for all objects.
- **DeSci ecosystem** — 49 projects, 96% still active but slow progress. Validates the need; most fail by coupling too many concerns.
- **Valsci** — Open-source claim verification against literature (F1=0.761). Potential Layer 2 tool.
- **Scite.ai** — Citation classification (supporting/contrasting/mentioning). 1.6B+ citations. Layer 2 integration target.
- **OpenAlex** — Open scholarly knowledge graph. 190M works. Layer 2/3 integration target.
- **Verification-First AI** (arxiv:2601.16909) — Formalizes verification bottleneck. AI should be adversarial auditor, not score predictor.
- **Software Heritage** — Merkle DAG for archiving source code. SWHID became ISO standard 2025. Validates DAG approach at scale.

## Key Dependencies

- **Python 3.11+** — Core implementation
- **multiformats** — CID generation (content-addressing)
- **cryptography** — Signing, identity
- **click** — CLI framework
- **Jinja2** — Static site generation
- **sentence-transformers** — Embedding-based similarity (Layer 2)

## Research Claims (reslab)
Commit findings with `lab execute "..." -d domain -e data.json`.
Quick notes: `lab note "..."`.
Domain vocabulary: architecture, data, evaluation, grokking, inference, lean, replication, scaling, theory, tooling, training, verification.
