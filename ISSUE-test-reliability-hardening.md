# Issue: Test Reliability Hardening

Date: 2026-03-18

## Trigger

TDD hardening pass for the DayTrace script test suite.

## Defect Found Through Tests

### 1. `git-history` timeout path crashed with `NameError`

- Severity: High
- File: `plugins/daytrace/scripts/git_history.py`
- Reproduction:
  - Patch `run_command()` to raise `subprocess.TimeoutExpired`
  - Execute `git_history.main()`
- Expected:
  - The CLI returns structured DayTrace error JSON for a timeout
- Actual:
  - The process raised `NameError` because `subprocess` was referenced in the `except` clause without being imported
- Impact:
  - A slow or hung `git` command could bypass the intended fail-soft JSON contract
- Status:
  - Fixed in this pass by importing `subprocess`
  - Guarded by a new regression test in `plugins/daytrace/scripts/tests/test_git_history.py`

## Test Hardening Added

- Added a real CLI integration test for `chrome_history.py` using temporary SQLite History databases with multi-profile discovery, URL normalization, visit collapsing, and date filtering.
- Added a real CLI integration test for `codex_history.py` using temporary `history.jsonl` and rollout JSONL files with workspace scoping, commentary extraction, and tool-call emission.
- Replaced the repo-state-dependent happy-path test for `workspace_file_activity.py` with isolated temporary git repository tests, and added a positive untracked-file emission test.

## Notes

- The main reliability gap before this pass was not duplicate tests; it was missing executable coverage on real CLI paths.
- `aggregate/store/projection/skill-miner` coverage remained strong before this change, but source-CLI integration coverage was weaker.
