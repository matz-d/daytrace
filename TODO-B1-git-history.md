# TODO B1. Source CLI / git-history

Phase: Foundation
Depends on: C の先行タスク（共通契約 + sources.json）

## Checklist

- [ ] CLI の引数仕様を決める（期間指定、対象ディレクトリ）
- [ ] `git log --name-only --after --before` ベースの取得処理を実装する
- [ ] commit ごとに共通イベント形式（source, timestamp, type, summary, details, confidence）で JSON 化する
- [ ] `details` に changed files / `--stat` レベルの差分情報を入れる
- [ ] 対象期間に commit がない場合の空結果を返す
- [ ] git repo でない場合の `skipped` 応答を実装する
- [ ] サンプル repo で CLI 単体実行を確認する

## Done Criteria

- [ ] 期間指定ありで共通形式の JSON が返る
- [ ] 失敗時も機械可読 JSON で終了する
