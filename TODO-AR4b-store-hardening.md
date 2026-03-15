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
- [x] 「store は best-effort」「slice は completeness を評価してから使う」という方針を短い note に固定する
- [x] `complete / partial / degraded / stale / empty` の状態定義を決める

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

- [x] `build_groups()` の破壊的 mutation に依存しない `group_id` 付与方針を決める
- [x] projection path でも `timeline[].group_id` が AR1a contract を満たすよう修正する
- [x] `aggregate.py` path と projection path の `timeline/group` 整合テストを追加する
- [x] `build_groups()` の mutation を残すか廃止するかを決め、方針をコードコメントまたは note に反映する

Done when:

- [x] `aggregate.py` と projection adapter の両方で `timeline[].group_id` が読める
- [x] contract test に projection variant が追加されている

### Track B. Fail-soft store writes

- [x] `aggregate.py` の store 永続化を個別 `try/except` に分離する
- [x] store 書き込み失敗時も aggregate payload 自体は `status=success` で返す
- [x] payload `config` に `store_error` または同等の warning 情報を入れる
- [x] `skill_miner_prepare.py` の pattern persist を quality gate 付きにする
- [x] 「空結果」「partial/degraded run」「persist 失敗」で既存 patterns を消さないようにする

Done when:

- [x] store が書けなくても aggregate JSON は返る
- [x] pattern persist が unsafe な run ではスキップされる
- [x] warning が stderr または payload に残る

### Track C. SQLite robustness and connection unification

- [x] `store.py` と `derived_store.py` の `_connect()` を一本化する
- [x] `PRAGMA journal_mode = WAL` を設定する
- [x] `PRAGMA busy_timeout = 5000` を設定する
- [x] connection を明示的に close するパターンへ揃える
- [x] `derived_store.py` 側の独自 `_connect()` を削除する

Done when:

- [x] 全 DB アクセスが共通 connection helper を通る
- [x] WAL / busy_timeout が有効になる
- [x] 接続 close 方針が統一される

### Track D. Slice completeness

- [x] `expected_sources()` もしくは同等の API を追加する
- [x] expected source 集合の定義に platform と preflight 可否を含める
- [x] `SliceStatus` 型または同等の構造を導入する
- [x] `evaluate_slice_completeness()` を実装する
- [x] `complete / partial / degraded / stale / empty` を判定できるようにする
- [x] projection adapter の hydrate 判定を completeness ベースに書き換える
- [x] `skill_miner_prepare.py --input-source auto` の判定を completeness ベースに書き換える
- [x] payload に completeness メタデータを含める

Done when:

- [x] 部分保存 slice を complete 扱いしない
- [x] expected source が揃っていない場合は hydrate か raw fallback が走る
- [x] downstream が completeness を参照できる

### Track E. requested_date normalization

- [x] store persist 時に `requested_date` を正規化後の ISO 日付で保存する
- [x] run fingerprint も同じ正規化値を使う
- [ ] 元入力の `"today"` / `"yesterday"` を残すなら `filters_json` に保持する
- [x] completeness 判定と query path が同じ正規化ルールを使うようにする
- [x] `read_store_packets` の閾値計算を `_store_slice_bounds` に統一する (P0-2, 2026-03-15)

Done when:

- [x] `"today"` と同じ実日付の ISO slice が二重化しない
- [ ] date-first query の hit rate が安定する

Note (2026-03-15):
P0-2 で `read_store_packets` が `_store_slice_bounds` を直接使うよう修正済み。
これにより store persist 側と読み取り側で日付粒度が一致する。
残る「hit rate が安定する」は計測・観察フェーズの話であり、
実装上のギャップは P0-2 で埋まった。

### Track F. Fidelity and approximate-store semantics

- [x] `skill_miner_prepare.py` payload に `config.input_fidelity` を追加する
- [x] store path 由来 packet に `_fidelity` を付ける (`canonical` / `approximate`)
- [x] raw path 由来 packet に `_fidelity = "original"` を付ける
- [x] store path と raw path の candidate 差が大きい時の warning 方針を決める
- [x] `--compare-legacy` 利用時に overlap 指標を出せるようにする
- [x] raw/store candidate overlap regression test を追加する (P1-3, 2026-03-15: `test_prepare_all_sessions_store_backed_matches_raw`)

Done when:

- [x] store-backed prepare が raw の近似であることが payload から分かる
- [~] candidate 品質の大きな劣化を回帰テストで検知できる (基本ケースは P1-3 で追加済み。overlap 指標の定量出力は未実装)

Note (2026-03-15):
P0-3 で `claude_history.py` が canonical `logical_packets` を observation details に保存するよう変更。
これにより store-backed prepare は highlight-based reconstruction ではなく
canonical packet を直接再利用でき、raw/store parity が大幅に改善された。
`_fidelity` per-packet マーカーの設計は以下を考慮すること:
- canonical packet 経由の store path → raw とほぼ同等（`"canonical"`）
- highlight-based reconstruction 経由（旧 slice）→ 従来通り近似（`"approximate"`）
- raw path → 原本（`"original"`）
旧 slice の再ハイドレーション推奨は TODO-AR5-source-registry.md に記載済み。

### Track G. Low-priority cleanup

- [ ] `normalize_event()` の confidence 値 range を soft validate する
- [x] `_canonical_json()` / `_stable_hash()` を共通化する
- [ ] confidence category 構築の責務を 1 箇所へ寄せる
- [x] `--no-store` path の contract test variant を追加する
- [x] `activities/patterns` を base schema に含める理由をコメントまたは note に明記する
- [x] `resolve_command_paths()` の basename 前提は AR5 で扱うことを note に残す

Done when:

- [ ] fingerprint ロジックの重複が解消される
- [x] `--no-store` path の回帰が保護される
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

- [x] `aggregate.py` path で `timeline[].group_id` が存在する
- [x] `daily_report_projection.py` path でも `timeline[].group_id` が存在する
- [x] `post_draft_projection.py` path でも `timeline[].group_id` が存在する
- [x] `--no-store` path の contract test が通る

### Store failure tolerance

- [x] store 書き込み失敗を人工的に起こしても aggregate payload は返る
- [x] pattern persist 失敗時も `skill_miner_prepare.py` は成功扱いで終わる
- [x] degraded/empty run が既存 patterns を消さない

### Completeness

- [x] 1 source だけ保存された slice を `partial` と判定できる
- [x] source の `error` / `skipped` を `degraded` と区別できる
- [x] manifest 変更後の slice を `stale` と判定できる
- [x] expected source が全て `success` の時だけ `complete` になる

### Fidelity

- [x] store path と raw path の candidate overlap 指標が出せる
- [x] しきい値未満の差分に warning が出る
- [x] payload の `config.input_fidelity` が正しく入る

### SQLite robustness

- [x] WAL / busy_timeout 設定が入る
- [x] DB helper が 1 箇所にまとまる
- [x] 明示 close が確認できる

## Suggested Test Additions

- [x] `test_projection_adapters.py` に `timeline[].group_id` 検証を追加する
- [x] `test_projection_adapters.py` に broader-slice / overlapping-slice の projection 整合テストを追加する (P1-1, 2026-03-15)
- [x] `test_projection_adapters.py` に partial slice fixture を追加する
- [x] `test_skill_miner.py` に auto mode の store reuse テストを追加する (P1-2, 2026-03-15: `test_prepare_auto_reuses_store_on_repeated_run`)
- [x] `test_skill_miner.py` に auto mode の partial-store fallback テストを追加する
- [x] `test_store.py` に persist failure の fail-soft テストを追加する
- [x] `test_aggregate_contracts.py` に `--no-store` variant を追加する
- [x] raw/store candidate overlap の regression test を追加する (P1-3, 2026-03-15: `test_prepare_all_sessions_store_backed_matches_raw`)
- [x] `test_derived_store.py` に broader-slice の time bounds / overlapping-slice 整合テストを追加する (P1-1, 2026-03-15)
- [x] `test_claude_history.py` に workspace switch 分割テストを追加する (P0-3, 2026-03-15)

## Cross-Reference: P0-P2 Hardening (2026-03-15)

以下の修正が AR4b の scope と重複・関連する。
AR4b 残タスクに着手する際は、これらが既に入っていることを前提にすること。

| ID | 変更概要 | 影響する Track |
|----|----------|---------------|
| P0-1 | projection slice integrity の設計確認（コード変更なし） | A |
| P0-2 | `read_store_packets` が `_store_slice_bounds` を直接使うよう統一 | E |
| P0-3 | `build_claude_logical_packets` に cwd-split 追加、workspace filter を packet level へ移動（`skill_miner_common.py`, `skill_miner_prepare.py`, `claude_history.py`）、canonical packet を store observation details に保存 | F |
| P1-1 | projection broader-slice / overlapping-slice 回帰テスト (`test_projection_adapters.py`, `test_derived_store.py`) | A, F |
| P1-2 | skill-miner auto mode store reuse テスト (`test_skill_miner.py`) | D, F |
| P1-3 | all-sessions raw/store parity テスト (`test_skill_miner.py`) | F |

変更の詳細: `test_skill_miner_contracts.py` の workspace-switch fixture も参照。

## Out of Scope

- schema の全面再分割
- generic query language の導入
- AR5 の user drop-in source 実装の拡張
- `resolve_command_paths()` の全面再設計
