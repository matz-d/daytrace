# TODO E3. Hardening / Edge Cases

Phase: Polish & Submit
Depends on: D1, D2, D3（出力スキルが動いてから）

## Checklist

- [ ] source 0 本時の end-to-end 動作を確認する
- [ ] 巨大履歴入力時の圧縮・タイムアウト・メモリ消費を確認する
- [ ] 権限エラー時のメッセージと skip 記録を確認する
- [ ] プライバシー観点で query string など不要情報が漏れないことを確認する
- [ ] 主要エッジケース修正を backlog 化し、MVP 対応分を切り分ける
- [ ] 最終デモを壊す不具合を優先順位順に潰す

## Done Criteria

- [ ] 既知の致命的不具合が解消されている
- [ ] limitation として残す事項が README に反映されている
