# TODO AR4b. Store Hardening / completeness + fail-soft + fidelity

Phase: Architecture Refresh
Depends on: AR4
Parent Plan Mapping: AR4 review follow-up

## Goal

AR1a-AR4 のレビューで見つかった、store-backed path の壊れやすさをまとめて潰す。
特に以下を優先する。

- projection path の `timeline[].group_id` 欠落
- store の completeness 概念不足
- cache/store 障害が本処理を巻き込む問題
- store-backed `skill-miner` が raw path の近似であることの明示不足
- SQLite 並行性と接続管理の甘さ

## 先行ゲート

- [ ] `timeline[].group_id` 欠落を最優先バグとして切り出す
- [ ] 「store は best-effort」「slice は completeness を評価してから使う」という方針を短い note に固定する
- [ ] `complete / partial / degraded / stale / empty` の状態定義を決める

## Priority Order

1. `group_id` 整合
2. fail-soft 化
3. SQLite robustness
4. slice completeness
5. requested_date 正規化
6. fidelity 明示
7. 低優先の整理事項

## Parallel Tracks

### Track A. Projection contract fix

- [ ] `build_groups()` の破壊的 mutation に依存しない `group_id` 付与方針を決める
- [ ] projection path でも `timeline[].group_id` が AR1a contract を満たすよう修正する
- [ ] `aggregate.py` path と projection path の `timeline/group` 整合テストを追加する
- [ ] `build_groups()` の mutation を残すか廃止するかを決め、方針をコードコメントまたは note に反映する

Done when:

- [ ] `aggregate.py` と projection adapter の両方で `timeline[].group_id` が読める
- [ ] contract test に projection variant が追加されている

### Track B. Fail-soft store writes

- [ ] `aggregate.py` の store 永続化を個別 `try/except` に分離する
- [ ] store 書き込み失敗時も aggregate payload 自体は `status=success` で返す
- [ ] payload `config` に `store_error` または同等の warning 情報を入れる
- [ ] `skill_miner_prepare.py` の pattern persist を quality gate 付きにする
- [ ] 「空結果」「partial/degraded run」「persist 失敗」で既存 patterns を消さないようにする

Done when:

- [ ] store が書けなくても aggregate JSON は返る
- [ ] pattern persist が unsafe な run ではスキップされる
- [ ] warning が stderr または payload に残る

### Track C. SQLite robustness and connection unification

- [ ] `store.py` と `derived_store.py` の `_connect()` を一本化する
- [ ] `PRAGMA journal_mode = WAL` を設定する
- [ ] `PRAGMA busy_timeout = 5000` を設定する
- [ ] connection を明示的に close するパターンへ揃える
- [ ] `derived_store.py` 側の独自 `_connect()` を削除する

Done when:

- [ ] 全 DB アクセスが共通 connection helper を通る
- [ ] WAL / busy_timeout が有効になる
- [ ] 接続 close 方針が統一される

### Track D. Slice completeness

- [ ] `expected_sources()` もしくは同等の API を追加する
- [ ] expected source 集合の定義に platform と preflight 可否を含める
- [ ] `SliceStatus` 型または同等の構造を導入する
- [ ] `evaluate_slice_completeness()` を実装する
- [ ] `complete / partial / degraded / stale / empty` を判定できるようにする
- [ ] projection adapter の hydrate 判定を completeness ベースに書き換える
- [ ] `skill_miner_prepare.py --input-source auto` の判定を completeness ベースに書き換える
- [ ] payload に completeness メタデータを含める

Done when:

- [ ] 部分保存 slice を complete 扱いしない
- [ ] expected source が揃っていない場合は hydrate か raw fallback が走る
- [ ] downstream が completeness を参照できる

### Track E. requested_date normalization

- [ ] store persist 時に `requested_date` を正規化後の ISO 日付で保存する
- [ ] run fingerprint も同じ正規化値を使う
- [ ] 元入力の `"today"` / `"yesterday"` を残すなら `filters_json` に保持する
- [ ] completeness 判定と query path が同じ正規化ルールを使うようにする

Done when:

- [ ] `"today"` と同じ実日付の ISO slice が二重化しない
- [ ] date-first query の hit rate が安定する

### Track F. Fidelity and approximate-store semantics

- [ ] `skill_miner_prepare.py` payload に `config.input_fidelity` を追加する
- [ ] store path 由来 packet に `_fidelity = "approximate"` を付ける
- [ ] raw path 由来 packet に `_fidelity = "original"` を付ける
- [ ] store path と raw path の candidate 差が大きい時の warning 方針を決める
- [ ] `--compare-legacy` 利用時に overlap 指標を出せるようにする
- [ ] raw/store candidate overlap regression test を追加する

Done when:

- [ ] store-backed prepare が raw の近似であることが payload から分かる
- [ ] candidate 品質の大きな劣化を回帰テストで検知できる

### Track G. Low-priority cleanup

- [ ] `normalize_event()` の confidence 値 range を soft validate する
- [ ] `_canonical_json()` / `_stable_hash()` を共通化する
- [ ] confidence category 構築の責務を 1 箇所へ寄せる
- [ ] `--no-store` path の contract test variant を追加する
- [ ] `activities/patterns` を base schema に含める理由をコメントまたは note に明記する
- [ ] `resolve_command_paths()` の basename 前提は AR5 で扱うことを note に残す

Done when:

- [ ] fingerprint ロジックの重複が解消される
- [ ] `--no-store` path の回帰が保護される
- [ ] 低優先の設計メモが残る

## Deliverables

- projection path の `group_id` 修正
- fail-soft store / pattern persistence
- 共通 DB connection helper
- slice completeness evaluator
- requested_date normalization
- fidelity metadata と comparison guard
- hardening テスト追加

## Verification Checklist

### Contract / projection

- [ ] `aggregate.py` path で `timeline[].group_id` が存在する
- [ ] `daily_report_projection.py` path でも `timeline[].group_id` が存在する
- [ ] `post_draft_projection.py` path でも `timeline[].group_id` が存在する
- [ ] `--no-store` path の contract test が通る

### Store failure tolerance

- [ ] store 書き込み失敗を人工的に起こしても aggregate payload は返る
- [ ] pattern persist 失敗時も `skill_miner_prepare.py` は成功扱いで終わる
- [ ] degraded/empty run が既存 patterns を消さない

### Completeness

- [ ] 1 source だけ保存された slice を `partial` と判定できる
- [ ] source の `error` / `skipped` を `degraded` と区別できる
- [ ] manifest 変更後の slice を `stale` と判定できる
- [ ] expected source が全て `success` の時だけ `complete` になる

### Fidelity

- [ ] store path と raw path の candidate overlap 指標が出せる
- [ ] しきい値未満の差分に warning が出る
- [ ] payload の `config.input_fidelity` が正しく入る

### SQLite robustness

- [ ] WAL / busy_timeout 設定が入る
- [ ] DB helper が 1 箇所にまとまる
- [ ] 明示 close が確認できる

## Suggested Test Additions

- [ ] `test_projection_adapters.py` に `timeline[].group_id` 検証を追加する
- [ ] `test_projection_adapters.py` に partial slice fixture を追加する
- [ ] `test_skill_miner.py` に auto mode の partial-store fallback テストを追加する
- [ ] `test_store.py` に persist failure の fail-soft テストを追加する
- [ ] `test_aggregate_contracts.py` に `--no-store` variant を追加する
- [ ] raw/store candidate overlap の regression test を追加する

## Out of Scope

- schema の全面再分割
- generic query language の導入
- AR5 の user drop-in source 実装の拡張
- `resolve_command_paths()` の全面再設計
