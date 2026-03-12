# DayTrace Store Run Context Note

`AR2` で固定する `source_runs` / `observations` 保存方針。

## Store Boundary

- `aggregate.py` は compatibility shell のまま残す
- source collect / normalize 後に `store.py` へ永続化を委譲する
- grouping 済みの `groups` はまだ保存しない
- `observations` は grouped data ではなく normalized event 単位で保存する

## Store Location

- default: `~/.daytrace/daytrace.sqlite3`
- override: `aggregate.py --store-path /path/to/daytrace.sqlite3`
- one-off で保存を止めたい場合は `--no-store`

## `source_runs` Fixed Fields

`mixed-scope` 再投影のため、最低限これらを固定する。

- `source_name`
- `source_id`
- `identity_version`
- `manifest_fingerprint`
- `command_fingerprint`
- `status`
- `scope_mode`
- `workspace`
- `requested_date`
- `since_value`
- `until_value`
- `all_sessions`
- `filters_json`
- `command_json`
- `reason`
- `message`
- `duration_sec`
- `events_count`
- `collected_at`

補足:

- `requested_date` は raw `--date` shorthand を保持する
- `since_value` / `until_value` は実際に source command へ forward した resolved filter を保持する
- `filters_json` は将来の拡張用に opaque JSON として残す

## Run Identity And Idempotency

`source_runs.run_fingerprint` は次の組み合わせで固定する。

- `source_identity`
- `manifest_fingerprint`
- `command_fingerprint`
- `workspace`
- `requested_date`
- `since`
- `until`
- `all_sessions`

運用ルール:

- 同じ `run_fingerprint` の再実行では `source_runs` row を再利用する
- 再実行時は既存 row を更新し、関連 `observations` を全置換する
- これにより duplicate write を避けつつ、最新の source 結果へ追従する

## `observations` Fixed Fields

- `source_run_id`
- `event_fingerprint`
- `source_name`
- `scope_mode`
- `occurred_at`
- `event_type`
- `summary`
- `confidence`
- `details_json`
- `event_json`
- `collected_at`

`event_json` は normalized event contract を再構成できる shape を保持する。

## Observation Fingerprint Policy

`event_fingerprint` は normalized event の次の logical fields から `sha256` で作る。

- `source`
- `timestamp`
- `type`
- `summary`
- `details`
- `confidence`

含めないもの:

- `source_run_id`
- `group_id`
- DB row id
- ingest timestamp

理由:

- `observations` は raw normalized event を表す層であり、grouping や persistence 上の付帯情報では identity を変えない
- 後続の `activities` derivation に進んだ時も、event identity を stable に保ちやすい

## Rebuild Rule

- DB は rebuildable cache / index とみなす
- DB を削除しても、同じ source collect を再実行すれば `source_runs` と `observations` を再作成できる
- `AR2` の回帰テストでは、削除後の再 ingest で件数が復元されることを確認する
