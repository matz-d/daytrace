# DayTrace アーキテクチャ刷新 親プラン

## 目的

このプランは、現在の DayTrace コードベースを、既存の plugin UX・CLI 契約・local-first 制約を壊さずに、より整理された内部アーキテクチャへ段階的に進化させるための親プランである。

目標はリライトではない。
目標は、今うまく動いているものを守りながら、再利用・キャッシュ・拡張に耐える内部構造へ安全に移行することだ。

## 現状認識

現行リポジトリには、すでに良い土台がある。

- source 契約は `plugins/daytrace/scripts/sources.json` に明示されている
- orchestration は `plugins/daytrace/scripts/aggregate.py` に集中している
- 共有ユーティリティは `plugins/daytrace/scripts/common.py` にある
- 出力責務は `daily-report` / `post-draft` / `skill-miner` に分かれている
- テストには unit 的な helper テストと CLI shape テストがすでにある

現在の内部の重さは、計画順序を決める上で重要である。

- `plugins/daytrace/scripts/common.py`: 200 行
- `plugins/daytrace/scripts/aggregate.py`: 541 行
- `plugins/daytrace/scripts/skill_miner_prepare.py`: 859 行
- `plugins/daytrace/scripts/skill_miner_common.py`: 1260 行

ここから分かること:

- 最初に価値が高い抽出対象は `common.py` ではなく `aggregate.py`
- `skill-miner` は大きなサブシステムなので最後に移行すべき
- 広い再設計より、互換性テストを先に固める方が安全

## 変更しない前提

移行中も、以下の制約は固定する。

- `stdlib only`
- `network-free`
- `local-first`
- 既存 Source CLI の stdout JSON 契約
- 移行期間中の `aggregate.py` 出力形状
- 既存 3 skill のユーザー向け entrypoint

## 設計の到達像

将来の内部モデルは以下を目指す。

```text
built-in sources + user drop-in sources
  -> source registry
  -> ingest / normalize
  -> SQLite store
  -> derived layers
     - observations
     - activities
     - patterns
  -> projections
     - daily-report
     - post-draft
     - skill-miner
  -> interfaces
     - aggregate.py compatibility JSON
     - plugin skills
```

## 中核アーキテクチャ判断

### 1. `aggregate.py` は互換シェルとして残す

`aggregate.py` は早い段階で消さない。
抽出した core logic と、将来的には store-backed query を包む compatibility shell にする。

### 2. skill DAG ではなく derived-data DAG を採用する

skill 同士を直接依存させない。
共通の machine-readable layer に依存させる。

```text
sources
  -> observations
  -> activities
  -> patterns
  -> renders
```

利用イメージ:

- `daily-report` は `activities` を読む
- `post-draft` は `activities` と必要に応じて `patterns` を読む
- `skill-miner` は `observations` と `patterns` を読む

### 3. SQLite は再構築可能な基盤として扱う

SQLite は source of truth ではない。
繰り返し利用を安く・きれいにするための、再構築可能な cache / index / persistence layer である。

DB が消えても、source CLI を再実行すれば必要な状態を再構築できなければならない。

### 4. query API は意図的に単純に保つ

store / query 層は、generic query builder ではなく、直接的な Python 関数から始める。

例:

- `get_observations(date, workspace=None, all_sessions=False)`
- `get_activities(date, workspace=None, all_sessions=False)`
- `get_patterns(days=7, workspace=None, all_sessions=False)`

現時点の consumer は少数であり、generic query language は早すぎる。

### 5. 保存データは「収集コンテキスト」を再現できること

DayTrace は mixed-scope を明示的に扱う。
そのため store は event 本体だけでなく、「どの条件で集めたか」を後から再現できなければならない。

最低限、以下の軸を保存対象に含める。

- source 名
- source の `scope_mode`
- workspace
- `date` / `since` / `until`
- `all_sessions`
- source manifest fingerprint または同等の source identity
- command fingerprint が必要ならその値

### 6. 派生データは versioned かつ rebuildable であること

`activities` と `patterns` は raw event の単純コピーではない。
grouping window や pattern 抽出ロジックが変われば再計算が必要になる。

そのため派生データには、少なくとも以下の概念が必要である。

- derivation version
- input fingerprint
- 再計算ルール
- stale 判定ルール

これらは TODO 4 以降で必須だが、TODO 2 の schema 設計時点から将来の拡張余地を確保する。

## 共有データモデル

### `source_runs`

source 実行単位のメタデータを保存する。

最低限の想定項目:

- source name
- status
- duration
- workspace
- date / since / until / all_sessions
- scope_mode
- skip reason / error message
- source manifest fingerprint
- command fingerprint
- 実行時刻

補足:

- `filters` は opaque JSON でもよいが、主要な問い合わせ軸は列として引ける形にしておく
- mixed-scope の再投影に必要な項目は `source_runs` だけ見ても分かるようにする

### `observations`

正規化済み source event を保存する。

初期定義:

- 現在の `timeline` event 単位の永続化版
- 各 row は、既存 source CLI が返す event 契約にできるだけ近く保つ

最低限の想定項目:

- source_run_id
- source name
- scope_mode
- occurred_at
- event type
- summary
- details payload
- event fingerprint
- 元 event 契約を再構成できる情報

### `activities`

grouped activity 単位を保存する。

初期定義:

- 現在の `aggregate.py` が作る `groups` の永続化版
- 最初の移行では、現在の 15 分 grouping semantics にできるだけ近く保つ
- 最初の段階で概念を広げない

追加要件:

- derivation version を持つ
- input fingerprint を持つ
- `group_window` など grouping 条件を再現できる

### `patterns`

`skill-miner` が使う repeated-pattern artifact を保存する。

初期定義:

- v1 では generic pattern engine にしない
- `skill_miner_prepare.py` が暗に持っている有用な machine-readable output の永続化版とする
- まずは compressed candidate 指向の構造から始める

追加要件:

- derivation version を持つ
- input fingerprint を持つ
- projection logic を吸い込みすぎない

### `renders`

最終生成物を保存して再現性や cache に使いたい場合の層。

これは将来の拡張候補としてのみ扱う。
本プランの 5 TODO の deliverable には含めず、他の移行をブロックしてはならない。

## 境界定義

スコープ拡大を防ぐため、以下の境界を先に固定する。

### observations と activities

- `observations` は単一の正規化 event
- `activities` は近接 `observations` をまとめた grouped window
- 最初の移行では、現在の `timeline -> groups` 関係にできるだけ忠実であること

### activities と patterns

- `activities` は 1 つの期間に何が起きたかを表す
- `patterns` は複数期間・複数 session にまたがる反復を表す
- `patterns` は `daily-report` / `post-draft` の narrative logic を吸収しない

### patterns と skill output

- `patterns` は machine-readable な evidence structure
- 提案文、分類説明、最終 markdown は projection logic の責務

## 互換性コミットメント

移行中、以下の interface は安定に保つ。

- `plugins/daytrace/scripts/sources.json`
- source CLI stdout JSON shape
- `plugins/daytrace/scripts/aggregate.py` の top-level JSON shape
- 現在の skill invocation flow

ただし、ここでいう「互換性」は top-level key の存在だけでは足りない。
downstream skill が依存している nested field と意味論も保護対象とする。

## 互換性マトリクス

TODO 1 で明文化し、以後の refactor の判定基準にする。

### `aggregate.py` top-level

必須:

- `status`
- `generated_at`
- `workspace`
- `filters`
- `config`
- `sources`
- `timeline`
- `groups`
- `summary`

### `sources[]`

少なくとも以下を互換対象とする。

- `name`
- `status`
- `scope`
- `events_count`
- optional: `reason`, `message`, `command`, `duration_sec`

意味論:

- `scope` は source manifest の `scope_mode` をそのまま downstream に見せる
- `status` は `success` / `skipped` / `error`

### `timeline[]`

少なくとも以下を互換対象とする。

- `source`
- `timestamp`
- `type`
- `summary`
- `details`
- `confidence`
- `group_id` during grouping path

意味論:

- timestamp 昇順で安定ソートされる
- source event 契約を再構成できる

### `groups[]`

少なくとも以下を互換対象とする。

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
- `confidence` は既存カテゴリ解釈と互換
- `events` は downstream skill が narrative / report 用に読める粒度を保つ

### `summary`

少なくとも以下を互換対象とする。

- `source_status_counts`
- `total_events`
- `total_groups`
- `no_sources_available`

意味論:

- downstream skill は `source_status_counts` を優先参照できる
- `no_sources_available` は空結果メタ情報として維持する

## 作業計画

移行は 5 つの TODO に分ける。

## TODO 1. 契約ベースライン確立と Core Extraction

### 目的

まず外部挙動を固定し、その後で `aggregate.py` から再利用可能な orchestration logic を抽出する。

### なぜ最初か

後続のすべての refactor に対する safety rail になるため。
また、現時点で中央にあり、かつまだ安全に切り出せるサイズなのが `aggregate.py` だから。

### 明示的な抽出対象

主対象は `plugins/daytrace/scripts/aggregate.py` の以下。

- `resolve_date_filters`
- `build_command`
- `normalize_event`
- `group_confidence`
- `build_groups`
- `build_summary`

加えて、必要に応じて以下も抽出候補とする。

- source selection / preflight evaluation
- source result normalization
- compatibility payload assembly

`common.py` は責務整理に必要な範囲だけ触る。
この TODO は「`common.py` を広く分割する」作業ではない。

### 契約保護で追加すること

移動前に、互換性テストを強化する。

必須追加:

- aggregate top-level だけでなく nested output-shape 契約の明示的テスト
- source CLI の success / skipped / error shape 契約テストの補強
- `scope` metadata と filter forwarding の回帰テスト
- `groups[]` / `timeline[]` / `summary` の意味論に関する回帰テスト
- `daily-report` / `post-draft` が依存する aggregate field についての smoke-level 保護

契約テストは `test_aggregate_contracts.py` として独立ファイルに配置する。
既存の `test_skill_miner_contracts.py` と同じパターンに揃える。

### 推奨する内部分割

この TODO は実行上は以下の 2 段に分ける。

- 1a: 契約テストと互換性マトリクスの固定
- 1b: extraction と `aggregate.py` の薄化

これにより、contract baseline の確立と code movement を別 deliverable として扱えるようにする。

### Deliverables

- time / scope / grouping / confidence などの抽出 module
- `aggregate.py` が抽出 logic を呼ぶ構成
- 強化された contract-oriented tests
- 互換性マトリクスの文書化

### Done Criteria

- 抽出 module は CLI を呼ばずにテストできる
- aggregate CLI の挙動は互換
- top-level だけでなく nested contract テストが通る
- downstream skill が依存する aggregate 契約が明文化されている

## TODO 2. Store Introduction

### 目的

run metadata と normalized event を保存する、再構築可能な SQLite 層を導入する。

### Scope

最初は以下に限定する。

- `source_runs`
- `observations`

`activities` や `patterns` をこの TODO の blocker にしない。

### 事前条件

store schema を確定する前に、少なくとも以下は内部契約として先に固定する。

- source identity の定義
- source manifest fingerprint の扱い
- mixed-scope を再現するための収集コンテキスト項目

この時点では user drop-in source の実装完了までは不要だが、store が built-in 専用前提になってはならない。

### 並行設計要件

TODO 3 で user drop-in source を入れる前提で、manifest shape の draft を TODO 2 中に書く。

最低限含める項目:

- `name`
- `command`
- `scope_mode`
- `supports_date_range`
- `supports_all_sessions`
- `confidence_category`
- prerequisites metadata

### idempotency / consistency 要件

最低限、以下を決める。

- rerun 時の duplicate write 制御
- 同一 source / 同一収集条件の再実行時の扱い
- `observations` の fingerprint 方針
- DB を消して再実行した時の復元条件

### Deliverables

- SQLite schema と migration bootstrap
- source CLI result を `source_runs` / `observations` に ingest する経路
- rerun idempotency ルール
- source-agnostic な manifest draft note
- 収集コンテキスト保存方針の文書化

### Done Criteria

- source 実行結果を永続化できる
- duplicate write が制御されている
- DB を削除して source を再実行すると必要データが復元される
- mixed-scope を再投影するのに必要な run context が保存される

## TODO 3. Source Registry Redesign

### 目的

built-in source と user-provided source を単一の registry model に統合する。

この TODO はアーキテクチャ刷新の前提条件ではない。
core refresh 完了後に独立拡張として進められるように設計し、TODO 4-5 の blocker にはしない。

### Scope

- 既存 `sources.json` は built-in registry として残す
- user drop-in manifest format を定義する
- user config directory からの discovery をサポートする
- manifest validation と preflight handling を一元化する

### 提案する user drop-in location

- `~/.config/daytrace/sources.d/`

### ルール

- built-in / user source は同じ internal registry API を通る
- invalid manifest は clear かつ machine-readable に失敗する
- registry logic は current built-in source の挙動と互換である
- TODO 2 で定めた source identity / manifest fingerprint と矛盾しない

### Deliverables

- built-in / user manifest を読む registry loader
- source manifest schema validation
- 統一された preflight evaluation path
- source identity / registry API の文書化

### Done Criteria

- built-in source は従来通り動く
- 少なくとも 1 つの user source を discovery して実行できる
- invalid manifest が明確に報告される
- store ingest が registry redesign により再設計を強いられない

## TODO 4. Derived Layers

### 目的

raw observations の上に、再利用可能な machine-readable layer を作る。

### 重要な事前条件

実装前に、短い design note を書いて以下を固定する。

- 初期の `observations -> activities` mapping
- 初期の `skill-miner prepare output -> patterns` mapping
- どこまでが persisted derived data で、どこからが projection logic か
- derivation version / input fingerprint / rebuild rule

この note は、`patterns` が無限に膨らむ抽象化プロジェクトになるのを防ぐためのもの。

### Scope

- `observations` から `activities` を derive する
- 現在の `skill-miner` core output から初期 `patterns` を derive する
- downstream projection 向けの simple query function を出す

### 単純性ルール

query surface は小さく明示的に保つ。
ここで generic query builder を作らない。

### consistency 要件

最低限、以下を満たす。

- `activities` は grouping 条件から再現できる
- `patterns` は current `skill_miner_prepare.py` の出力と追跡可能に対応付く
- derivation version が変われば再計算できる
- stale な derived row を検出または再生成できる

### Deliverables

- aggregate-style grouping から抽出された activity derivation logic
- 現在の skill-miner candidate 構造に沿った pattern persistence / query path
- projection 向け minimal query APIs
- derived data versioning note

### Done Criteria

- `activities` を stored `observations` から再現可能に生成できる
- 初期 `patterns` を current skill-miner logic から広い再設計なしに生成できる
- projection が simple query function を通じて derived data を読める
- derivation version / rebuild rule が固定されている

## TODO 5. Skill Migration And Compatibility

### 目的

3 つの skill を shared derived data に移しつつ、ユーザー向け挙動を保つ。

### この TODO 内の順序

1. `daily-report`
2. `post-draft`
3. `skill-miner`

`skill-miner` を最後にするのは、最も大きく、最もリスクが高いため。

### Scope

- `daily-report` を `activities` 読み取りへ移行
- `post-draft` を `activities` と必要に応じて `patterns` 読み取りへ移行
- `skill-miner` を store-backed `observations` / `patterns` へ段階的に移行
- その間も `aggregate.py` 互換 path は維持する

### 追加ルール

- user-facing workflow の強制変更はしない
- `aggregate.py` を先に消さない
- mixed-scope の説明責務は保持する
- projection 層で narrative logic を抱え込みすぎない

### Deliverables

- 各 skill 向けの projection adapter
- compatibility-preserving aggregate path
- user-facing workflow 変更なしの migration
- skill-level regression test 追加

### Done Criteria

- current skill entrypoint がそのまま動く
- source を毎回すべて再実行しなくても複数 projection を生成できる
- `aggregate.py` 契約が維持される
- skill が mixed-scope 情報を引き続き扱える

## 推奨実行順

1. TODO 1a `契約テストと互換性マトリクスの固定`
2. TODO 1b `Core Extraction`
3. TODO 2 `Store Introduction`
4. TODO 4 `Derived Layers`
5. TODO 5 `Skill Migration And Compatibility`
6. TODO 3 `Source Registry Redesign`

補足:

- TODO 2 の着手時点で、TODO 3 に先立って source identity と manifest draft は凍結する
- これにより、store schema と registry redesign の手戻りを減らす
- TODO 3 は必要になれば前倒しできるが、親プラン上は独立拡張として後置する

## リスクと緩和策

### リスク: aggregate 互換性のドリフト

緩和策:

- TODO 1 で contract coverage を強化する
- `aggregate.py` は最後まで compatibility shell として残す
- top-level だけでなく nested contract と意味論も保護する

### リスク: SQLite が brittle な依存になる

緩和策:

- DB state を rebuildable とみなす
- DB 削除と再 ingest の flow を明示的にテストする
- 収集コンテキストを保存して mixed-scope を再投影可能にする

### リスク: derived data が stale になる

緩和策:

- derivation version と input fingerprint を持たせる
- rebuild rule を先に決める
- code 変更後の stale data を検出または再生成できるようにする

### リスク: `patterns` のスコープが膨張する

緩和策:

- TODO 4 実装前に narrow な first-pass definition を固定する
- 初期永続化は `skill_miner_prepare.py` の現行出力と揃える

### リスク: `skill-miner` 移行で全体が不安定化する

緩和策:

- 最後に移行する
- current candidate / proposal behavior を、store-backed 版が十分に確認できるまで維持する

### リスク: source extensibility 導入が遅すぎて store 設計が built-in 前提になる

緩和策:

- TODO 2 で manifest draft と source identity を先に固定する
- TODO 3 で registry 統合を実装する

### リスク: TODO 2 と TODO 3 の境界が曖昧で手戻りが発生する

緩和策:

- TODO 2 完了条件に source identity / manifest fingerprint / run context の固定を含める
- TODO 3 は discovery と validation の実装に集中させる

### リスク: TODO の粒度が大きく進捗判定が曖昧になる

緩和策:

- TODO 1 は 1a と 1b に分けて進める
- 各 TODO は「文書固定」と「実装」を必要に応じて分けて管理する

## 成功条件

このプランは、以下がすべて満たされたときに完了とみなす。

1. 現在の 3 skill がユーザー視点で引き続き動く
2. `aggregate.py` が互換な top-level shape と nested contract を返す
3. source run result と normalized observation が SQLite に保存される
4. mixed-scope を再投影するのに必要な run context が保存される
5. `activities` と初期 `patterns` を生成する関数または module が、`aggregate.py` / `skill-miner` 本体の外から import 可能な shared reusable layer として存在する
6. 少なくとも 1 つの skill が query API 経由で derived data を読み取り、既存挙動と互換な出力を返せる
7. 少なくとも 1 つの user drop-in source を discovery できる
8. DB を削除して source を再実行すると必要状態を再構築できる
9. derived data の version / rebuild rule が定義されている

## スコープ外

- web UI
- cloud sync
- source 契約を壊す変更
- Windows 全面対応の再設計
- generic cross-project query language
- `renders` 層の実装。これは将来の cache / 再現性最適化として想定し、必要になった時点で独立 TODO として起票する

## 次のステップ

この文書を親プランとして使い、5 本の TODO 文書を起こす。
各 TODO には最低限以下を含める。

- exact scope
- explicit deliverables
- concrete done criteria
- test expectations
- rollback / compatibility note if needed
