# TODO E3. Hardening / Edge Cases

Phase: Polish & Submit
Depends on: D1, D2, D3（出力スキルが動いてから）

## Checklist

- [x] source 0 本時の end-to-end 動作を確認する
- [x] 巨大履歴入力時の圧縮・タイムアウト・メモリ消費を確認する
- [x] 権限エラー時のメッセージと skip 記録を確認する
- [x] プライバシー観点で query string など不要情報が漏れないことを確認する
- [x] 主要エッジケース修正を backlog 化し、MVP 対応分を切り分ける
- [x] 最終デモを壊す不具合を優先順位順に潰す

## Done Criteria

- [x] 既知の致命的不具合が解消されている
- [x] limitation として残す事項が README に反映されている

## Verification Notes

- [x] source 0 本ケースは `aggregate.py` を unsupported source のみの `sources.json` で実行し、`summary.no_sources_available=true` と `sources[].status=skipped` を確認した
- [x] 大きめの履歴入力として `claude_history.py --all-sessions`、`codex_history.py --all-sessions`、`aggregate.py --date today --all-sessions` を実行し、当日環境では約 0.4s / 約 104 events / 10 groups / 約 29MB 規模で完了することを確認した
- [x] `claude_history.py` の unreadable JSONL を用いた検証で `status=skipped`, `reason=permission_denied` を確認した
- [x] browser URL の query string / fragment 除去は `chrome_history.py` と `common.py` のテストで確認した

## MVP Backlog

- [x] MVP で対応した項目: workspace 伝搬、plugin root 解決明文化、Chrome URL 圧縮、permission denied の graceful degrade、query string / fragment の除去
- [x] limitation として残す項目: Windows 未検証、対話選択フローの最終確認は手動ベース、`sources.json` 設定不備は明示的エラー
