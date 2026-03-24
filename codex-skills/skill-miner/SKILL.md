---
name: skill-miner
description: Extract recurring DayTrace patterns from Claude/Codex history in Codex and turn them into DayTrace proposals for CLAUDE.md, skills, hooks, or agents. Use when the user asks to mine repeated workflows, propose automations, or inspect recurring work habits.
---

# Skill Miner

Codex wrapper for the DayTrace `skill-miner` skill.

The real implementation is shared with the plugin version:

- Commands run from `scripts/`
- The full contract lives in `upstream-skill.md`
- Classification, proposal, and research details live in `references/`

## What To Run

Default:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/skill-miner/scripts/skill_miner_prepare.py" --input-source auto --store-path ~/.daytrace/daytrace.sqlite3 --decision-log-path ~/.daytrace/skill-miner-decisions.jsonl
```

Broader observation:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/skill-miner/scripts/skill_miner_prepare.py" --input-source auto --store-path ~/.daytrace/daytrace.sqlite3 --decision-log-path ~/.daytrace/skill-miner-decisions.jsonl --all-sessions
```

## Notes

- Keep responses compact and Japanese unless asked otherwise.
- Do not re-read raw history in the proposal phase when prepare/proposal contracts already provide the evidence path.
- Follow `upstream-skill.md` for the exact triage, research, and proposal flow.
