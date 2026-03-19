# Store and Observation Model

このドキュメントは、DayTrace のローカル蓄積基盤を実装者向けに説明するためのもの。
source の生ログ、正規化された観測、derived layer、completeness、fail-soft の関係を一箇所にまとめる。

## 1. 目的

### 何を store するのか

- **`source_runs`**: source ごとの実行メタデータ（いつ・どの条件で・どのソースを実行したか）
- **`observations`**: 正規化された個別イベント（normalized event 単位）
- **`activities`**: `observations` を grouping semantics で束ねた derived layer（aggregate の `groups[]` 相当）
- **`patterns`**: `skill_miner_prepare.py` が生成した candidates を保存した derived layer

### なぜ store するのか

- **再利用**: 同じ日付・workspace・条件での aggregate を毎回再実行せず、store から読み出す
- **一貫性**: projection adapter を通じて、`daily-report` / `post-draft` が同じ derived data を参照する
- **共有**: `skill-miner` が生成した `patterns` を `post_draft_projection.py` が参照できる

### raw history と何が違うのか

raw history（`.jsonl` ファイルなど）は source ごとの生データで、フォーマットが異なる。
store は全 source を **Source CLI Contract** に従って正規化したイベントを保持するため、downstream が source 固有のフォーマットを知らなくても消費できる。

## 2. データの流れ

```
Raw logs
(~/.claude/projects/**/*.jsonl, git log, Chrome DB, ...)
        │
        ▼
Source CLIs (git_history.py, claude_history.py, ...)
  → 正規化された events[] を stdout JSON で返す
        │
        ▼
aggregate.py
  → source_runs へ upsert（run_fingerprint で冪等）
  → observations へ insert（event_fingerprint で dedup）
        │
        ├──→ activities（aggregate_core.build_groups() で導出）
        │       ↑ daily_report_projection.py / post_draft_projection.py が参照
        │
        └──→ patterns（skill_miner_prepare.py の candidates[] から導出）
                ↑ post_draft_projection.py が cached patterns として参照
```

## 3. テーブル構成

store path のデフォルト: `~/.daytrace/daytrace.sqlite3`（schema version: 3）

### 3-1. `source_runs`

source の 1 回の実行を表すレコード。`run_fingerprint` で一意に識別される。

| カラム | 型 | 役割 |
|-------|-----|-----|
| `run_fingerprint` | TEXT UNIQUE | 実行の一意識別子（後述） |
| `source_name` | TEXT | source の名前（例: `git-history`） |
| `source_id` | TEXT | `sources.json` の `name`（= `source_name`） |
| `identity_version` | TEXT | source identity のバージョン |
| `manifest_fingerprint` | TEXT | `sources.json` の論理フィールドから導出したフィンガープリント |
| `confidence_categories_json` | TEXT | JSON配列（例: `["git"]`, `["ai_history"]`） |
| `command_fingerprint` | TEXT | 実際に実行したコマンドの hash |
| `status` | TEXT | `success` / `skipped` / `error` |
| `scope_mode` | TEXT | `all-day` / `workspace` |
| `workspace` | TEXT | 絶対パス |
| `requested_date` | TEXT | `--date` で解決した ISO 日付（例: `2026-03-16`） |
| `since_value` | TEXT | source command へ forward した since（resolved 値） |
| `until_value` | TEXT | source command へ forward した until（resolved 値） |
| `all_sessions` | INTEGER | 0 / 1 |
| `filters_json` | TEXT | 拡張用 opaque JSON（将来の filter 追加に対応） |
| `command_json` | TEXT | 実際に実行したコマンド配列 |
| `reason` | TEXT | skipped 時の理由（nullable） |
| `message` | TEXT | error 時のメッセージ（nullable） |
| `duration_sec` | REAL | 実行時間（秒） |
| `events_count` | INTEGER | 収集したイベント件数 |
| `collected_at` | TEXT | ISO 8601 タイムスタンプ |

**インデックス**:
- `(source_name, collected_at)` — source 別の最新取得クエリ用
- `(workspace, since_value, until_value, all_sessions)` — slice 検索用

### 3-2. `observations`

正規化された個別イベント。source_runs に紐付く。

| カラム | 型 | 役割 |
|-------|-----|-----|
| `source_run_id` | INTEGER | `source_runs.id` への FK（CASCADE DELETE） |
| `event_fingerprint` | TEXT | 正規化イベントの一意識別子（後述） |
| `observation_kind` | TEXT | `event`（通常イベント）または `packet`（AI history の logical packet） |
| `source_name` | TEXT | source の名前 |
| `scope_mode` | TEXT | `all-day` / `workspace` |
| `occurred_at` | TEXT | イベントの発生日時（ISO 8601） |
| `event_type` | TEXT | イベント種別（例: `commit`, `conversation`） |
| `summary` | TEXT | 短い概要文字列 |
| `confidence` | TEXT | `high` / `medium` / `low` |
| `details_json` | TEXT | source 固有の詳細（JSON） |
| `event_json` | TEXT | normalized event contract を再構成できる JSON |
| `collected_at` | TEXT | ISO 8601 タイムスタンプ |

**インデックス**:
- `(occurred_at)` — 日時範囲クエリ用
- `(source_name, occurred_at)` — source + 日時の複合クエリ用

AI history source（`claude-history` / `codex-history`）は `details.ai_observation_packets[]` に logical packet を持つ場合があり、その場合はイベント本体（`observation_kind='event'`）に加えて packet 単位の sub-observation（`observation_kind='packet'`）も挿入される。

### 3-3. `activities`

`observations` から grouping semantics で束ねた derived layer。
`aggregate_core.build_groups()` と同じルールで導出される。

| カラム | 型 | 役割 |
|-------|-----|-----|
| `query_fingerprint` | TEXT | クエリ文脈の一意識別子（workspace + since + until + all_sessions + group_window + max_span + derivation_version） |
| `derivation_version` | TEXT | `activities-v2` |
| `input_fingerprint` | TEXT | 入力 observations の hash（stale 判定に使う） |
| `workspace` | TEXT | 絶対パス（nullable） |
| `since_value` | TEXT | クエリ期間の開始 |
| `until_value` | TEXT | クエリ期間の終了 |
| `group_window_minutes` | INTEGER | グルーピング窓（デフォルト 15 分） |
| `activity_id` | TEXT | activity の一意識別子 |
| `start_timestamp` | TEXT | グループ内最初のイベント日時 |
| `end_timestamp` | TEXT | グループ内最後のイベント日時 |
| `summary` | TEXT | グループ概要 |
| `confidence` | TEXT | `high` / `medium` / `low` |
| `sources_json` | TEXT | グループを構成する source 名の配列 |
| `confidence_categories_json` | TEXT | グループの confidence_category 配列 |
| `source_count` | INTEGER | ユニーク source 数 |
| `event_count` | INTEGER | グループ内イベント数 |
| `evidence_json` | TEXT | 代表イベントの配列（aggregate の `groups[].evidence` 相当） |
| `observation_fingerprints_json` | TEXT | グループを構成する observation の fingerprint 配列 |
| `activity_json` | TEXT | `aggregate.py` の `groups[]` エントリと同型の payload |
| `derived_at` | TEXT | derived した日時 |

UNIQUE制約: `(query_fingerprint, activity_id)` — 同一クエリ文脈内で activity_id は一意

補足（`max_span_minutes` カラムがない理由）:
- `max_span_minutes` は固定値ではなく可変（デフォルト 60、CLI で上書き可能）
- `activities` の再利用判定は `query_fingerprint`（slice 選択）と `input_fingerprint`（stale 判定）で完結するため、専用カラムがなくても正しくキャッシュ分離される
- 現在は `group_window_minutes` だけを列として保持し、`max_span_minutes` は fingerprint 入力と projection の `config.max_span_minutes` で追跡する設計

### 3-4. `patterns`

`skill_miner_prepare.py` の `candidates[]` を薄い persistence layer として保存したもの。

| カラム | 型 | 役割 |
|-------|-----|-----|
| `query_fingerprint` | TEXT | クエリ文脈の一意識別子 |
| `pattern_kind` | TEXT | `skill-miner-candidate`（現在は固定） |
| `pattern_key` | TEXT | `candidates[].candidate_id` |
| `derivation_version` | TEXT | `skill-miner-candidate-v1` |
| `input_fingerprint` | TEXT | prepare 出力の hash（stale 判定に使う） |
| `workspace` | TEXT | 絶対パス（nullable） |
| `observation_mode` | TEXT | `workspace` / `all-sessions` |
| `days` | INTEGER | 観測窓（日数） |
| `label` | TEXT | candidate のラベル |
| `score` | REAL | candidate のスコア |
| `support_json` | TEXT | `candidates[].support`（出現回数・source 多様性等） |
| `pattern_json` | TEXT | candidate オブジェクト全体 |
| `derived_at` | TEXT | derived した日時 |

UNIQUE制約: `(query_fingerprint, pattern_kind, pattern_key)`

## 4. Derived Layer の考え方

### 4-1. observations → activities

`get_activities(...)` が呼ばれると:

1. 同一 `query_fingerprint` の row を取得
2. `input_fingerprint` が現在の observations の hash と一致するか確認
3. 一致 → そのまま返す（再利用）
4. 不一致または row なし → `aggregate_core.build_groups()` と同じルールで全置換する（rebuild）

confidence の導出ルール（`aggregate_core` から継承）:
- `git` + `ai_history` の両方を含むグループ → `high`
- `git` または `ai_history` のいずれか → `medium`
- それ以外 → `low`

`activities[].activity_json` は current `groups[]` と同型の payload を保持するため、downstream skill は `aggregate.py` の出力と同じコードで読める。

`aggregate_core.build_groups()` の具体ルール:

1. `timeline[]` を timestamp 昇順で走査する
2. 先頭 event から group を開始する
3. 次 event が現在 group の `end` から `group_window_minutes` 以内なら同じ group に連結する
4. 超えたら新しい group を開始する
5. group ごとに `id`, `start_timestamp`, `end_timestamp`, `sources`, `confidence_categories`, `event_count`, `evidence`, `events` を導出する

派生フィールドの current semantics:

- `group_window_minutes`: デフォルト 15
- `max_span_minutes`: デフォルト 60。rolling-chain による無制限拡大を防ぐ
- `summary`: 単一 event の場合はその `summary`、複数 event の場合は `"{n} activities from {sources}"` の汎用表現
- `evidence_json`: group 先頭から最大 5 件の event の `timestamp`, `source`, `type`, `summary`
- `confidence`: source 名から引いた `confidence_category` の集合だけで決まる
- `activity_json.events[]`: 元の normalized event をそのまま保持し、各 event には `group_id` が付く

重要な制約:

- `activities` は semantic cluster ではなく **time-window based activity blocks**
- したがって `daily-report` / `post-draft` の上位 skill は、ここから「その時間帯に何が起きたか」を再構成するが、「本当に詰まったこと」や「次にやること」までは決定論的には確定できない
- narrative や action inference の精度は `activities` 自体よりも、downstream skill の abstain / confidence policy に強く依存する

### 4-2. prepare → patterns

`persist_patterns_from_prepare(...)` が呼ばれると:

1. 同一 `query_fingerprint` の既存 patterns row を全削除
2. `prepare_payload.candidates[]` を `patterns` テーブルへ全挿入
3. `unclustered[]` は patterns 化しない

stale 判定の主根拠は `input_fingerprint` の mismatch。

### 4-3. derivation version

version を上げる条件:
- grouping semantics が変わる
- persisted field shape が変わる
- fingerprint 入力が変わる

現行バージョン:
- `activities`: `activities-v2`
- `patterns`: `skill-miner-candidate-v1`

## 5. Query Context と Fingerprint

### Run Fingerprint（`source_runs`）

`source_runs.run_fingerprint` は以下の組み合わせを `sha256` で hash したもの:

- `source_identity`（= `source_id` + `identity_version`）
- `manifest_fingerprint`（sources.json の論理フィールドから導出）
- `command_fingerprint`（実際に実行したコマンドの hash）
- `workspace`（絶対パス）
- `requested_date`（ISO 日付）
- `since_value`（resolved フィルタ値）
- `until_value`（resolved フィルタ値）
- `all_sessions`（boolean）

**冪等性**: 同一 `run_fingerprint` の再実行では `source_runs` row を UPDATE し、関連 `observations` を全置換する。

### Observation Fingerprint（`observations`）

`event_fingerprint` は normalized event の以下のフィールドを `sha256` で hash したもの:

- `source`, `timestamp`, `type`, `summary`, `details`, `confidence`

**含めないもの**: `scope_mode`, `source_run_id`, DB row id, ingest timestamp

理由: observations は「raw normalized event を表す層」であり、grouping や persistence 上の付帯情報では identity を変えない。

### Activity Query / Input Fingerprint（`activities`）

`activities` のキャッシュ一致判定には 2 種類の fingerprint を使う:

- `query_fingerprint`（どの slice を読むか）
  - 入力: `derivation_version`, `workspace`, `requested_date`, `since`, `until`, `all_sessions`, `group_window_minutes`, `max_span_minutes`
  - `max_span_minutes` が違うと hash が必ず変わるため、同じ日付・workspace でも別キャッシュとして扱われる
- `input_fingerprint`（既存 slice が stale か）
  - 入力: `derivation_version`, `group_window_minutes`, `max_span_minutes`, `observation_fingerprints`, `confidence_categories_by_source`
  - 同じ `query_fingerprint` でも、入力観測または grouping パラメータが変わると mismatch になり再導出される

`max_span_minutes` について:
- デフォルトは `60` だが、`aggregate.py --max-span` / projection 系 CLI の `--max-span` で変更できる
- `0` は無効化（span 制約なし）
- したがって `max_span_minutes` は「versioning のための固定定数」ではなく、cache key に含めるべき実行パラメータ

### Manifest Fingerprint

`sources.json` の各 source エントリの **論理フィールドのみ**から導出（`required`, `timeout_sec`, `platforms` などの runtime orchestration fields は除外）。
これにより、実行制御パラメータが変わっても fingerprint は変わらない。

## 6. Slice Completeness

### 6-1. 状態定義

projection adapter が store slice を読む際に評価する completeness:

| 状態 | 意味 |
|------|------|
| `complete` | 全 source が success、現行マニフェストと fingerprint が一致 |
| `partial` | 一部 source が skipped または error（データは一部欠損） |
| `degraded` | 重要な source（git, ai_history）が欠けている |
| `stale` | マニフェスト変更後に slice が更新されていない |
| `empty` | 該当 slice が存在しない（hydrate が必要） |

### 6-2. いつ hydrate するか

`daily_report_projection.py` / `post_draft_projection.py` の動作:

1. store に完全な slice あり（`complete` または `partial` で十分） → store から activities を読んで返す
2. slice なし（`empty`）または `stale` → `aggregate.py` を 1 回実行して hydrate → store に保存 → 返す

### 6-3. いつ raw fallback するか

`skill_miner_prepare.py --input-source auto` の動作:

1. store の claude-history / codex-history slice が `complete` かつ現行マニフェストと一致 → store-backed path
2. それ以外（`partial`, `degraded`, `stale`, `empty`, 未検証） → raw history に直接フォールバック

`--compare-legacy` を付けると store path と raw path の比較サマリを返す（移行期の整合性確認用）。

## 7. Fidelity

`observations` に保存されるデータの忠実度レベル:

| Fidelity | 意味 | 例 |
|---------|------|-----|
| `original` | 生データをそのまま保持 | git commit の生メッセージ |
| `canonical` | 正規化した値（後から再現可能） | timestamp を ISO 8601 に統一 |
| `approximate` | 近似・要約（元を完全には再現できない） | 長い会話を短い summary に圧縮したもの |

`skill_miner_prepare.py` は canonical packet payload を `observations.details_json` 内に保存する（AR4 以降）。
これにより store-backed prepare が raw history と同等の packet を再構成できる。

## 8. Fail-soft と再構築性

### store write failure

store への書き込みが失敗した場合:
- warning として `stderr` に記録する
- 本処理の JSON payload（`aggregate.py` の stdout）は正常に返す
- 次回の実行で再 ingest できる

### corrupted JSON columns

`derived_store.py` は JSON デコード時に安全なフォールバックを持ち、パースエラーは `decode_warnings` として payload に記録する。corrupted な 1 カラムで全レコードが読めなくなることはない。

### `--no-store`

`aggregate.py --no-store` を付けると、その 1 回の実行だけ SQLite への書き込みをスキップする。
store なしで aggregate 結果を確認したい場合や、CI / テスト環境での利用に向く。

### rebuildable cache

store は **rebuildable best-effort cache** として扱う:
- store を削除しても、同じ source collect を再実行すれば完全に再作成できる
- `source_runs` と `observations` の rebuild は aggregate.py の再実行で完了する
- `activities` と `patterns` は上位レイヤが再 derive して自動再構成する

## 9. mixed-scope との関係

### `all-day` vs `workspace`

`sources.json` の `scope_mode` がこの区分を定義する:

| source | scope_mode |
|--------|-----------|
| `git-history` | `workspace` |
| `claude-history` | `all-day` |
| `codex-history` | `all-day` |
| `chrome-history` | `all-day` |
| `workspace-file-activity` | `workspace` |

### scope はどこに保存されるか

- `source_runs.scope_mode`: source 実行単位で保存
- `observations.scope_mode`: 個別イベント単位でも複製して保存（`activities` 導出時に source を特定せず scope で判断できるようにするため）

### downstream でどう使うか

- `aggregate.py` は `sources[].scope` を返すため、skill は `sources[]` を読んで mixed-scope を把握できる
- `all-day` と `workspace` の両方が含まれる場合、`daily-report` / `post-draft` は冒頭に mixed-scope 注記を入れる
- `workspace` 指定があっても `all-day` source までは絞り込まれないため、`all-day` の証跡を workspace 限定として扱わない

## 10. 運用上の確認ポイント

### store path

- デフォルト: `~/.daytrace/daytrace.sqlite3`
- override: `aggregate.py --store-path /path/to/daytrace.sqlite3`
- 権限確認: `~/.daytrace/` ディレクトリが存在するか、または書き込み権限があるか

### warm store（ウォームストア）

store に slice がある状態を「warm」と呼ぶ。warm state では projection adapter が `aggregate.py` を再実行せず高速に返す。
初回実行 or `--no-store` 実行後は cold state（`aggregate.py` の実行が必要）。

### schema version

`PRAGMA user_version` で確認できる。現行は `3`。
version 1 から 2 への自動マイグレーション（`confidence_categories_json` カラム追加）および version 2 から 3 への自動マイグレーション（`observation_kind` カラム追加）はいずれも `bootstrap_store()` が担う。

### local-only assumptions

- store は `~/.daytrace/` に置かれるローカルファイルであり、外部への送信は一切行わない
- store path を指定することで複数環境での分離や CI での使い捨て store も可能

## 11. 関連ドキュメント

- `plugins/daytrace/scripts/README.md`: Source CLI Contract、aggregator output shape、skill-miner CLI 仕様
- `plugins/daytrace/scripts/store-run-context-note.md`: `source_runs` / `observations` の保存方針と fingerprint policy（scripts/ 内に配置）
