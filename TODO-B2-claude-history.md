# TODO B2. Source CLI / claude-history

Phase: Foundation
Depends on: C の先行タスク（共通契約 + sources.json）

## Checklist

- [x] 対象パス `~/.claude/projects/**/*.jsonl` の探索仕様を確定する
- [x] 期間フィルタと対象日の抽出ロジックを実装する
- [x] `user` / `assistant` イベントから必要項目のみ抽出する
- [x] 共通イベント形式で JSON 化する（`details` に cwd / sessionId / message 要約を入れる）
- [x] セッション単位の要約生成ロジックを実装する
- [x] 履歴が存在しない場合の `skipped` 応答を実装する
- [x] 大量履歴でも要約圧縮されることを確認する

## Note

このスクリプトは 2 つのデータパスで使われる:
- `daily-report` / `post-draft`: aggregator 経由（期間指定あり）
- `skill-miner`: 直接呼び出し（期間制限なし、全セッション対象）

両方のユースケースに対応できる引数設計にすること。

## Done Criteria

- [x] 期間指定でセッション要約つき JSON が返る
- [x] 期間指定なし（全セッション）でも動作する
- [x] 履歴欠損時も正常系として扱える
