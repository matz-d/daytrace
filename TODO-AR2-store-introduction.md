# TODO AR2. Store Introduction / source_runs + observations

Phase: Architecture Refresh
Depends on: AR1b
Parent Plan Mapping: TODO 2

## Goal

再構築可能な SQLite store を導入し、source 実行結果と normalized event を永続化する。
この段階では `activities` / `patterns` は入れず、run context と observations の安定保存に集中する。

## 先行ゲート

- [x] source identity の定義を固定する
- [x] manifest fingerprint の扱いを固定する
- [x] mixed-scope 再投影に必要な run context 項目を固定する

## Parallel Tracks

### Track A. Schema / bootstrap

- [x] SQLite schema を設計する
- [x] `source_runs` table を作る
- [x] `observations` table を作る
- [x] migration bootstrap を用意する

### Track B. Ingest path

- [x] source CLI result から `source_runs` に保存する経路を作る
- [x] normalized event を `observations` に保存する経路を作る
- [x] source run と observation の関連付けを実装する
- [x] `aggregate.py` と store の責務境界を定める

### Track C. Idempotency / rebuild / docs

- [x] duplicate write 制御を実装する
- [x] `observations` fingerprint 方針を固定する
- [x] DB 削除後の再 ingest フローをテストする
- [x] source-agnostic manifest draft note を書く
- [x] run context 保存方針を文書化する

## Deliverables

- SQLite schema
- migration/bootstrap path
- `source_runs` / `observations` ingest path
- rerun idempotency rule
- manifest draft note
- run context 保存ノート

## Done Criteria

- [x] source 実行結果を `source_runs` に保存できる
- [x] normalized event を `observations` に保存できる
- [x] duplicate write が制御されている
- [x] DB 削除後に再実行すれば必要データを復元できる
- [x] mixed-scope 再投影に必要な run context が残る

## Verification Notes

- store 初期化テスト
- rerun / rebuild テスト
- observation 保存件数と aggregate result 件数の照合
