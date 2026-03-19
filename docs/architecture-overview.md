# Architecture Overview

このドキュメントは、DayTrace の全体像を短時間で共有するための概要資料。
README より一段実装寄りだが、内部実装の細部には入りすぎず、説明と判断の土台を揃えることを目的とする。

## 1. DayTrace が解く問題

- **証跡収集の分断**: Git コミット・AI 会話・ブラウザ閲覧・ファイル変更を 1 本ずつ人手で追う負担を排除する
- **成果物の分散**: 日報・投稿下書き・反復パターン提案がバラバラに存在する問題を、単一の観測パイプラインで解決する
- **環境非一様性**: source 欠損・権限不足・mixed-scope を含む現実の証跡を、壊れず扱う必要がある
- **外部依存なし**: 追加パッケージ・外部通信なしで動作し、Python 3 標準ライブラリ + Bash + Git のみを使う

## 2. 全体構成

```
┌──────────────────────────────────────────────────────┐
│                   Orchestration Layer                │
│               daytrace-session (SKILL)               │
└────────────────────────┬─────────────────────────────┘
                         │
     ┌───────────────────┼────────────────────┐
     ▼                   ▼                    ▼
┌─────────┐       ┌────────────┐       ┌──────────────┐
│daily-   │       │skill-miner │       │ post-draft   │
│report   │       │(SKILL)     │       │ (SKILL)      │
└────┬────┘       └─────┬──────┘       └──────┬───────┘
     │                  │                     │
     ▼                  ▼                     ▼
┌──────────────────────────────────────────────────────┐
│              Aggregate / Store Layer                 │
│  daily_report_projection.py  post_draft_projection   │
│  aggregate.py  store.py  derived_store.py            │
│  source_runs │ observations │ activities │ patterns  │
└────────────────────────┬─────────────────────────────┘
                         │
     ┌───────────────────┼────────────────────┐
     ▼                   ▼                    ▼
┌──────────┐     ┌───────────────┐    ┌──────────────┐
│git-      │     │claude-history │    │chrome-history│
│history   │     │codex-history  │    │workspace-    │
│(workspace│     │(all-day)      │    │file-activity │
│scope)    │     │               │    │(workspace)   │
└──────────┘     └───────────────┘    └──────────────┘
                   Source Layer
```

## 3. レイヤごとの責務

### 3-1. Source Layer

各 source は独立した CLI スクリプトとして実装され、Source CLI Contract に従い 1 本の JSON を stdout へ返す。

| Source | スコープ | `confidence_category` | 主なデータ |
|--------|---------|----------------------|-----------|
| `git-history` | `workspace` | `git` | カレントリポジトリの Git コミット履歴と当日の tracked worktree snapshot |
| `claude-history` | `all-day` | `ai_history` | `~/.claude/projects/**/*.jsonl` の会話ログを logical packet 化したイベント |
| `codex-history` | `all-day` | `ai_history` | `~/.codex/history.jsonl`, `~/.codex/sessions/` の会話ログを logical packet 化したイベント |
| `chrome-history` | `all-day` | `browser` | Chrome の History DB（読み取り専用コピー） |
| `workspace-file-activity` | `workspace` | `file_activity` | ワークスペース内の untracked ファイル変更 |

各 source は `sources.json` に登録され、`source_registry.py` が unified entrypoint として提供する。
ユーザーは `~/.config/daytrace/sources.d/*.json` へ drop-in manifest を置くことで source を追加できる。

**Success 出力 shape:**

```json
{
  "status": "success",
  "source": "git-history",
  "events": [
    {
      "source": "git-history",
      "timestamp": "2026-03-09T14:30:00+09:00",
      "type": "commit",
      "summary": "Implement source CLI",
      "details": {},
      "confidence": "high"
    }
  ]
}
```

source が使えない場合は `status: "skipped"` (reason 付き) または `status: "error"` (message 付き) を返す。

AI history source の補足:

- `claude-history` / `codex-history` は `details.ai_observation_packets[]` と `details.logical_packets[]` を通じて packet 単位の canonical observation を保持する
- tool activity に rollout-native な結果メタデータがある場合は、`result_status`, `exit_code`, `error_excerpt` などの explicit execution metadata を tool call detail に付与する
- これらの explicit metadata が得られない場合は、既存の text/tool repetition heuristic にフォールバックする

### 3-2. Aggregate / Store Layer

**`aggregate.py`** — 全 source を並行実行し、タイムライン統合・グルーピング・store への永続化を担うオーケストレーター。

出力 shape の主要フィールド:

- `sources[]`: source ごとの実行結果（`status`, `scope`, `events_count` など）
- `timeline[]`: 全 source のイベントを timestamp 昇順にマージしたリスト
- `groups[]`: 15 分窓で近接イベントをグルーピングした活動グループ（`evidence`, `confidence` 付き）
- `summary`: source 別カウント、total_events、total_groups、`no_sources_available`

グルーピングの confidence ルール: `git + ai_history = high`, `git or ai_history = medium`, その他 `low`

`groups[]` の current semantics:

- semantic clustering ではなく、timestamp 昇順の `timeline[]` を **15 分窓**で連結した time-window grouping
- 次イベントが現在 group の末尾から 15 分以内なら同じ group、超えたら新しい group
- `summary` は単一イベント group ではその event の `summary` を使い、複数イベント group では `"{n} activities from {sources}"` という汎用要約になる
- `evidence` は group 先頭から最大 5 件の event を保持する
- `timeline[].group_id` と `groups[].events[]` は同じ event object を共有する

つまり `daily-report` / `post-draft` が読む `groups[]` は「意味的にまとまった作業単位」ではなく、「近い時間帯に起きた証跡の塊」である。
上位 skill はこの制約を前提に、事実再構成と narrative 化を行う必要がある。

**Projection Adapters** — store-backed 再利用レイヤ:

- `daily_report_projection.py`: store の `activities` を優先し、slice が無い時だけ `aggregate.py` で hydrate する
- `post_draft_projection.py`: 同様に `activities` + cached `patterns` を返す

**SQLite Store** (`~/.daytrace/daytrace.sqlite3`):

- `source_runs`: source 実行のメタデータとフィンガープリント
- `observations`: 正規化された個別イベント（normalized event 単位）
- `activities`: `observations` を `aggregate_core.build_groups()` semantics で束ねた derived layer
- `patterns`: `skill_miner_prepare.py` の `candidates[]` を保存した derived layer

### 3-3. Output Skills

| Skill | 主軸 | 役割 | ask 回数 |
|-------|------|------|---------|
| `daily-report` | date-first | その日の活動を日報ドラフトに再構成 | 最大 1 回（mode 未指定時のみ） |
| `post-draft` | date-first | 一次情報から narrative draft を 1 本組み立て | 0 回 |
| `skill-miner` | scope-first | AI 会話履歴から反復パターンを抽出・提案 | 0 回（提案成立後のみ選択プロンプト） |

### 3-4. Orchestration

**`daytrace-session`** は個別 skill を自律的に順次実行する統合 skill。

- ask は 0 回を基本とし、機密境界確認と `CLAUDE.md diff preview` だけは例外
- 各判断ポイントで `[DayTrace]` プレフィックス付きの自己判断ログを出力
- Phase 1 〜 5（Phase 1.5 含む）をソース欠損・スクリプトエラーに関わらず最後まで完走する
- 例外: `CLAUDE.md diff preview` と、共有用出力で機密境界をまたぐ可能性がある場合の確認だけはユーザー確認を待つ

## 4. 実行フロー

### 通常 skill 実行（例: `daily-report`）

```
ユーザー指示
    │
    ▼
[Entry Contract] 日付・mode・workspace を自然言語から抽出
    │
    ▼
[Data Collection] daily_report_projection.py を 1 回実行
    │
    ├─ store に slice あり ──→ activities を直接返す
    └─ store に slice なし ──→ aggregate.py で hydrate → store に保存 → 返す
    │
    ▼
[Output Generation] sources[].scope を確認 → mixed-scope 注記判定 → 日報生成
```

### `daytrace-session` の全フェーズ

```
Phase 1: Source Assessment
    daily_report_projection.py を実行 → sources[] を確認 → 判断ログ出力

Phase 1.5: DayTrace ダイジェスト
    ログから読み取れる 1 日の概観を 3-5 行の散文で出す（Phase 2 の前に先出し）

Phase 2: Daily Report
    Phase 1 の中間 JSON で日報生成 → mode に応じて自分用 / 共有用

Phase 3: Pattern Mining & Proposals
    skill_miner_prepare.py → candidates[] → triage → (必要なら detail + judge) → proposal

Phase 4: Post Draft（条件付き）
    AI + Git 共起 or groups >= 4 の条件で post_draft_projection.py → narrative draft

Phase 5: Session Summary
    全フェーズの実施結果をサマリとして出力
```

## 5. スコープ設計

### 5-1. date-first と scope-first

`daily-report` と `post-draft` は **date-first**: 対象日が主軸で、workspace は補助フィルタ。

`skill-miner` は **scope-first**: どの範囲の履歴を読むかが主軸。
- デフォルト: current workspace の 7 日窓
- `--all-sessions`: workspace 制限を外して全セッションを対象にする（7 日窓は維持）
- workspace モード限定で、packet/candidate が少なすぎる場合だけ 30 日へ adaptive 拡張する

### 5-2. mixed-scope

`daily-report` / `post-draft` では source によってスコープが異なる。

| スコープ種別 | sources | 内容 |
|-------------|---------|------|
| `all-day` | `claude-history`, `codex-history`, `chrome-history` | その日全体の証跡 |
| `workspace` | `git-history`, `workspace-file-activity` | current workspace または指定 workspace に限定 |

workspace を指定した場合も `all-day` source まで repo 限定にはならず、mixed-scope は解消されない。
aggregate.py の `sources[].scope` フィールドがこれを明示するため、downstream skill は `scope` を読んで混同を避ける。

## 6. Reliability のための設計

### fail-soft

- 各 source は独立して実行され、1 本の失敗が他に波及しない
- `source_status_counts.success >= 1` ならば処理を継続する
- `success == 0` でも空の結果で正常終了する（空日報 / 空 narrative を返す）
- store への write failure は warning として記録し、本処理の JSON payload 自体は返す

### Slice Completeness

store-backed projection を読む際は「保存済みであること」だけで信用せず、query context と fingerprint を突き合わせて completeness を評価する。

- `complete`: 全 source が成功し、現行マニフェストと一致
- `partial`: 一部 source が skipped または error
- `degraded`: 重要 source が欠けている
- `stale`: マニフェスト変更後に未更新
- `empty`: slice が存在しない（hydrate が必要）

### rebuildable store

store は **rebuildable cache / index** として扱う。
同じ source collect を再実行すれば `source_runs` と `observations` を完全に再作成できる。
`--no-store` で 1 回の実行だけ永続化をスキップできる。

### no-store fallback

`skill_miner_prepare.py --input-source auto` は、store の該当 slice が complete で現行マニフェストと一致する場合のみ store を使い、それ以外は raw history に直接フォールバックする。

## 7. ハッカソン時点の完成範囲

### 完成済み（Phase 1 で見せるもの）

- 5 source の独立実行と aggregate 統合
- SQLite store（`source_runs` / `observations` / `activities` / `patterns`）
- projection adapters（`daily_report_projection.py`, `post_draft_projection.py`）
- `daily-report`: date-first、自分用 / 共有用モード、graceful degrade
- `post-draft`: 0 ask、narrative policy、reader 自動推定、graceful degrade
- `skill-miner`: compress → triage → (detail + judge) → proposal の 5 フェーズ
- `daytrace-session`: Phase 1.5 を含む全フェーズ自律実行、`[DayTrace]` 判断ログ
- source registry（`sources.json` + user drop-in）
- graceful degrade（全 source 欠損時も空結果で正常終了）

### Phase 2 以降に送るもの

- `skill` / `hook` / `agent` の即時生成（現状は提案止まり）
- self-improving loop の本実装（skill run 観測 → amend → 採用率評価）
- split-aware candidate reconstruction（clustering 精度改善）
- shell history の収集
- Windows 対応

## 8. 関連ドキュメント

- `README.md`: エンドユーザー向けの概要とインストール手順
- `docs/skill-catalog.md`: 4 skill の役割・入出力・使い分けガイド
- `docs/store-and-observation-model.md`: store テーブル構成・derived layer・completeness の詳細
- `docs/skill-miner-current-state.md`: skill-miner の現在の能力と既知の弱点
