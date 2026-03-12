# TODO AR5. Source Registry Redesign / built-in + user drop-in

Phase: Architecture Refresh
Depends on: AR2
Parent Plan Mapping: TODO 3

## Goal

built-in source と user drop-in source を同じ registry API で扱えるようにする。
これは core refresh の blocker ではなく、独立拡張として後置する。

## 先行ゲート

- [x] manifest shape draft を固定する
- [x] source identity / manifest fingerprint が AR2 と整合していることを確認する
- [x] built-in source 互換を崩さない validation 方針を決める

## Parallel Tracks

### Track A. Registry loader / discovery

- [ ] built-in registry loader を明確化する
- [ ] user drop-in discovery を実装する
- [ ] `~/.config/daytrace/sources.d/` からの読み込みを追加する

### Track B. Validation / preflight

- [ ] source manifest schema validation を実装する
- [ ] invalid manifest を machine-readable に報告する
- [ ] built-in / user source 共通の preflight path を作る

### Track C. Compatibility / tests / docs

- [ ] existing `sources.json` 互換を保つ
- [ ] 1 つ以上の user source fixture を追加する
- [ ] invalid manifest fixture を追加する
- [ ] registry API と source identity の文書を整える

## Deliverables

- unified registry loader
- manifest validation
- shared preflight path
- built-in / user source 用テスト
- registry API 文書

## Done Criteria

- [ ] built-in source は従来通り動く
- [ ] 少なくとも 1 つの user source を discovery して実行できる
- [ ] invalid manifest を明確に報告できる
- [ ] store ingest と source identity の整合が崩れていない

## Verification Notes

- built-in registry regression テスト
- user drop-in source fixture テスト
- invalid manifest テスト
