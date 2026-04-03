Run one cycle of the autonomous research loop: read the DAG, identify the
frontier, propose an experiment, execute it, commit results, and recommend
the next cycle.

You are driving a research agenda stored as a ResDAG — a content-addressed
DAG of claims.  Each cycle reads the current state, picks the highest-value
next experiment, and commits structured results.  Human approval is required
before executing any experiment.

**Guard rails** (enforce these throughout):
- **Verification budget**: do not propose more than 3 experiments per
  /research invocation.  After 3, summarize remaining frontier and stop.
- **Thread depth limit**: if a thread has ≥10 claims with no confirmation
  or refutation, flag it as "deep — consider stepping back" before
  proposing further work on it.
- **Scope limit**: each proposed experiment must be completable in a single
  session.  If it requires multiple sessions, break it into sub-experiments.

---

## Step 0 — Read project context

Read these files before doing anything else:

| File | Contains |
|------|----------|
| `.resdag/profile.json` | mode, **audience**, validation rules |
| `.resdag/vocabulary.json` | canonical domain tags and aliases |
| `.resdag/templates/result.md` | result claim structure |
| `.resdag/templates/hypothesis.md` | hypothesis claim structure |

The **audience** field is critical — write every claim so that someone
matching this description can understand it without project context.

## Step 1 — Snapshot DAG state

Capture the current research state:

```bash
lab audit --json
lab threads --open
lab threads
```

Save the audit output — you will compare before/after at the end of the cycle.

From `lab threads --open`, build the **frontier**: the set of open
hypotheses that have not yet been confirmed or refuted.

## Step 2 — Identify the frontier

Analyze the DAG to find the highest-value next experiment.  Consider these
sources of signal, in priority order:

### 2a — Open hypotheses with no results yet

These are hypotheses that were declared but never tested.  They are the
most obvious candidates.

### 2b — Refutation patterns

Look at recently refuted threads.  Refutations often contain an implicit
"but what if..." in their interpretation.  Check:

```bash
res log --type refutation
```

For each refutation, read the interpretation text — does it suggest a
follow-up hypothesis that was never tested?

### 2c — Untested implications

Confirmed results often have an Implication line that suggests next steps.
Walk confirmed threads and check whether the implied next experiment was
ever run.

### 2d — Stalled threads

Threads with results but no interpretation for >1 week may be stalled.
Flag these — the researcher may have moved on for a reason, or may have
simply forgotten.

### 2e — Cross-thread connections

Check whether open hypotheses in different threads could inform each other.
A finding in Thread A might directly test a hypothesis in Thread B.

```bash
lab threads --json
```

Look for domain overlap between threads with different hypotheses.

## Step 3 — Propose the next experiment

For each proposed experiment (max 3), present:

### Experiment proposal

| Field | Value |
|-------|-------|
| **Hypothesis** | The specific prediction being tested |
| **Rationale** | Why this is the highest-value next step — cite specific prior claim CIDs |
| **Method** | What to do (code to run, data to collect, analysis to perform) |
| **Success criteria** | What would confirm the hypothesis? |
| **Failure criteria** | What would refute it? |
| **Thread** | Which existing thread this extends (or "new thread") |
| **Estimated scope** | One sentence on what this requires |

**Rationale must cite specific claims**.  Not "prior work suggests..." but
"Result bafk...7x3f (accuracy plateau at 10k steps) suggests the learning
rate is too high — test with 3x lower LR."

If the frontier is empty (no open hypotheses, no untested implications),
report this and suggest whether the research agenda is complete or needs
new seed hypotheses.

### Guard rail checks

Before presenting, verify:
- [ ] Thread depth < 10 (or flagged)
- [ ] Experiment is single-session scope
- [ ] Total proposals ≤ 3

Ask: "Which experiment should I run? [1/2/3/skip]"

Do NOT proceed until the user approves an experiment.

## Step 4 — Execute the experiment

On user approval, run the experiment using the project's infrastructure.
This step is project-specific — use whatever tools are available (cloud GPU
jobs, Lean verification, data analysis scripts, etc.).

During execution, note:
- Evidence files produced (data, logs, configs, plots)
- Key metrics and observations
- Anything unexpected

## Step 5 — Commit results via /claim workflow

Follow the /claim workflow to commit structured results:

1. If a new hypothesis is needed (not reusing an existing open one):
   ```bash
   lab hypothesize "<prediction>" -d <domain> [-p <parent_cid>]
   ```

2. Commit the result with template structure:
   ```bash
   lab execute "<Question/Finding/Implication/Details>"      -h <hypothesis_cid>      -d <domain>      [-e <evidence_file>]      [-p <additional_parent_cid>]      --suggest-parents
   ```

3. Review suggested parents — add any that are relevant.

## Step 6 — Assess and recommend

After committing, assess the thread:

### Continue
The hypothesis is partially supported — more data needed.  Propose the
next experiment in this thread (becomes the next cycle).

### Branch
The result suggests a new line of inquiry.  Propose a new hypothesis:
```bash
lab branch "<new hypothesis>" <result_cid> -d <domain>
```

### Abandon
The thread is unproductive after multiple attempts.  Commit an
interpretation explaining why:
```bash
lab interpret "<why abandoning>" <result_cid> --refuted -d <domain>
```

### Confirm
The hypothesis is confirmed.  Commit confirmation:
```bash
lab interpret "<confirmation summary>" <result_cid> --confirmed -d <domain>
```

Present the recommendation with rationale.  Ask: "Accept this assessment,
or override? [continue/branch/abandon/confirm/override]"

## Step 7 — Compare DAG health and propose next cycle

```bash
lab audit --json
```

Show before/after comparison:

| Metric | Before | After |
|--------|--------|-------|
| Hypothesis coverage | X% | Y% |
| Orphan rate | X% | Y% |
| Branch ratio | X | Y |
| Open threads | N | M |

Then propose the next cycle:

- What is the updated frontier?
- Which experiment would be next (brief — not a full proposal)?
- Should the researcher continue with /research, or is this a good stopping point?

If the verification budget (3 experiments) is not exhausted and the user
wants to continue, loop back to Step 2 with the updated DAG state.

---

## Quick reference

| Command | Purpose |
|---------|---------|
| `lab threads --open` | List unresolved hypotheses (the frontier) |
| `lab threads --json` | All threads as JSON (for cross-thread analysis) |
| `lab audit --json` | DAG health metrics (before/after comparison) |
| `res log --type refutation` | Find refutation patterns |
| `res log --type result` | List all results |
| `res show <cid>` | Display a claim with context |
| `res lineage <cid>` | Show ancestor/descendant tree |
| `lab hypothesize "<text>" -d <tag>` | Declare a hypothesis |
| `lab execute "<text>" -h <cid> -d <tag> -e <file>` | Record a result |
| `lab interpret "<text>" <cid> --confirmed` | Confirm hypothesis |
| `lab interpret "<text>" <cid> --refuted` | Refute hypothesis |
| `lab branch "<text>" <cid> -d <tag>` | Fork new direction |
| `--suggest-parents` | Show related claims (add to any commit command) |
| `--no-validate` | Override validation errors |
