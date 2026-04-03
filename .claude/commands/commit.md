Run critics on staged changes, then commit if they pass.

1. Run `git diff --cached` to see staged changes. If nothing staged, run `git diff` and suggest what to stage.
2. For each `.critics/*.critic.md` file, feed the staged diff to the critic prompt and evaluate.
3. If any critic returns `severity: "critical"`, **block the commit** and show the issues.
4. If all pass (or only warnings), proceed:
   - Generate a concise commit message from the diff
   - Prefix with phase tag: `[protocol]`, `[storage]`, `[tools]`, `[export]`, `[infra]`
   - Show the message for confirmation
   - Commit
