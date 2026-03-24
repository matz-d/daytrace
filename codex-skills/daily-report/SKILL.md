---
name: daily-report
description: Generate a DayTrace daily report from Codex using local activity logs and the shared DayTrace scripts. Use when the user asks for a self report, shared report, daily recap, or a date-first report in Codex.
---

# Daily Report

Codex wrapper for the DayTrace `daily-report` skill.

The real implementation is shared with the plugin version:

- Commands run from `scripts/`
- The full contract lives in `upstream-skill.md`

Use this skill when the user wants a date-first daily report in Codex.

## What To Run

Default:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/daily-report/scripts/daily_report_projection.py" --date today --all-sessions
```

With a workspace filter:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/daily-report/scripts/daily_report_projection.py" --date today --all-sessions --workspace /absolute/path/to/workspace
```

## Notes

- Keep user-facing responses in Japanese unless asked otherwise.
- Treat `--all-sessions` as broader observation, not as a global-only output mode.
- For exact mode handling, escalation rules, and output policy, follow `upstream-skill.md`.
