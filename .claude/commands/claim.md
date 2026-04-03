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
lab execute "<result text>"   -h <hypothesis_cid>   -d <domain>   [-e <evidence_file>]   [-p <additional_parent_cid>]
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
