Prepare handoff notes for the next session.

1. Read `features.json` — confirm exactly 1 P0 is set. If not, ask which item should be P0 and update `features.json`.
2. Append a dated entry to `claude-progress.txt` summarizing:
   - What was accomplished this session
   - Current state of the P0 item
   - Any blockers or context the next session needs
   - What the P0 is for next session
3. Verify the session maintained:
   - Protocol simplicity (no unnecessary complexity added to base protocol)
   - Content-addressing consistency (all objects identified by CID)
   - Layer separation (protocol vs. storage vs. tools vs. applications)
4. Show the handoff notes for confirmation.
