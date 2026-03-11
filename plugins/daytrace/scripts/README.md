# DayTrace Source CLI Contract

`scripts/` contains all CLI scripts for DayTrace, organized into two groups:

**共通 CLI** — 全 skill が使う:

| Script | 役割 |
|--------|------|
| `aggregate.py` | 5 source を統合し中間 JSON を返すオーケストレーター |
| `common.py` | 共有ユーティリティ（JSON I/O, エラー処理, CLI 引数） |
| `git_history.py` | Git commit 履歴の source CLI |
| `claude_history.py` | Claude 会話履歴の source CLI |
| `codex_history.py` | Codex 会話履歴の source CLI |
| `chrome_history.py` | Chrome 閲覧履歴の source CLI |
| `workspace_file_activity.py` | ファイル変更検出の source CLI |
| `sources.json` | source レジストリ（preflight, timeout, confidence_category） |

**skill-miner 専用 CLI** — `/skill-miner` skill だけが使う:

| Script | 役割 |
|--------|------|
| `skill_miner_prepare.py` | 全セッションを圧縮 candidate view に変換 |
| `skill_miner_detail.py` | 選択候補の session_ref から raw detail を再取得 |
| `skill_miner_research_judge.py` | 追加調査後の structured conclusion |
| `skill_miner_proposal.py` | prepare + judge → 最終 proposal 組み立て |
| `skill_miner_common.py` | skill-miner 共有ユーティリティ |

## Common output contract

Each source CLI must print one JSON object to stdout.

Success shape:

```json
{
  "status": "success",
  "source": "git-history",
  "events": [
    {
      "source": "git-history",
      "timestamp": "2026-03-09T14:30:00+09:00",
      "type": "commit",
      "summary": "Implement source CLI",
      "details": {},
      "confidence": "high"
    }
  ]
}
```

Skipped shape:

```json
{
  "status": "skipped",
  "source": "chrome-history",
  "reason": "not_found",
  "events": []
}
```

Error shape:

```json
{
  "status": "error",
  "source": "codex-history",
  "message": "history.jsonl is unreadable",
  "events": []
}
```

## Required event fields

- `source`
- `timestamp`
- `type`
- `summary`
- `details`
- `confidence`

`details` is required but source-specific.

## Source registry fields

`sources.json` supports these additional declarative fields:

- `prerequisites`: preflight checks such as `git_repo`, `path_exists`, `all_paths_exist`, `glob_exists`, `chrome_history_db`
- `confidence_category`: source role used by grouping confidence rules, such as `git`, `ai_history`, `browser`, `file_activity`

## Shared CLI conventions

- `--since` and `--until` accept ISO 8601 datetime or `YYYY-MM-DD`
- `--date` accepts `today`, `yesterday`, or `YYYY-MM-DD` as a shorthand for single-day aggregation
- `--group-window` overrides the default 15 minute grouping window
- `--workspace` defaults to the current working directory where relevant
- `--all-sessions` disables workspace filtering for Claude/Codex history
- `--limit` caps returned events for manual inspection

## Aggregator output

`aggregate.py` emits a reusable intermediate JSON with these top-level keys:

- `sources`: normalized per-source execution results
- `timeline`: merged event list sorted by timestamp
- `groups`: nearby events grouped with `evidence` and aggregated `confidence`
- `summary`: source status counts, total event count, total group count, and `no_sources_available`

Aggregator behavior:

- forwards `--workspace` to source CLIs and also runs them with that directory as `cwd`
- prints a one-line preflight summary to `stderr` before collection starts
- uses `sources.json` metadata to evaluate preflight availability and confidence categories without source-name conditionals

## Skill Miner CLIs

`skill-miner` uses two standalone CLIs that do not go through `aggregate.py`.
Deep research adds helper CLIs for post-detail judgment and final proposal formatting.

### `skill_miner_prepare.py`

Purpose:

- reads raw Claude/Codex JSONL directly
- defaults to `--days 7`
- disables the date window only when `--all-sessions` is explicitly set
- splits Claude history into logical sessions
- emits compressed `candidates` and `unclustered` packets for proposal phase
- can emit `intent_analysis` for B0 observation with `--dump-intents`

Top-level shape:

```json
{
  "status": "success",
  "source": "skill-miner-prepare",
  "candidates": [],
  "unclustered": [],
  "sources": [],
  "summary": {},
  "config": {},
  "intent_analysis": {
    "summary": {},
    "items": []
  }
}
```

Important fields:

- `config.days`: default `7`
- `config.all_sessions`: only explicit override for the date window
- `config.date_window_start`: ISO 8601 threshold used when `all_sessions=false`
- `candidates[].session_refs`: stable references for detail lookup
- `candidates[].support`: packet counts and ranking evidence
- `candidates[].confidence`, `proposal_ready`, `triage_status`: proposal quality and triage outcome
- `candidates[].quality_flags`, `evidence_summary`: why a candidate is strong, weak, or held back
- `candidates[].evidence_items`: up to 3 proposal-ready evidence entries with `session_ref`, `timestamp`, `source`, `summary`
- `candidates[].research_targets`: up to 5 suggested refs for deep research on `needs_research` candidates
- `candidates[].research_brief`: suggested questions and decision rules for deep research
- `unclustered[]`: packets that did not form a repeated cluster
- `intent_analysis.summary`: `generic_rate`, `synonym_split_rate`, `specificity_distribution`
- `intent_analysis.items`: anonymized `primary_intent` samples for B0 inspection

Contract notes:

- `summary` in `evidence_items[]` prefers `primary_intent`; when empty it falls back to a masked representative snippet
- `prepare` is the only phase that reads raw history for evidence chain construction
- no state file is used; execution mode is determined only by CLI flags

`candidates[].evidence_items[]` example:

```json
[
  {
    "session_ref": "codex:abc123:1710000000",
    "timestamp": "2026-03-10T09:00:00+09:00",
    "source": "codex-history",
    "summary": "SKILL.md の構造確認を行い、提案理由を整理"
  }
]
```

### `skill_miner_detail.py`

Purpose:

- accepts one or more `session_ref` values from prepare output
- returns user/assistant conversation detail for selected packets only

Top-level shape:

```json
{
  "status": "success",
  "source": "skill-miner-detail",
  "details": [],
  "errors": []
}
```

Important fields:

- `details[].messages`: pure user/assistant conversation log
- `details[].tool_calls`: aggregated command/tool usage when available

### `skill_miner_research_judge.py`

Purpose:

- accepts one candidate from prepare output and one detail payload
- returns a structured conclusion for deep research

Top-level shape:

```json
{
  "status": "success",
  "source": "skill-miner-research-judge",
  "candidate_id": "codex-abc123",
  "judgment": {}
}
```

Important fields:

- `judgment.recommendation`: `promote_ready`, `split_candidate`, or `reject_candidate`
- `judgment.proposed_triage_status`: suggested triage status after research
- `judgment.reasons`: short explanation list for the decision
- `judgment.split_suggestions`: candidate split axes when the verdict is `split_candidate`

### `skill_miner_proposal.py`

Purpose:

- accepts prepare output and optional research judgments
- returns final `ready` / `needs_research` / `rejected` proposal sections and markdown
- renders the evidence chain directly from `candidates[].evidence_items[]`
- does not reload raw history

Top-level shape:

```json
{
  "status": "success",
  "source": "skill-miner-proposal",
  "ready": [],
  "needs_research": [],
  "rejected": [],
  "selection_prompt": null,
  "markdown": ""
}
```

Important fields:

- `ready`: proposal-ready candidates
- `needs_research`: candidates still held back after prepare and optional research judgment
- `rejected`: candidates and unclustered references that should not be proposed
- `markdown`: preformatted proposal sections for the LLM/user-facing output

### `session_ref` contract

- Claude: `claude:/absolute/path/to/file.jsonl:<epoch>`
- Codex: `codex:<session_id>:<epoch>`

These refs are the only supported bridge between prepare and detail.
