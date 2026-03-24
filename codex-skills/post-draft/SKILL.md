---
name: post-draft
description: Generate a DayTrace narrative post draft from Codex using local activity logs and the shared DayTrace scripts. Use when the user asks for a blog draft, narrative recap, or a shareable writeup of the day from Codex.
---

# Post Draft

Codex wrapper for the DayTrace `post-draft` skill.

The real implementation is shared with the plugin version:

- Commands run from `scripts/`
- The full contract lives in `upstream-skill.md`
- Variant details and examples live in `references/`

Use this skill when the user wants a date-first narrative draft in Codex.

## What To Run

Default:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/post-draft/scripts/post_draft_projection.py" --date today --all-sessions
```

With a workspace filter:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/post-draft/scripts/post_draft_projection.py" --date today --all-sessions --workspace /absolute/path/to/workspace
```

## Notes

- Keep user-facing responses in Japanese unless asked otherwise.
- Follow `upstream-skill.md` for narrative policy, trigger conditions, and fallback rules.
- Use `references/` only when you need the deeper post-draft guidance.
