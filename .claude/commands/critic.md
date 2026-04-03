Run codebase critics on staged changes.

Arguments: `$ARGUMENTS` (optional — specific critic name, e.g., `protocol`, `claims`, `simplicity`)

1. Get staged diff with `git diff --cached`. If nothing staged, use `git diff`.
2. If `$ARGUMENTS` is provided, run only `.critics/$ARGUMENTS.critic.md`. Otherwise run all `.critics/*.critic.md`.
3. For each critic: feed the diff + critic prompt, collect JSON output.
4. Report results:

| Critic | Pass | Issues | Severity |

5. If any critical issues, list them with fix suggestions.
