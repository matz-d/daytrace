# DayTrace Derived Layer Note

`AR3` で固定する `observations -> activities` / `skill-miner prepare -> patterns` / versioning 方針。

## Layer Boundary

- `observations`
  - normalized event 単位を保持する raw-ish store layer
  - source 実行結果の再構成に使う
- `activities`
  - `observations` を aggregate-style grouping semantics で束ねた derived layer
  - `aggregate.py` の current `groups[]` semantics にできるだけ忠実に保つ
- `patterns`
  - current `skill_miner_prepare.py` の candidate output を保存する initial derived layer
  - narrative logic や prose generation は吸わない

## `observations -> activities` Mapping

初期実装では、stored `observations` の `event_json` を timeline として読み出し、`aggregate_core.build_groups()` と同じ grouping rule で `activities` を導出する。

入力:

- `event_json`
- `event_fingerprint`
- `source_name`
- `scope_mode`
- `occurred_at`
- source run に保存した `confidence_categories_json`

導出ルール:

- grouping window は `group_window_minutes` で固定する
- timeline は `occurred_at` 昇順で評価する
- confidence は current aggregate と同じ `git + ai_history = high`, `git or ai_history = medium`, その他 `low`
- `activities[].activity_json` には current `groups[]` と同型の payload を保持する
- constituent observation は `observation_fingerprints_json` で追跡する

保持しないもの:

- prose summary の追加解釈
- downstream skill 固有の narrative selection

## `skill-miner prepare -> patterns` Mapping

初期 `patterns` は raw history から直接 derive せず、current `skill_miner_prepare.py` output の `candidates[]` を保存する thin persistence layer とする。

入力:

- `prepare_payload.config`
- `prepare_payload.summary`
- `prepare_payload.candidates[]`

初期対応:

- `patterns.pattern_kind = "skill-miner-candidate"`
- `patterns.pattern_key = candidates[].candidate_id`
- `patterns.label = candidates[].label`
- `patterns.score = candidates[].score`
- `patterns.support_json = candidates[].support`
- `patterns.pattern_json = candidate object 全体`

この段階では:

- `unclustered[]` は patterns 化しない
- candidate 生成ロジック自体は `skill_miner_prepare.py` 側に残す
- stale refresh は `prepare` 再実行と再保存で行う

## Derivation Version

- activities: `activities-v1`
- patterns: `skill-miner-candidate-v1`

version を上げる条件:

- grouping semantics が変わる
- persisted field shape が変わる
- fingerprint 入力が変わる

## Input Fingerprint Policy

### activities

`activities.input_fingerprint` は次を hash したものとする。

- ordered `event_fingerprint`
- `group_window_minutes`
- source ごとの `confidence_categories`
- `activities` derivation version

### patterns

`patterns.input_fingerprint` は次を hash したものとする。

- `prepare_payload.config` の query 文脈
- `prepare_payload.summary`
- 各 candidate の `candidate_id`, `label`, `score`, `support`, `session_refs`, `evidence_items`
- pattern derivation version

## Rebuild Rule

- `activities`
  - `get_activities(...)` 呼び出し時に、query context ごとの persisted rows と current input fingerprint を比較する
  - row が無い、または fingerprint がずれる場合はその query context を全置換する
- `patterns`
  - `persist_patterns_from_prepare(...)` 呼び出し時に同じ query context の rows を全置換する
  - stale 判定の主根拠は input fingerprint mismatch とする

## Query Surface

generic query builder は作らず、まずは次の明示関数に限定する。

- `get_observations(...)`
- `get_activities(...)`
- `get_patterns(...)`
