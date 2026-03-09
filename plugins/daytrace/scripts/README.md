# DayTrace Source CLI Contract

`scripts/` contains source CLIs for DayTrace.

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
