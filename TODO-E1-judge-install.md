# TODO E1. Judge Install / Environment Validation

Phase: Polish & Submit
Depends on: E3（hardening で致命的バグを潰してから）

## Checklist

- [x] ソースが少ないマシンを想定した検証ケースを定義する
- [x] install 直後の利用可能ソース検出表示を確認する
- [x] source 0 本、1 本、複数本のケースで実行確認する
- [x] 権限不足、履歴不在、DB lock の挙動を確認する
- [x] graceful degrade の実例をスクリーンショットまたはログで残す（※DB lock は temp copy により耐障害的成功するため degrade ではない）

## Done Criteria

- [x] クリーン環境相当で install → 実行が再現できる
- [x] source 欠損があっても審査で説明可能な状態になっている

## Verification Notes (2026-03-09)

- `source 0 本`: `HOME="$TMP_HOME" python3 plugins/daytrace/scripts/aggregate.py --workspace "$EMPTY_WS" --all-sessions` で `stderr` に `Source preflight: ... available=none` を確認。`stdout.summary.no_sources_available=true` で終了し、`git-history` / `workspace-file-activity` は `not_git_repo`、履歴系は `not_found` で `skipped`。
- `source 1 本 (codex-history のみ)`: `HOME="$TMP_HOME" python3 plugins/daytrace/scripts/aggregate.py --workspace "$EMPTY_WS" --all-sessions` で `available=codex-history` を確認。`stdout.summary.source_status_counts` は `success=1, skipped=4`、空ではなく 3 event を返した。
- `複数 source`: Git repo + untracked file + Claude/Codex 履歴ありの一時環境で同コマンドを実行し、`available=claude-history, codex-history, git-history, workspace-file-activity` を確認。`chrome-history(not_found)` があっても aggregate 全体は成功し、4 source 成功 / 1 source skip / 6 event で終了。
- `権限不足`: `python3 plugins/daytrace/scripts/claude_history.py --root "$UNREADABLE_CLAUDE_ROOT" --all-sessions`、`python3 plugins/daytrace/scripts/codex_history.py --history-file "$UNREADABLE_HISTORY" --sessions-root "$SESSIONS_ROOT" --all-sessions`、`python3 plugins/daytrace/scripts/chrome_history.py --root "$UNREADABLE_CHROME_ROOT"` を確認。いずれも JSON で `status=skipped` と `reason=permission_denied` を返し、`message` に OS エラーが入る。
- `履歴不在`: `python3 plugins/daytrace/scripts/codex_history.py --history-file "$MISSING_HISTORY" --sessions-root "$MISSING_SESSIONS"` で JSON `status=skipped`, `reason=not_found` を確認。install 直後の空環境でも machine-readable に扱える。
- `source 欠損`: 欠損 script を指す一時 `sources.json` で `python3 plugins/daytrace/scripts/aggregate.py --workspace "$EMPTY_WS" --sources-file "$TMP_SOURCES"` を実行。`stderr` は `unavailable=missing-source(command_missing)`、`stdout.sources[0]` は `status=error` だが top-level aggregate は落ちずに JSON を返す。
- `DB lock 相当`: 排他 lock 中の Chrome `History` DB を用意して `python3 plugins/daytrace/scripts/chrome_history.py --root "$LOCKED_CHROME_ROOT"` を実行。読み取り前に temp copy を作る実装のため `status=success` で 1 event を返し、lock 中でも graceful degrade ではなく**耐障害的成功**として通常成功することを確認（degrade の実例には含めない）。
- 評価: install 直後に審査員が知りたい「この環境で何が使えるか」は `stderr` の `Source preflight: workspace=... | available=... | unavailable=... | skipped=...` で即時に把握できる。詳細な reason は `stdout.sources[]` の JSON でも追える。
