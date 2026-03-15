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

- [x] built-in registry loader を明確化する
- [x] user drop-in discovery を実装する
- [x] `~/.config/daytrace/sources.d/` からの読み込みを追加する

### Track B. Validation / preflight

- [x] source manifest schema validation を実装する
- [x] invalid manifest を machine-readable に報告する
- [x] built-in / user source 共通の preflight path を作る

### Track C. Compatibility / tests / docs

- [x] existing `sources.json` 互換を保つ
- [x] 1 つ以上の user source fixture を追加する
- [x] invalid manifest fixture を追加する
- [x] registry API と source identity の文書を整える

## Deliverables

- unified registry loader
- manifest validation
- shared preflight path
- built-in / user source 用テスト
- registry API 文書

## Done Criteria

- [x] built-in source は従来通り動く
- [x] 少なくとも 1 つの user source を discovery して実行できる
- [x] invalid manifest を明確に報告できる
- [x] store ingest と source identity の整合が崩れていない

## Scope Decisions

### `--user-sources-dir` は collection-only サポート (2026-03-15)

`aggregate.py --user-sources-dir` は source 収集時の registry ロードには反映されるが、
`load_expected_sources()` (auto-mode completeness validation) は `DEFAULT_USER_SOURCES_DIR` を使用する。

理由:
- `--user-sources-dir` は registry テスト・開発用フラグ（README: "for registry testing or custom installs"）
- auto-mode の manifest 検証には `--sources-file` が既に提供されている
- completeness validation にカスタム dir を通す需要は現時点で確認されていない

影響:
- `aggregate.py --user-sources-dir /custom/dir` で収集した slice を
  `skill_miner_prepare.py --input-source auto` で検証する場合、
  completeness 判定がデフォルト dir ベースになるため、
  カスタム dir 固有の source が missing 扱いになる可能性がある
- workaround: `--sources-file` で明示的にカスタム registry を指定する

将来の変更が必要になった場合:
- `load_expected_sources()` に `user_sources_dir` パラメータを追加し、
  呼び出し元（`skill_miner_prepare.py`, `derived_store.py`）から伝搬する

### Legacy store slice の再ハイドレーション (2026-03-15)

P0-3 で canonical packet payload が source observation details に導入された。
この変更以前にハイドレーションされた store slice は旧形式のため、
store-backed prepare が highlight-based reconstruction にフォールバックする。

推奨: 対象期間の `aggregate.py` を再実行して slice を更新する。
README.md の contract notes に同内容を記載済み（L228）。

## Verification Notes

- built-in registry regression テスト
- user drop-in source fixture テスト
- invalid manifest テスト
