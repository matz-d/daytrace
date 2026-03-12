# TODO AR1a. Contract Baseline / aggregate compatibility

Phase: Architecture Refresh
Depends on: なし
Parent Plan Mapping: TODO 1a

## Goal

`aggregate.py` を安全に触るための contract baseline を先に固定する。
ここでは code movement より、互換性マトリクス・contract test・downstream 依存点の保護を優先する。

## 先行ゲート

- [x] 親プランの互換性マトリクスを、この TODO の作業単位に落とし直す
- [x] `aggregate.py` の contract 対象を top-level / `sources[]` / `timeline[]` / `groups[]` / `summary` に分解する
- [x] `daily-report` / `post-draft` が実際に読んでいる aggregate field を列挙する

先行ゲートが終わるまでは、`aggregate.py` の本格抽出に入らない。

## Parallel Tracks

### Track A. Aggregate contract tests

- [x] `plugins/daytrace/scripts/tests/test_aggregate_contracts.py` を新設する
- [x] top-level shape の契約テストを追加する
- [x] `sources[]` の必須 field / optional field 契約を追加する
- [x] `timeline[]` の event contract と sort semantics を保護する
- [x] `groups[]` の field / confidence / grouping semantics を保護する
- [x] `summary` の field と意味論を保護する

### Track B. Source result / filter forwarding protection

- [x] source CLI の `success` / `skipped` / `error` shape を保護する
- [x] `scope` metadata の回帰テストを追加する
- [x] `--workspace` / `--date` / `--since` / `--until` / `--all-sessions` の forwarding 回帰を補強する
- [x] mixed-scope が可視化されることを contract として固定する

### Track C. Downstream smoke protection and docs

- [x] `daily-report` / `post-draft` が前提にする aggregate field を smoke-level に保護する
- [x] contract matrix を TODO 側に要約して記録する
- [x] 将来の extraction で壊してはいけない意味論を箇条書きで固定する

## Contract Matrix Snapshot

### Top-level

互換対象:

- `status`
- `generated_at`
- `workspace`
- `filters`
- `config`
- `sources`
- `timeline`
- `groups`
- `summary`

補足:

- `filters` は raw CLI flag を保持する
- `--date` shorthand は source forwarding 時には resolved `since` / `until` へ変換される

### `sources[]`

必須 field:

- `name`
- `status`
- `scope`
- `events_count`

optional field:

- `reason`
- `message`
- `command`
- `duration_sec`

意味論:

- `status` は `success` / `skipped` / `error`
- `scope` は source manifest の `scope_mode` をそのまま見せる

### `timeline[]`

互換対象:

- `source`
- `timestamp`
- `type`
- `summary`
- `details`
- `confidence`
- `group_id`

意味論:

- `timestamp` 昇順で安定ソートされる
- source event contract を再構成できる粒度を維持する

### `groups[]`

互換対象:

- `id`
- `start_timestamp`
- `end_timestamp`
- `summary`
- `confidence`
- `sources`
- `confidence_categories`
- `source_count`
- `event_count`
- `evidence`
- `events`

意味論:

- grouping は既存の window semantics に従う
- `confidence` は category ベース (`git` + `ai_history` = `high`) を維持する
- `events` は downstream skill が report / narrative を組める粒度で残す

### `summary`

互換対象:

- `source_status_counts`
- `total_events`
- `total_groups`
- `no_sources_available`

意味論:

- downstream skill は `source_status_counts` を優先参照できる
- `no_sources_available` は空結果メタ情報として維持する

## Downstream Field Dependencies

### `daily-report`

実際に前提にしている field:

- `sources[].name`
- `sources[].status`
- `sources[].scope`
- `sources[].events_count`
- `groups[].summary`
- `groups[].confidence`
- `groups[].sources`
- `groups[].confidence_categories`
- `groups[].event_count`
- `groups[].events`
- `groups[].evidence`
- `timeline[].summary`
- `timeline[].type`
- `timeline[].source`
- `timeline[].timestamp`
- `timeline[].group_id`
- `summary.source_status_counts`
- `summary.total_events`
- `summary.total_groups`
- `summary.no_sources_available`

### `post-draft`

実際に前提にしている field:

- `sources[].name`
- `sources[].status`
- `sources[].scope`
- `groups[].summary`
- `groups[].confidence`
- `groups[].sources`
- `groups[].confidence_categories`
- `groups[].event_count`
- `groups[].events`
- `groups[].evidence`
- `timeline[].summary`
- `timeline[].type`
- `timeline[].source`
- `timeline[].timestamp`
- `timeline[].group_id`
- `summary.source_status_counts`
- `summary.no_sources_available`

## Extraction Guardrails

- mixed-scope 可視化は `sources[].scope` ベースで維持する
- timeline は timestamp 昇順を維持する
- grouping window の既定値と group boundary semantics を変えない
- group confidence は `confidence_category` 由来の決定論的ルールを維持する
- `summary.no_sources_available` は空結果メタ情報として維持し、分岐判定の主根拠は `source_status_counts.success` に置く

## Deliverables

- `test_aggregate_contracts.py`
- aggregate nested contract 一式のテスト
- downstream skill 依存点の smoke protection
- 実装前に固定された互換性ノート

## Done Criteria

- [x] `test_aggregate_contracts.py` が追加されている
- [x] top-level だけでなく nested contract テストが通る
- [x] mixed-scope と filter forwarding の回帰が保護されている
- [x] `daily-report` / `post-draft` が依存する aggregate field が文書化されている

## Verification Notes

- `python3 -m unittest plugins/daytrace/scripts/tests/test_aggregate_contracts.py`
- `python3 -m unittest plugins/daytrace/scripts/tests/test_aggregate.py`
- 既存 skill 文書と contract matrix の差分確認
