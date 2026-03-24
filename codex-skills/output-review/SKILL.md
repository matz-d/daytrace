---
name: output-review
description: >
  Review DayTrace outputs (daily report, digest, post draft, proposals) against output-polish.md,
  detect UX gaps, and reflect P-plan items into plugin SKILL.md. Use when the user asks to review
  output, improve UX for end users, apply P7/P items, align SKILL.md with output spec, or confirm
  output quality. Dev-repo only: does not ship in the published plugin.
---

# Output Review

Codex skill for the **DayTrace development repository** only. The published `daytrace` plugin stays at five skills; this workflow lives under `codex-skills/output-review/`.

- **Full phases and rules:** `upstream-skill.md`
- **P-item criteria:** `references/p-plan-check.md`
- **§A violation patterns:** `references/violation-patterns.md`
- **Polish spec:** `docs/output-polish.md` (repository root)

When reading or editing plugin skills, use paths `plugins/daytrace/skills/<name>/SKILL.md`. Table paths in `p-plan-check.md` that start with `skills/` mean that suffix under `plugins/daytrace/`.
