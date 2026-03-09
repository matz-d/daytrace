# TODO B3. Source CLI / codex-history

Phase: Foundation
Depends on: C の先行タスク（共通契約 + sources.json）

## Checklist

- [ ] `~/.codex/history.jsonl` と `~/.codex/sessions/.../rollout-*.jsonl` の読み方を整理する
- [ ] `history.jsonl` を索引として session ファイルへ辿る実装を行う
- [ ] session meta / commentary / tool call を共通イベント形式で JSON 化する
- [ ] 期間フィルタとセッション単位のまとめを実装する
- [ ] 履歴未存在時の `skipped` 応答を実装する
- [ ] 代表的な rollout データで CLI 単体確認を行う

## Note

B2 と同様、2 つのデータパスで使われる:
- `daily-report` / `post-draft`: aggregator 経由（期間指定あり）
- `skill-miner`: 直接呼び出し（全セッション対象）

## Done Criteria

- [ ] Codex セッション履歴を期間指定で JSON 化できる
- [ ] 期間指定なし（全セッション）でも動作する
- [ ] 履歴構造差分があっても落ちずに skip できる
