Read `features.json` and `claude-progress.txt`.

1. Find the single P0 item (priority 0). If none, find the highest priority `not_started` or `in_progress` item.
2. If multiple P0s exist, warn and ask which to work on.
3. Report:
   - Current phase
   - P0 item name, description, and acceptance criteria
   - Relevant test file
   - Last session's progress notes
4. Set the P0 item's status to `in_progress` in `features.json`.
5. Check environment:
   - Python 3.11+ available
   - Git initialized
   - `uv` available for package management
