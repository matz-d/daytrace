# DayTrace Store Run Context Note

`AR2` で固定する `source_runs` / `observations` 保存方針。

## Store Boundary

- `aggregate.py` は compatibility shell のまま残す
- source collect / normalize 後に `store.py` へ永続化を委譲する
- grouping 済みの `groups` はまだ保存しない
- `observations` は grouped data ではなく normalized event 単位で保存する

運用ポリシー:

- store は rebuildable な best-effort cache として扱う
- store 書き込み失敗は warning として残し、本処理の JSON payload 自体は返す
- store slice を読む側は保存済みであることだけで信用せず、`completeness` を評価してから再利用する

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

- `requested_date` は `--date today` / `yesterday` を正規化した ISO 日付を保持する
- `since_value` / `until_value` は実際に source command へ forward した resolved filter を保持する
- 元の shorthand を残したい場合は `filters_json` に持たせる
- `filters_json` は将来の拡張用に opaque JSON として残す

## Run Identity And Idempotency

`source_runs.run_fingerprint` は次の組み合わせで固定する。

- `source_identity`
- `manifest_fingerprint`
- `command_fingerprint`
- `workspace`
- `requested_date`
- `since_value`
- `until_value`
- `all_sessions`

補足:

- fingerprint 対象の `since_value` / `until_value` は、source command へ実際に forward した resolved filter 値を指す
- 実装上の一時変数名が `since` / `until` でも、永続化上の正準名は `since_value` / `until_value` とする

運用ルール:

- 同じ `run_fingerprint` の再実行では `source_runs` row を再利用する
- 再実行時は既存 row を更新し、関連 `observations` を全置換する
- これにより duplicate write を避けつつ、最新の source 結果へ追従する

補足:

- `aggregate_core.resolve_command_paths()` は script basename 前提の解決をしている
- basename 前提の全面見直しは AR5 で扱い、この note では現行挙動として固定する

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

DB field mapping:

- logical `source` -> normalized event の `source` -> `observations.source_name`
- logical `timestamp` -> normalized event の `timestamp` -> `observations.occurred_at`
- logical `type` -> normalized event の `type` -> `observations.event_type`
- logical `summary` -> normalized event の `summary` -> `observations.summary`
- logical `details` -> normalized event の `details` -> `observations.details_json`
- logical `confidence` -> normalized event の `confidence` -> `observations.confidence`

明示ルール:

- `scope_mode` は `observations` row に保存するが、`event_fingerprint` には含めない
- `source` は normalized event の source 名だけを指し、`scope_mode` を内包しない
- fingerprint は DB row ではなく normalized event contract を基準に計算する

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
