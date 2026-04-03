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

This creates a refutation node linking old to new, so the original is marked
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
