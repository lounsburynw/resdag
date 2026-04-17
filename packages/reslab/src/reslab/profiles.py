"""Project profiles for reslab.

`lab init --mode <mode>` generates a project profile that shapes all future
commits.  Three modes: exploratory, disciplined, strict.  See ADR-001.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ProfileMode(str, Enum):
    EXPLORATORY = "exploratory"
    DISCIPLINED = "disciplined"
    STRICT = "strict"


@dataclass
class ValidationRules:
    hypothesis_parent: str = "off"
    claim_structure: str = "off"
    vocabulary: str = "off"


@dataclass
class Profile:
    mode: str
    project: str
    audience: str
    validation: ValidationRules

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "project": self.project,
            "audience": self.audience,
            "validation": asdict(self.validation),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        v = data.get("validation", {})
        return cls(
            mode=data.get("mode", "exploratory"),
            project=data.get("project", ""),
            audience=data.get("audience", ""),
            validation=ValidationRules(
                hypothesis_parent=v.get("hypothesis_parent", "off"),
                claim_structure=v.get("claim_structure", "off"),
                vocabulary=v.get("vocabulary", "off"),
            ),
        )


PROFILE_FILENAME = "profile.json"


def mode_defaults(mode: ProfileMode) -> ValidationRules:
    """Return validation presets for the given mode."""
    if mode is ProfileMode.EXPLORATORY:
        return ValidationRules(
            hypothesis_parent="off",
            claim_structure="off",
            vocabulary="warn",
        )
    if mode is ProfileMode.DISCIPLINED:
        return ValidationRules(
            hypothesis_parent="warn",
            claim_structure="warn",
            vocabulary="warn",
        )
    # strict
    return ValidationRules(
        hypothesis_parent="require",
        claim_structure="require",
        vocabulary="require",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_profile(profile: Profile, store_path: str | Path) -> None:
    p = Path(store_path)
    p.mkdir(parents=True, exist_ok=True)
    (p / PROFILE_FILENAME).write_text(
        json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n"
    )


def load_profile(store_path: str | Path) -> Profile | None:
    p = Path(store_path) / PROFILE_FILENAME
    if not p.exists():
        return None
    with open(p) as f:
        return Profile.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

_HYPOTHESIS_TEMPLATE = """\
Prediction: <!-- What do you expect to happen? -->
Rationale: <!-- Why do you expect this? Reference prior results. -->
If wrong: <!-- What would you try next if this is refuted? -->
"""

_RESULT_TEMPLATE = """\
Question: <!-- What were you testing? One sentence. -->
Finding: <!-- What happened? Plain English for the stated audience. -->
Implication: <!-- What does this change about the project? -->
Details: <!-- Metrics, config, raw numbers for those who want depth. -->
"""

_METHOD_TEMPLATE = """\
Approach: <!-- What are you doing and how? -->
Differs from prior work: <!-- What's new here? -->
Limitations: <!-- What won't this tell you? -->
"""


def generate_templates(store_path: str | Path) -> None:
    """Write claim templates to .resdag/templates/."""
    tpl_dir = Path(store_path) / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    for name, content in [
        ("hypothesis.md", _HYPOTHESIS_TEMPLATE),
        ("result.md", _RESULT_TEMPLATE),
        ("method.md", _METHOD_TEMPLATE),
    ]:
        dest = tpl_dir / name
        if not dest.exists():
            dest.write_text(content)


# ---------------------------------------------------------------------------
# /claim slash command
# ---------------------------------------------------------------------------

_CLAIM_COMMAND = """\
Commit structured research claims using the hypothesis-first workflow.

You are authoring claims for a ResDAG store — a content-addressed DAG of
research assertions.  Every result must link to a hypothesis.  Every claim
must use the template structure and canonical vocabulary.

---

## Step 0 — Read project context

Read these three files before doing anything else:

| File | Contains |
|------|----------|
| `.resdag/profile.json` | mode, **audience**, validation rules |
| `.resdag/vocabulary.json` | canonical domain tags and aliases |
| `.resdag/templates/result.md` | result claim structure |
| `.resdag/templates/hypothesis.md` | hypothesis claim structure |

The **audience** field is critical — write every claim so that someone
matching this description can understand it without project context.

## Step 1 — Assess the session

Determine what was accomplished:
- Look at recent git commits and diffs in this session.
- Review the conversation history for key findings.
- Identify evidence files produced (data, logs, configs).

Summarize the main finding in one sentence — this becomes the Finding line.

## Step 2 — Choose domain tags

Select tags from `.resdag/vocabulary.json` (canonical tags only).
If unsure, check existing claims for conventions:

```bash
lab threads --open
lab audit --json
```

## Step 3 — Find or create a hypothesis

Run `lab threads --open` to see existing open hypotheses.

**If an open hypothesis covers this work** → note its CID for Step 5.

**If no hypothesis exists** → create one now.  Use the template from
`.resdag/templates/hypothesis.md`:

```
Prediction: <what you expected to happen>
Rationale: <why you expected this — reference prior results if any>
If wrong: <what you would try next if refuted>
```

To find related claims for parent links:

```bash
lab hypothesize "<hypothesis text>" -d <domain> --suggest-parents
```

Review the suggested parents.  If any are relevant, add `-p <cid>`.
Commit the hypothesis:

```bash
lab hypothesize "<hypothesis text>" -d <domain> [-p <parent_cid>]
```

Note the returned CID (first 12 characters shown).

## Step 4 — Structure the result

Use the template from `.resdag/templates/result.md`:

```
Question: <what were you testing? One sentence.>
Finding: <what happened? Plain English for the stated audience.>
Implication: <what does this change about the project?>
Details: <metrics, config, raw numbers for those who want depth.>
```

**Writing for the audience**: if profile.json says the audience is
"ML researchers", write the Finding so an ML researcher gets it without
reading your codebase.  Put implementation specifics in Details.

## Step 5 — Show proposed claims for confirmation

Before committing, present to the user:

1. **Hypothesis** (if newly created): full text, domain tags, parent links
2. **Result**: full text, domain tags, hypothesis CID, evidence files
3. **Parent suggestions**: run `--suggest-parents` and list relevant matches

Ask: "Ready to commit these claims? [y/n]"

Do NOT commit until the user confirms.

## Step 6 — Commit the result

```bash
lab execute "<result text>" \
  -h <hypothesis_cid> \
  -d <domain> \
  [-e <evidence_file>] \
  [-p <additional_parent_cid>]
```

If evidence files exist (data, logs, configs from this session), attach
them with `-e`.  Multiple `-e` flags for multiple files.

## Step 7 — Offer to interpret and branch

After the result is committed, ask:

> Should I commit an interpretation?
>
> - **Confirmed** — the hypothesis held
> - **Refuted** — the hypothesis was wrong
> - **Branch** — new hypothesis based on this finding
> - **Skip** — no interpretation needed now

If the user chooses **Confirmed**:
```bash
lab interpret "<interpretation text>" <result_cid> --confirmed -d <domain>
```

If the user chooses **Refuted**:
```bash
lab interpret "<interpretation text>" <result_cid> --refuted -d <domain>
```

If the user chooses **Branch** (new hypothesis from the interpretation):
```bash
lab branch "<new hypothesis text>" <interpretation_cid> -d <domain>
```

---

## Quick reference

| Command | Purpose |
|---------|---------|
| `lab hypothesize "<text>" -d <tag>` | Declare a hypothesis |
| `lab execute "<text>" -h <cid> -d <tag> -e <file>` | Record a result |
| `lab interpret "<text>" <result_cid> --confirmed` | Confirm hypothesis |
| `lab interpret "<text>" <result_cid> --refuted` | Refute hypothesis |
| `lab branch "<text>" <parent_cid> -d <tag>` | Fork new direction |
| `lab note "<text>"` | Quick note (no structure, not in strict mode) |
| `lab threads --open` | List unresolved hypotheses |
| `lab audit --json` | DAG health metrics |
| `--suggest-parents` | Show related claims (add to any commit command) |
| `--no-validate` | Override validation errors |
"""


def generate_claim_command(project_root: str | Path) -> None:
    """Write .claude/commands/claim.md."""
    dest = Path(project_root) / ".claude" / "commands" / "claim.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text(_CLAIM_COMMAND)


# ---------------------------------------------------------------------------
# /retrofit slash command
# ---------------------------------------------------------------------------

_RETROFIT_COMMAND = """\
Restructure existing claims in the DAG to follow the hypothesis-first workflow.

You are analyzing an existing ResDAG store and proposing structural improvements:
inserting missing hypotheses, restructuring unstructured claims, and linking
orphans.  This is a batch operation — read everything first, plan all changes,
then commit only after user approval.

**Idempotency rule**: only propose changes for claims that are NOT already
structured (no Question/Finding/Implication sections) and NOT already linked
to a hypothesis parent.  If the store is fully retrofitted, report
"nothing to do" and exit.

---

## Step 0 — Read project context

Read these files before doing anything else:

| File | Contains |
|------|----------|
| `.resdag/profile.json` | mode, **audience**, validation rules |
| `.resdag/vocabulary.json` | canonical domain tags and aliases |
| `.resdag/templates/result.md` | result claim structure |
| `.resdag/templates/hypothesis.md` | hypothesis claim structure |

The **audience** field is critical — every restructured claim must be
understandable by someone matching this description.

## Step 1 — Snapshot current DAG health

Run these commands to capture the "before" state:

```bash
lab audit --json
```

Save the output — you will show before/after comparison in Step 6.

Also run:

```bash
lab threads
lab threads --open
```

Note which hypotheses already exist and which threads are established.

## Step 2 — Scan all claims

```bash
res log
res log --orphans
```

Read each claim with `res show <cid>` as needed.  Classify every claim into
one of these categories:

| Category | Criteria | Action needed |
|----------|----------|---------------|
| **Already structured** | Has Question/Finding/Implication or Prediction/Rationale sections | Skip (idempotent) |
| **Has hypothesis parent** | A hypothesis claim exists in its ancestor chain | Skip restructuring, may still need text rewrite |
| **Orphan** | No parents, type is not hypothesis | Needs parent link |
| **Unstructured result** | Result/replication without template sections | Needs restructuring |
| **Chain start** | First claim in a linear run on a new topic | Needs hypothesis insertion |
| **Topic transition** | Claim where domain tags or subject changes within a chain | Needs hypothesis insertion at this point |

## Step 3 — Identify implicit hypotheses

Walk the DAG looking for natural hypothesis insertion points:

1. **Chain starts**: the first claim in a linear sequence (no siblings) that
   begins a recognizable line of inquiry.  What was the researcher testing?
2. **Topic transitions**: within a chain, where the domain tags shift or the
   claim text introduces a new question.
3. **Orphan clusters**: groups of orphaned claims on the same topic — they
   likely belong to the same implicit hypothesis.

For each insertion point, draft a hypothesis using the template:

```
Prediction: <what the researcher was implicitly testing>
Rationale: <why — inferred from the claims that follow>
If wrong: <what alternative the subsequent claims suggest>
```

Write for the **audience** specified in profile.json.

## Step 4 — Propose restructured claims

For each unstructured claim, draft a replacement using the result template:

```
Question: <what was being tested? One sentence.>
Finding: <what happened? Plain English for the stated audience.>
Implication: <what does this change about the project?>
Details: <metrics, config, raw numbers — preserve all data from the original.>
```

Rules:
- **Preserve all information** from the original claim text — restructuring
  must not lose data.  Move specifics to Details if needed.
- **Write for the audience** in profile.json.
- **Use canonical vocabulary** from vocabulary.json for domain tags.
- The restructured claim gets the same domain tags as the original (normalized
  through vocabulary) plus the hypothesis as parent.

## Step 5 — Propose orphan fixes

For each orphan claim, determine the best parent:

1. Check if a hypothesis from Step 3 covers this claim → link to it.
2. If no hypothesis fits, run `--suggest-parents` to find related claims:
   ```bash
   lab note "orphan claim text here" --suggest-parents
   ```
   (Use the suggestion output without actually committing.)
3. If a clear parent exists in the DAG, note the link.
4. If no parent is appropriate, the orphan may be a legitimate root — flag
   it as intentional and skip.

## Step 6 — Present the retrofit plan

Show the user a complete plan before committing anything:

### Before / After DAG Health

| Metric | Before | After (projected) |
|--------|--------|--------------------|
| Hypothesis coverage | X% | Y% |
| Orphan rate | X% | Y% |
| Branch ratio | X | Y |
| Max linear run | X | Y |

### Proposed Changes

For each change, show:

1. **New hypotheses** (N total):
   - For each: full text, domain tags, proposed children
2. **Restructured claims** (N total):
   - For each: original CID, original text (abbreviated), new text, parent links
3. **Orphan fixes** (N total):
   - For each: orphan CID, proposed parent CID, reason
4. **Skipped** (N total):
   - Claims already structured or already linked to hypotheses

Ask: "Apply this retrofit plan? [y/n]"

Do NOT commit anything until the user confirms.

## Step 7 — Apply the plan

On user approval, execute in this order:

### 7a — Commit new hypotheses

```bash
lab hypothesize "<hypothesis text>" -d <domain> [-p <parent_cid>]
```

Note each returned CID — you need them for the next steps.

### 7b — Commit restructured claims

For each unstructured claim being replaced:

```bash
lab execute "<restructured text>" -h <hypothesis_cid> -d <domain> [-p <additional_parent>]
```

Then supersede the original:

```bash
res supersede <original_cid> <new_cid>
```

This creates a supersession node linking old to new, so the original is marked
SUPERSEDED but never deleted (append-only protocol).

### 7c — Fix orphans

For orphans that just need a parent link (text is fine), commit a new version
with the parent and supersede the old:

```bash
lab execute "<same text>" -d <domain> -p <parent_cid> [-h <hypothesis_cid>]
res supersede <orphan_cid> <new_cid>
```

### 7d — Verify the result

```bash
lab audit --json
```

Compare with the Step 1 snapshot.  Report the improvements.

---

## Quick reference

| Command | Purpose |
|---------|---------|
| `res log` | List all claims |
| `res log --orphans` | Find parentless non-hypothesis claims |
| `res log --active` | Exclude superseded claims |
| `res show <cid>` | Display a claim with context |
| `res lineage <cid>` | Show ancestor/descendant tree |
| `res supersede <old> <new>` | Mark old claim as superseded by new |
| `lab hypothesize "<text>" -d <tag>` | Create a hypothesis |
| `lab execute "<text>" -h <cid> -d <tag>` | Create a structured result |
| `lab threads` | List all research threads |
| `lab threads --open` | List unresolved hypotheses |
| `lab audit --json` | DAG health metrics (machine-readable) |
| `--suggest-parents` | Show related claims (add to any commit command) |
| `--no-validate` | Override validation errors |
"""


def generate_retrofit_command(project_root: str | Path) -> None:
    """Write .claude/commands/retrofit.md."""
    dest = Path(project_root) / ".claude" / "commands" / "retrofit.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text(_RETROFIT_COMMAND)


# ---------------------------------------------------------------------------
# /research slash command
# ---------------------------------------------------------------------------

_RESEARCH_COMMAND = """\
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
   lab execute "<Question/Finding/Implication/Details>" \
     -h <hypothesis_cid> \
     -d <domain> \
     [-e <evidence_file>] \
     [-p <additional_parent_cid>] \
     --suggest-parents
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
"""


def generate_research_command(project_root: str | Path) -> None:
    """Write .claude/commands/research.md."""
    dest = Path(project_root) / ".claude" / "commands" / "research.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text(_RESEARCH_COMMAND)


# ---------------------------------------------------------------------------
# Critic (strict only)
# ---------------------------------------------------------------------------

_CLAIMS_REVIEW_CRITIC = """\
Review all claims being committed for structural quality.

Check each claim against the project profile (.resdag/profile.json):

1. **Hypothesis parent**: Every result claim must link to a hypothesis via --hypothesis.
   Fail if a result has no hypothesis parent.

2. **Claim structure**: Claim text must contain the template sections
   (Question/Finding/Implication for results, Prediction/Rationale/If wrong for hypotheses).
   Fail if sections are missing.

3. **Vocabulary**: All domain tags must be in .resdag/vocabulary.json.
   Fail on unknown tags.

4. **Audience**: Claims must be understandable to the stated audience without project context.
   Warn if claim text contains unexplained jargon or acronyms.

Output JSON: {"pass": true/false, "issues": [...], "severity": "critical|warning"}
"""


def generate_critic(project_root: str | Path) -> None:
    """Write .critics/claims.review.critic.md."""
    dest = Path(project_root) / ".critics" / "claims.review.critic.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_text(_CLAIMS_REVIEW_CRITIC)


# ---------------------------------------------------------------------------
# CLAUDE.md fragment
# ---------------------------------------------------------------------------

_CLAUDE_HEADER = "## Research Claims (reslab)"

_EXPLORATORY_FRAGMENT = """\
## Research Claims (reslab)
Commit findings with `lab execute "..." -d domain -e data.json`.
Quick notes: `lab note "..."`.
Domain vocabulary: {tags}.
"""

_DISCIPLINED_FRAGMENT = """\
## Research Claims (reslab)
Use `/claim` to commit structured research claims.
This command handles the hypothesis → result → interpret → branch workflow.

For quick notes that don't need structure: `lab note "..."`.

Claims should be understandable to: {audience}.
Domain vocabulary: {tags}.
"""

_STRICT_FRAGMENT = """\
## Research Claims (reslab)
Use `/claim` to commit all research claims. This is required — do not use
raw `lab execute` without the hypothesis-first workflow.

All claims must follow templates in `.resdag/templates/`.
All claims must be understandable to: {audience}.
Domain vocabulary: {tags}. Unknown tags are rejected.
"""


def generate_claude_fragment(
    mode: ProfileMode,
    audience: str,
    canonical_tags: Sequence[str],
) -> str:
    """Return the CLAUDE.md fragment for the given mode."""
    tags_str = ", ".join(canonical_tags) if canonical_tags else "(none configured)"
    audience_str = audience or "(not specified)"

    if mode is ProfileMode.EXPLORATORY:
        return _EXPLORATORY_FRAGMENT.format(tags=tags_str)
    if mode is ProfileMode.DISCIPLINED:
        return _DISCIPLINED_FRAGMENT.format(audience=audience_str, tags=tags_str)
    return _STRICT_FRAGMENT.format(audience=audience_str, tags=tags_str)


def update_claude_md(project_root: str | Path, fragment: str) -> None:
    """Append or replace the reslab section in CLAUDE.md."""
    claude_md = Path(project_root) / "CLAUDE.md"

    if not claude_md.exists():
        claude_md.write_text(fragment)
        return

    content = claude_md.read_text()

    # Replace existing section if present
    if _CLAUDE_HEADER in content:
        # Find start of our section
        start = content.index(_CLAUDE_HEADER)
        # Find next ## header after ours, or end of file
        rest = content[start + len(_CLAUDE_HEADER):]
        next_header = rest.find("\n## ")
        if next_header == -1:
            end = len(content)
        else:
            end = start + len(_CLAUDE_HEADER) + next_header
        content = content[:start].rstrip() + "\n\n" + fragment.rstrip() + "\n" + content[end:]
    else:
        content = content.rstrip() + "\n\n" + fragment.rstrip() + "\n"

    claude_md.write_text(content)


# ---------------------------------------------------------------------------
# DAG health summary (for init on existing stores)
# ---------------------------------------------------------------------------

def dag_health_summary(store) -> dict:
    """Compute basic DAG health metrics from a store.

    Returns dict with: total_claims, hypothesis_count, orphan_count,
    structure_coverage (fraction of results with template sections).
    """
    from resdag.claim import ClaimType

    cids = store.list_cids()
    total = len(cids)
    if total == 0:
        return {
            "total_claims": 0,
            "hypothesis_count": 0,
            "orphan_count": 0,
            "orphan_rate": 0.0,
            "structure_coverage": 0.0,
        }

    hypotheses = 0
    orphans = 0
    results_total = 0
    results_structured = 0
    section_markers = ("Question:", "Finding:", "Prediction:", "Approach:")

    for cid in cids:
        claim = store.get(cid)
        if claim.type == ClaimType.HYPOTHESIS:
            hypotheses += 1
        # Orphan: no parents, but not a hypothesis (hypotheses can be roots)
        if not claim.parents and claim.type != ClaimType.HYPOTHESIS:
            orphans += 1
        if claim.type == ClaimType.RESULT:
            results_total += 1
            if any(m in claim.claim for m in section_markers):
                results_structured += 1

    return {
        "total_claims": total,
        "hypothesis_count": hypotheses,
        "orphan_count": orphans,
        "orphan_rate": round(orphans / total, 2) if total else 0.0,
        "structure_coverage": round(results_structured / results_total, 2) if results_total else 0.0,
    }


# ---------------------------------------------------------------------------
# High-level init
# ---------------------------------------------------------------------------

def init_profile(
    store_path: str | Path,
    project_root: str | Path,
    mode: ProfileMode,
    project: str = "",
    audience: str = "",
    canonical_tags: Sequence[str] = (),
) -> Profile:
    """Generate all artifacts for the given mode. Returns the Profile."""
    from reslab.vocabulary import default_vocabulary, load_vocabulary, save_vocabulary

    rules = mode_defaults(mode)
    profile = Profile(
        mode=mode.value,
        project=project,
        audience=audience,
        validation=rules,
    )
    save_profile(profile, store_path)

    # Vocabulary — create if not present
    vocab = load_vocabulary(store_path)
    if vocab is None:
        vocab = default_vocabulary()
        save_vocabulary(vocab, store_path)

    tags = canonical_tags or vocab.canonical_tags()

    # Templates (disciplined + strict)
    if mode in (ProfileMode.DISCIPLINED, ProfileMode.STRICT):
        generate_templates(store_path)
        generate_claim_command(project_root)
        generate_retrofit_command(project_root)
        generate_research_command(project_root)

    # Critic (strict only)
    if mode is ProfileMode.STRICT:
        generate_critic(project_root)

    # CLAUDE.md fragment (all modes)
    fragment = generate_claude_fragment(mode, audience, tags)
    update_claude_md(project_root, fragment)

    return profile
