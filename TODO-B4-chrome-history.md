# TODO B4. Source CLI / chrome-history

Phase: Foundation
Depends on: C の先行タスク（共通契約 + sources.json）

## Checklist

- [x] Chrome `History` DB の探索先と対象 profile を固定する
- [x] DB を `/tmp` にコピーして読む安全なフローを実装する
- [x] URL / title / last visit time / visit count の抽出クエリを実装する
- [x] 共通イベント形式で JSON 化する（`details` に url / title / visit_count を入れる）
- [x] query string を除去する正規化処理を入れる
- [x] Chrome 非インストール時または DB 不在時の `skipped` 応答を実装する
- [ ] ロック中でもコピー経由で読めることを確認する

## Done Criteria

- [ ] Chrome 起動中でも履歴が読める
- [x] URL 正規化済みの共通形式 JSON が返る
