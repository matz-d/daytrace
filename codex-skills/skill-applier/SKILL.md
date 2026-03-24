---
name: skill-applier
description: Apply a DayTrace proposal from Codex by turning a selected skill-miner candidate into a concrete next step, scaffold, hook, agent, or CLAUDE.md-style rule update. Use when the user asks to apply a proposal or turn a mined pattern into an artifact.
---

# Skill Applier

Codex wrapper for the DayTrace `skill-applier` skill.

The real implementation is shared with the plugin version:

- Commands run from `scripts/`
- The full contract lives in `upstream-skill.md`
- Detailed apply-path guidance lives in `references/`

## What To Run

To inspect only the selected evidence:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/skill-applier/scripts/skill_miner_detail.py" --refs "<session_ref_1>" "<session_ref_2>"
```

To write back a user decision:

```bash
SESSION_TMP="${SESSION_TMP:-$(mktemp -d "${TMPDIR:-/tmp}/daytrace-session-XXXXXX")}"
python3 "${CODEX_HOME:-$HOME/.codex}/skills/skill-applier/scripts/skill_miner_decision.py" --proposal-file "$SESSION_TMP/proposal.json" --candidate-index 1 --decision adopt --completion-state completed --output-file "$SESSION_TMP/user-decision.json"
python3 "${CODEX_HOME:-$HOME/.codex}/skills/skill-applier/scripts/skill_miner_proposal.py" --prepare-file "$SESSION_TMP/prepare.json" --judge-file "$SESSION_TMP/judge.json" --decision-log-path ~/.daytrace/skill-miner-decisions.jsonl --skill-creator-handoff-dir ~/.daytrace/skill-creator-handoffs --user-decision-file "$SESSION_TMP/user-decision.json" > "$SESSION_TMP/proposal-final.json"
```

## Notes

- Follow `upstream-skill.md` for dispatch rules and completion semantics.
- This wrapper shares the same apply paths as the plugin contract; environment-specific destinations still come from that upstream contract.
- Use `references/` when you need the detailed hook, agent, or scaffold rules.
