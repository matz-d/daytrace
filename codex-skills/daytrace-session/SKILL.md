---
name: daytrace-session
description: Run DayTrace from Codex to collect local activity, generate a daily report, optionally draft a post, and extract recurring improvement proposals from Claude/Codex history. Use when the user asks for a daily review, day summary, "daytrace", or wants the full DayTrace session in Codex.
---

# DayTrace Session

Codex wrapper for the DayTrace orchestration flow.

Use this skill when the user wants the DayTrace end-to-end flow from Codex. The implementation lives in the linked `scripts/` directory under this skill, so commands should target:

```bash
${CODEX_HOME:-$HOME/.codex}/skills/daytrace-session/scripts
```

## What To Run

Default flow:

1. Phase 1 data collection:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/daytrace-session/scripts/daily_report_projection.py" --date today --all-sessions
```

2. Reuse the returned JSON to summarize source coverage and generate the daily report.

3. If post-draft conditions are met, run:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/daytrace-session/scripts/post_draft_projection.py" --date today --all-sessions
```

4. Run pattern mining with a shared decision log:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/daytrace-session/scripts/skill_miner_prepare.py" --input-source auto --store-path ~/.daytrace/daytrace.sqlite3 --decision-log-path ~/.daytrace/skill-miner-decisions.jsonl --all-sessions
```

If Phase 1 returned `report_date`, add `--reference-date <report_date>` to the pattern-mining command so the report day and observation window stay aligned.

## Output Rules

- Respond in Japanese unless the user asks otherwise.
- Do not show `[DayTrace]` prefixes or raw phase-number metadata in chat.
- Keep the user-facing flow short and status-oriented: source summary, digest, report, optional post draft, proposal summary, session summary.
- Treat `--all-sessions` as broader observation, not as a signal to force global-only proposals.

## Paths And Artifacts

- Daily-report and post-draft artifacts are written under `~/.daytrace/output/<date>/` when the projection payload includes `output_dir`.
- Pattern-mining persistence should use the explicit paths above instead of relying on implicit defaults.
- Keep temporary proposal files in a session-specific temp directory, not a shared fixed `/tmp/*.json`.

## When You Need More Detail

- Full upstream orchestration contract: `upstream-session.md`
- Output/presentation rules: `output-polish.md`
