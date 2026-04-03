# ADR-001: Project Profiles and Init Modes

**Status:** Proposed  
**Date:** 2026-04-03  
**Context:** Real-world usage of reslab on a research project (72 claims) revealed two fundamental problems that tag normalization and visualization improvements cannot fix:

1. **Linear DAG** — 3 branch points across 74 claims, 0 hypotheses committed. The DAG is a linked list because claims are dumped retrospectively, not committed as part of a hypothesis-driven workflow.
2. **Opaque content** — Claims are machine-generated session summaries unreadable to anyone outside the project. No structure, no audience awareness, no context.

Both problems stem from the same root cause: reslab has no opinion about *how* claims should be authored. It stores whatever you give it. The fix must happen at authoring time, and the authoring agent (usually Claude Code) must be guided by the tool, not by user discipline.

## Decision

`lab init` generates a **project profile** — a bundle of config, templates, validation rules, and agent integration artifacts that shapes every future commit. The profile is configured by a single `--mode` flag that sets coherent defaults.

### Modes

#### `exploratory` — fast iteration, minimal structure

For solo researchers who would otherwise use a text file. Any structure is a win. Zero friction.

- **Validation:** vocabulary warnings only. No hypothesis or structure enforcement.
- **Templates:** Not generated. Free-form claim text.
- **Agent integration:** CLAUDE.md fragment with basic `lab execute` / `lab note` instructions.
- **`lab note`:** Enabled, primary commit path.
- **DAG expectation:** Mostly linear. Branches where the researcher naturally hypothesizes.

#### `disciplined` — hypothesis-first encouraged, templates available

The sweet spot for a solo researcher or small team that wants the DAG to mean something. The slash command makes the structured path easier than the unstructured path.

- **Validation:** Warn on missing hypothesis parent. Warn on unstructured claim text. Warn on unknown vocabulary tags.
- **Templates:** Generated (`hypothesis.md`, `result.md`, `method.md`). Surfaced to the agent via the slash command, not enforced by code.
- **Agent integration:** CLAUDE.md fragment + `/claim` slash command. The slash command drives the hypothesis → result → interpret → branch workflow.
- **`lab note`:** Enabled for quick observations, no warnings.
- **DAG expectation:** Hypothesis → result → interpretation → branch for major experiments. Quick notes for minor findings.

#### `strict` — hypothesis-first required, templates enforced

For multi-team collaboration, audit trails, or publication-quality DAGs. Every claim must be comprehensible to the stated audience.

- **Validation:** Require hypothesis parent on results. Require template structure. Reject unknown vocabulary tags. Log `--no-validate` usage as profile violations.
- **Templates:** Generated and enforced. Claim text must contain the template sections.
- **Agent integration:** CLAUDE.md fragment + `/claim` slash command + `.critics/claims.review.critic.md` that blocks commit on unstructured claims.
- **`lab note`:** Disabled. Use `lab execute` with proper structure.
- **DAG expectation:** Every result has a hypothesis. Every hypothesis has an interpretation. Publishable narrative structure.

### Generated artifacts

`lab init --mode <mode>` generates:

```
.resdag/
├── profile.json           # mode, audience, validation rules
├── vocabulary.json        # canonical domain tags (all modes)
└── templates/             # claim templates (disciplined + strict)
    ├── hypothesis.md
    ├── result.md
    └── method.md
```

Agent integration (disciplined + strict):
```
.claude/commands/
└── claim.md               # /claim slash command
```

CLAUDE.md fragment appended (all modes).

### profile.json schema

```json
{
  "mode": "exploratory | disciplined | strict",
  "project": "Project name",
  "audience": "Who should understand claims without project context",
  "validation": {
    "hypothesis_parent": "off | warn | require",
    "claim_structure": "off | warn | require",
    "vocabulary": "off | warn | require"
  }
}
```

Modes are presets that populate `validation`. Users can edit `profile.json` to mix and match (e.g., `hypothesis_parent: require` + `claim_structure: warn`).

### Claim templates

Templates define the expected structure for each claim type. They are markdown files with section headers that the agent fills in.

**`templates/result.md`:**
```markdown
Question: <!-- What were you testing? One sentence. -->
Finding: <!-- What happened? Plain English for the stated audience. -->
Implication: <!-- What does this change about the project? -->
Details: <!-- Metrics, config, raw numbers for those who want depth. -->
```

**`templates/hypothesis.md`:**
```markdown
Prediction: <!-- What do you expect to happen? -->
Rationale: <!-- Why do you expect this? Reference prior results. -->
If wrong: <!-- What would you try next if this is refuted? -->
```

**`templates/method.md`:**
```markdown
Approach: <!-- What are you doing and how? -->
Differs from prior work: <!-- What's new here? -->
Limitations: <!-- What won't this tell you? -->
```

Templates are conventions, not schemas. The renderer parses section headers when present and uses them for structured display. Unstructured text still renders correctly (whole text as body).

### /claim slash command

The `/claim` command (`.claude/commands/claim.md`) is the primary agent integration point. When invoked, it:

1. Reads `.resdag/profile.json` for audience and validation rules.
2. Reads `.resdag/templates/` for the claim template structure.
3. Reads `.resdag/vocabulary.json` for canonical domain tags.
4. Determines what was accomplished in the current session.
5. Checks whether a hypothesis was committed for this work.
   - If not, generates one and commits it FIRST via `lab hypothesize`.
6. Structures the result using the appropriate template.
7. Suggests parent links from existing claims (via TF-IDF or context).
8. Shows the proposed claims (hypothesis + result) for user confirmation.
9. Commits via `lab execute --hypothesis <cid> ...`.
10. Offers to interpret and branch: "Should I commit an interpretation and branch to the next hypothesis?"

The slash command makes the structured path the *easy* path — one command drives the full workflow.

### CLAUDE.md fragment

Appended by `lab init`. Content varies by mode.

**Exploratory:**
```markdown
## Research Claims (reslab)
Commit findings with `lab execute "..." -d domain -e data.json`.
Quick notes: `lab note "..."`.
Domain vocabulary: {canonical tags}.
```

**Disciplined:**
```markdown
## Research Claims (reslab)
Use `/claim` to commit structured research claims.
This command handles the hypothesis → result → interpret → branch workflow.

For quick notes that don't need structure: `lab note "..."`.

Claims should be understandable to: {audience}.
Domain vocabulary: {canonical tags}.
```

**Strict:**
```markdown
## Research Claims (reslab)
Use `/claim` to commit all research claims. This is required — do not use
raw `lab execute` without the hypothesis-first workflow.

All claims must follow templates in `.resdag/templates/`.
All claims must be understandable to: {audience}.
Domain vocabulary: {canonical tags}. Unknown tags are rejected.
```

### Validation layer

`lab execute`, `lab hypothesize`, etc. read `.resdag/profile.json` at commit time and apply validation rules:

- **`off`**: No check performed.
- **`warn`**: Print warning to stderr, commit proceeds.
- **`require`**: Print error, command fails. `--no-validate` overrides (logged).

Validation is applied in the CLI layer (like vocabulary normalization), not in the workflow functions. The Python API stays unconstrained — validation is a user-facing concern.

### Retrospective use: /retrofit

`lab init` configures future behavior. `/retrofit` fixes the past. Both are generated by init (disciplined + strict modes).

The problem: every real user has existing data. Nobody installs reslab on day one. A typical store might have 74 claims, 0 hypotheses, 0 structured claims, 15 orphans. Without a retrofit path, reslab only helps new projects.

**Two-layer approach:**

**Layer 1: Render-time heuristics (no LLM, no DAG mutations, immediate)**

Built into the renderer. Works automatically on any store with a profile:
- Title extraction: `[Session 62] Inference loop validated: ...` → title is `Inference loop validated`
- Implicit thread inference: walk linear chains, group by domain overlap, display as thread navigation
- DAG health badge: branch ratio, hypothesis coverage, orphan rate on the site index

These make existing stores look better the moment `lab init` runs. No agent needed.

**Layer 2: Agent-assisted retrofit (/retrofit slash command, one-time)**

The `/retrofit` slash command (`.claude/commands/retrofit.md`) drives a full restructuring:

1. Agent reads all claims in the store.
2. Identifies implicit hypotheses: chain starts, topic transitions, branch points.
3. Proposes hypothesis claims with template structure (Prediction/Rationale/If wrong).
4. Proposes restructured claims using result template (Question/Finding/Implication/Details), rewritten for the audience in profile.json.
5. Identifies orphans, suggests parent links via content similarity.
6. Presents full plan with before/after DAG health metrics.
7. On user approval, commits: new hypotheses, structured claim replacements (superseding originals), parent links for orphans.

The agent provides the intelligence (rewriting claims, inferring hypotheses). reslab provides the framework (templates, vocabulary, profile, commit commands).

`/retrofit` is idempotent — re-running on a partially retrofitted store only proposes changes for remaining unstructured claims. Running on a fully retrofitted store reports "nothing to do."

**Init integration:**

When `lab init` detects an existing store, it reports the current state and mentions `/retrofit`:

```
Found existing store: 74 claims, 0 hypotheses, 15 orphans.

Render-time improvements applied automatically:
  ✓ Title extraction from [Session N] prefixes
  ✓ Thread inference from chain structure
  ✓ DAG health badge on site

For deeper restructuring, run /retrofit.
```

### Mode transitions

`lab config set mode strict` re-generates profile.json, templates, and agent artifacts. Existing claims are unaffected — modes only change future behavior. Missing templates are created. Existing templates are not overwritten (user may have customized them). CLAUDE.md fragment is updated in place (identified by `## Research Claims (reslab)` header).

### Interaction with existing features

- **`domain_vocabulary`** (done): Vocabulary is generated at init for all modes. Validation level set by mode.
- **`vocabulary_hierarchy`** (planned): Subtag/alias distinction works within the profile system. No conflict.
- **`structured_claims`** (planned): Subsumed by this ADR. Claim templates replace the title/body convention with a richer structure. The renderer parses template sections.
- **`agentic_commit_harness`** (planned): The `/claim` slash command IS the harness for the agent case. The Python API (`reslab.harness.propose()`) remains useful for programmatic integration.
- **`vocab_bootstrap`** (planned): `lab vocab init` works alongside `lab init`. Can be called separately to analyze and suggest vocabulary for an existing store.

## Consequences

**Positive:**
- One decision at init time shapes all future behavior.
- The agent (Claude Code) is guided by generated artifacts, not user discipline.
- Progressive: start exploratory, tighten to disciplined or strict as the project matures.
- DAG branching emerges naturally from hypothesis-first workflow.
- Claim readability improves from template structure + audience awareness.

**Negative:**
- More generated files in the project. `.resdag/templates/`, `.claude/commands/claim.md`, CLAUDE.md fragment.
- Mode presets may not fit all projects. Users must know to edit `profile.json`.
- The `/claim` slash command is Claude Code-specific. Other agents need different integration.
- `strict` mode friction may drive users to `--no-validate` escape hatch.

**Risks:**
- If the `/claim` slash command is poorly designed, agents will avoid it and use raw `lab execute`.
- If templates are too rigid, claims become formulaic and lose nuance.
- If validation warnings are too noisy, they become invisible.
