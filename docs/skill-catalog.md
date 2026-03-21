# Skill Catalog

このドキュメントは、DayTrace の skill 群の役割差分を一覧化するためのカタログ。
README の紹介文を補い、実装者・利用者・外部説明の全員が同じ言葉で skill を説明できる状態を目指す。

## 1. Skill 一覧

| Skill | 役割ラベル | 主軸 | user-invocable |
|-------|-----------|------|---------------|
| `daily-report` | Fact & Open Loops | date-first | ✓ |
| `post-draft` | Context & Narrative | date-first | ✓ |
| `skill-miner` | Pattern Extraction | scope-first | ✓ |
| `skill-applier` | Fixation | — | ✓ |
| `daytrace-session` | Orchestration | — | ✓ |

## 2. 比較表

### 2-1. 役割

| Skill | 何を作るか | 主に使う source | 何を主軸に判断するか |
|-------|-----------|----------------|---------------------|
| `daily-report` | その日の日報ドラフト（自分用 / 共有用） | 全 source（date-first） | 対象日のイベント全体 |
| `post-draft` | 読者向け narrative draft 1 本 | 全 source（date-first） | AI + Git 共起グループを中心に主題選定 |
| `skill-miner` | 反復パターンの提案（提案 / 有望候補 / 観測ノート） | claude-history, codex-history（aggregate 不使用） | workspace / all-sessions の観測スコープ |
| `skill-applier` | 適用・生成成果物（CLAUDE.md diff / skill scaffold / hook・agent guided creation） | skill-miner の proposal JSON | suggested_kind による dispatch |
| `daytrace-session` | 全フェーズの自律実行サマリ | 全 source（各 skill に委譲） | 判断ルールテーブルに従って自動決定 |

### 2-2. 入力と ask

| Skill | 日付 | workspace | mode / reader / topic | ask 回数 |
|-------|------|-----------|----------------------|---------|
| `daily-report` | today (デフォルト) or YYYY-MM-DD | 任意、補助フィルタ | `自分用` / `共有用` | mode 未指定時だけ 1 回 |
| `post-draft` | today (デフォルト) or YYYY-MM-DD | 任意、補助フィルタ | `reader`, `topic` は optional override | 0 回 |
| `skill-miner` | — | `cwd` デフォルト、`--all-sessions` で制限解除 | — | 0 回（提案後に選択プロンプト） |
| `skill-applier` | — | — | `suggested_kind` で dispatch を決定 | CLAUDE.md diff 確認と候補選択のみ |
| `daytrace-session` | today (デフォルト) | 任意、補助フィルタ | mode 未指定は自分用 + 条件付き共有用 | 0 回（共有用機密境界確認・候補選択確認・CLAUDE.md diff は例外） |

### 2-3. 出力

| Skill | 出力物 | 出力形式 |
|-------|-------|---------|
| `daily-report` | 日報ドラフト（3〜6 項目、根拠付き） | 日本語 Markdown |
| `post-draft` | narrative draft 1 本（背景、今日の中心、気づき） | 日本語 Markdown |
| `skill-miner` | `提案（アクション候補） / 有望候補（もう少し観測が必要） / 観測ノート` の 3 区分 proposal | Markdown + JSON |
| `skill-applier` | CLAUDE.md diff preview / skill scaffold context / hook・agent guided creation | Markdown |
| `daytrace-session` | 上記 4 つ + `[DayTrace]` 判断ログ + セッションサマリ | 日本語 Markdown |

## 3. `daily-report`

### 3-1. 目的

その日全体の活動を、日本語の日報ドラフトとして 3〜6 項目に再構成する。
「その repo で何をしたか」ではなく、「その日全体で何をしていたか」を date-first で伝えることが目的。
`自分用` と `共有用` の 2 モードで構成・文体を変えて出し分ける。

### 3-2. 入力

- **日付**: 指定がなければ `today`。`YYYY-MM-DD` / `yesterday` も可
- **mode**: `自分用` / `共有用`。自然言語から抽出できた場合は ask しない
- **workspace**: 任意。`git-history` と `workspace-file-activity` の絞り込みに使う補助フィルタ

データ収集は `daily_report_projection.py --date today --all-sessions` を 1 回だけ実行する。
この projection adapter は store に slice があれば再利用し、なければ `aggregate.py` で hydrate する。

### 3-3. 出力

**自分用**（時系列ベース、メモ的語彙、1〜3 文/項目）:

```markdown
## 日報 YYYY-MM-DD

### 今日の流れ
1. 見出し
   内容: 1-3文
   根拠: git-history の commit, codex-history の修正ログ

### 未完了の手がかり
- 根拠のある項目のみ（0 項目でも可）
```

**共有用**（カテゴリベース、第三者向け表現、2〜4 文/項目）:

```markdown
## 日報 YYYY-MM-DD

### 今日の概要
- 1-2文で全体要約

### 実装 / 調査 / 設計・判断
- 見出し
  - 内容: 背景を含む
  - 成果: ...
  - 残課題: ...
  - 根拠: git-history, codex-history

### 未完了の手がかり
- 根拠のある項目のみ（0 項目でも可）
```

どちらのモードでも `確認したい点` セクションは作らない。
low confidence は本文内の inline 注記で処理し、途中で追加 ask しない。

### 3-4. 向いている場面

- 毎日の業務終わりに今日の活動を素早く整理したい
- 上長や同僚に共有するレポートドラフトを作りたい
- ログが一部欠けていても、分かる範囲でまず出したい

### 3-5. 制限事項

- `workspace` を指定しても `claude-history` / `codex-history` / `chrome-history` は repo 限定にならない（mixed-scope）
- source が 0 本の場合は空日報を返す
- 出力は下書きであり、送信・公開は行わない

## 4. `post-draft`

### 4-1. 目的

その日の一次情報から、読者に向けた narrative draft を 1 本組み立てる。
`Context & Narrative` の skill として、日報（Fact & Open Loops）とは明確に役割が異なる。
ask 0 回で完走し、`topic` と `reader` は optional override として受け付ける。

### 4-2. 入力

- **日付**: 指定がなければ `today`
- **reader**: 任意。未指定時は「同じ技術スタックを使う開発者」をデフォルトとして自動推定
- **topic**: 任意。未指定時は narrative policy の 3 段フォールバックで主題を自動選定
- **workspace**: 任意。補助フィルタ

データ収集は `post_draft_projection.py --date today --all-sessions` を 1 回だけ実行する。
cached `patterns` があれば一緒に返される。

**主題選定フォールバック**（Python helper には切り出さず、LLM が SKILL.md の policy として実行）:

1. AI + Git 共起グループ（`event_count` 最大を優先）
2. AI 密度グループ（`ai_history` イベント数 3 件以上で最大のもの）
3. 最大イベント数グループ（上記に該当しない場合）

### 4-3. 出力

**基本構成**（300〜1200 字）:

```markdown
# タイトル案

## 背景
## 今日の中心
## 気づき
```

- 3 セクション構成。詰まった点・学び・次にやることは、根拠がある場合のみ narrative に織り込む
- reader override で説明の粒度とトーンを調整する（セクション数は変わらない）
- group の列挙で終わらせず、背景と意味づけを含めた 1 本通った narrative にする
- 公開・送信はせず、下書きのみ返す

### 4-4. 向いている場面

- 今日の学びをブログや Zenn にまとめたい
- 社内 Slack や外部勉強会向けの発信ドラフトを作りたい
- 試行錯誤した日の「なぜそうしたか」を言語化したい

### 4-5. 制限事項

- 主題選定は決定論的 helper に閉じないため unit test の pass/fail 条件にはなっていない
- `team-summary` / `slack` 向けの直接送信は main UX から外れている
- `workspace` を指定しても all-day source は repo 限定にならない（mixed-scope）

## 5. `skill-miner`

### 5-1. 目的

Claude / Codex の会話履歴を横断して反復パターンを抽出し、`CLAUDE.md` / `skill` / `hook` / `agent` のどれに固定すべきかを評価して proposal を返す。
scope-first であり、aggregate.py は使わず専用 CLI だけを使う。

### 5-2. 入力

`aggregate.py` は使わない。skill-miner 専用 CLI を順に実行する:

| フェーズ | CLI | 役割 |
|---------|-----|------|
| 1 | `skill_miner_prepare.py --input-source auto --store-path ~/.daytrace/daytrace.sqlite3 --decision-log-path ~/.daytrace/skill-miner-decisions.jsonl` | セッションを圧縮 candidate view に変換 |
| 2（条件付き） | `skill_miner_detail.py --refs <ref1> <ref2>` | needs_research 候補の detail 再取得 |
| 3（条件付き） | `skill_miner_research_judge.py --candidate-file ... --detail-file ...` | 追加調査後の結論判定 |
| 4 | `skill_miner_proposal.py --prepare-file ... --judge-file ... --decision-log-path ... --skill-creator-handoff-dir ...` | 最終 proposal 組み立て・decision log writeback |
| 5（条件付き） | `skill-applier` skill に委譲 | 候補選択後の apply / 生成アクション実行 |

**観測窓のデフォルト**: 7 日。`--all-sessions` で workspace 制限を解除するが 7 日窓は維持。
`workspace` モードでは packet / candidate が少なすぎる場合だけ 30 日に自動拡張（adaptive window）。

### 5-3. 出力

```markdown
### 観測範囲
観測範囲: {workspace名} / 直近 {N}日間 / {source}

## 提案（アクション候補）
1. 候補名
   種類: 再利用スキル / 自動チェック（hook） / 専用エージェント / プロジェクト設定（CLAUDE.md）
   確度: 中程度 — 複数セッションで出現、もう少し定着を見たい
   根拠:
   - 2026-03-08T10:00:00+09:00 claude-history: findings-first review を要求
   効果: 同種作業の再利用フローを安定化できる
   → 種類に応じた apply / 生成フローへ進める

## 有望候補（もう少し観測が必要）
1. 候補名
   confidence: weak
   出現: 3回 / 2ソース
   現状: 巨大クラスタで意味の異なる作業が混ざる可能性がある
   次のステップ: 1-2 週間の運用後に再観測で分割判断

## 観測ノート
1. 候補名または項目種別
   理由: 単発または一般化の根拠不足
```

`提案（アクション候補）` が 1 件以上ある時だけ、末尾に候補選択プロンプトを付けて次の apply / draft 選択へ繋ぐ。
`CLAUDE.md` 分類の候補だけは immediate apply として diff preview を返す仕様を持つ。

### 5-4. 向いている場面

- AI 活用の反復パターンを見つけて自動化候補にしたい
- `CLAUDE.md` に追記すべき原則候補を探したい
- workspace 横断で自分の作業スタイルを俯瞰したい

### 5-5. 制限事項

- `skill` は scaffold / handoff の提示まで、`hook` / `agent` は承認後の生成までを扱う。自動デプロイは行わない
- 提案品質は clustering 精度に依存し、巨大クラスタが発生すると粒度が粗くなる
- `SKILL.md` の自動修正・self-improving loop の本実装は Phase 2 以降
- 詳細は `docs/skill-miner-current-state.md` を参照

## 6. `skill-applier`

### 6-1. 目的

skill-miner が返した proposal の candidate を `suggested_kind` に応じた具体的成果物に変換する。
`CLAUDE.md` は immediate apply path を持ち、`skill` は scaffold / handoff、`hook` / `agent` は承認後の guided creation を行う。

### 6-2. 入力

- **proposal JSON**: `skill_miner_proposal.py` の stdout（`ready[]`, `decision_log_stub[]`）
- 入力は `skill-miner/references/proposal-json-contract.md` で定義された machine-actionable JSON

### 6-3. Dispatch Rules

| suggested_kind | アクション | 詳細仕様 |
|---------------|-----------|---------|
| `CLAUDE.md` | Immediate Apply — diff preview → apply | `references/claude-md-apply.md` |
| `skill` | Scaffold Draft — context 構造化 → skill-creator handoff | `references/skill-scaffold.md` |
| `hook` | Guided Creation — 設計案提示 → 承認後 settings.json に生成 | `references/hook-agent-nextstep.md` |
| `agent` | Guided Creation — 設計案提示 → 承認後 agents/ に生成 | `references/hook-agent-nextstep.md` |

### 6-4. 出力

- `CLAUDE.md`: diff preview。apply 成功後、decision log に `adopt + completed` を writeback
- `skill`: scaffold context（purpose / steps / output / references の構造化提示）+ skill-creator handoff
- `hook` / `agent`: 設計案（trigger / action / scope）を提示し、承認後にファイルを生成する

### 6-5. Decision Writeback

ユーザーの adopt / defer / reject を `skill_miner_decision.py` で正規化し、`skill_miner_proposal.py --user-decision-file` 経由で decision log に書き戻す。

### 6-6. 向いている場面

- skill-miner の提案を実際の成果物にしたい
- `CLAUDE.md` に追記すべきルールを 1 ステップで確定させたい
- skill / hook / agent の設計を具体化したい

### 6-7. 制限事項

- `skill` は handoff まで、`hook` / `agent` は承認後の生成までを担う（即時デプロイはしない）
- raw history 全量を再読み込みしない（evidence_items の範囲内で完結させる）
- `CLAUDE.md` は `cwd/CLAUDE.md` のみが対象

## 7. `daytrace-session`

### 7-1. 目的

「今日の振り返りをお願い」の 1 言で、ログ収集・日報生成・反復パターン提案・投稿下書きまでを自律的に完走するオーケストレーション skill。
個別 skill の出力フォーマットや品質基準を上書きせず、orchestration のみを担う。

### 7-2. 実行順

| フェーズ | 処理 | CLI |
|---------|------|-----|
| Phase 1 | Source Assessment | `daily_report_projection.py` |
| Phase 1.5 | DayTrace ダイジェスト | Phase 1 の JSON からログの概観を 3-5 行の散文で出す |
| Phase 2 | Daily Report | Phase 1 の中間 JSON を再利用 |
| Phase 3 | Pattern Mining & Proposals & Fixation | `skill_miner_prepare.py` → (条件付き) `detail` → `judge` → `proposal` → `skill-applier` |
| Phase 4 | Post Draft（条件付き） | `post_draft_projection.py` |
| Phase 5 | Session Summary | — |

**Phase 4 の起動条件**: `git + (claude or codex) 共起 sources success` または `total_groups >= 4`

**自動判断テーブル**:

| 判断ポイント | 条件 | Yes | No |
|-------------|------|-----|-----|
| 続行 vs 停止 | success >= 1 | 続行 | 空日報 → Phase 5 |
| 共有用追加 | mode 未指定 & total_groups >= 5 | 自分用 + 共有用 | 自分用のみ |
| 追加調査実行 | needs_research >= 1 | detail + judge 自動実行 | スキップ |
| apply / 生成アクション | ready >= 1 & 候補選択あり | skill-applier に委譲 | 全候補を pending で記録 |
| CLAUDE.md diff | ready に CLAUDE.md 候補あり | diff preview 表示 | スキップ |
| 投稿下書き | AI + Git 共起 or groups >= 4 | 生成 | スキップ |

### 7-3. 自己判断ログ

各フェーズで `[DayTrace]` プレフィックス付きの判断ログを出力する。スキップした場合もその理由を記録する。

```
[DayTrace] ログを収集しました
  git-history (12 events) — workspace scope
  claude-history (8 events) — all-day scope
  chrome-history → 権限不足のためスキップ
  → 4 ソースで続行します

[DayTrace] 活動グループが 7 件あるため、共有用の要約も自動生成します

[DayTrace] 1 件は追加調査が必要 → 関連セッションを自動確認します
[DayTrace] 調査完了: 1 件を「ready」に昇格

[DayTrace] CLAUDE.md に適用可能な候補があります → diff preview を表示します
```

### 7-4. 向いている場面

- 毎日の終わりに一言で全振り返りを完走させたい
- 日報・パターン提案・ブログ下書きを個別に呼ぶのが手間
- どの skill を使うべきか迷う時

### 7-5. 制限事項

- Phase 2 〜 4 の品質は各個別 skill の品質に依存する
- 共有用日報の機密境界確認・ready proposal の候補選択確認・CLAUDE.md diff preview では、例外的にユーザー確認を待つ
- ※ 機密境界: workspace 内部の情報を外部共有向け（共有用日報・投稿下書きなど）に出す際の、情報公開範囲の切り替え境界
- フェーズの 1 つが失敗してもセッション全体は止まらない

## 8. 使い分けガイド

### まず何を呼ぶべきか

```
「今日の振り返りを全部やって」
    → daytrace-session（Phase 1〜5、Phase 1.5 含む を自動完走）

「今日の日報だけ作りたい」
    → daily-report（Fact & Open Loops に集中）

「今日の体験をブログにまとめたい」
    → post-draft（Context & Narrative に集中）

「自分の AI 活用パターンを整理したい」
    → skill-miner（Pattern Extraction に集中）

「skill-miner の提案を成果物に変えたい」
    → skill-applier（Fixation に集中）
```

### 個別 skill を使う時

- 特定の成果物だけが欲しい場合は個別 skill を使う
- `daily-report` の mode を細かく制御したい場合（例: 昨日分を共有用で）
- `post-draft` の reader / topic を上書きしたい場合
- `skill-miner` で `--all-sessions` や `--days` を手動制御したい場合
- `skill-applier` で特定の proposal を手動で適用 / 生成したい場合

### 統合 skill を使う時

- 日常の振り返りルーティンとして使う場合
- 迷ったらとにかく `daytrace-session` を呼ぶ
- ask なしで最後まで進んでほしい場合

## 9. FAQ

### なぜ `daily-report` と `post-draft` は別なのか

目的が異なるため。

- `daily-report` は **Fact & Open Loops**: 今日何をしたか・どんな未完了の手がかりがあるかを自分または共有相手のために整理する
- `post-draft` は **Context & Narrative**: 読者に向けて、その日の試行錯誤・判断・学びを 1 本の話として組み立てる

同じログから出発しても、求められる構成・文体・粒度が根本的に違う。

### なぜ `skill-miner` だけ scope-first なのか

反復パターンは「いつ起きたか」より「どの範囲の作業で繰り返されているか」が本質的な問いのため。
workspace を絞るか全セッションを横断するかが候補の意味を左右する。一方で `daily-report` / `post-draft` は対象日の活動全体を伝えることが主目的なので date-first が自然。

### なぜ `skill-miner` と `skill-applier` が分かれているのか

抽出と apply / 生成の責務が異なるため。`skill-miner` はパターンを発見して評価・分類する責務を持ち、`skill-applier` は選択された候補を成果物（CLAUDE.md ルール・skill scaffold・hook / agent 定義）に変換する責務を持つ。分離することで、提案を見てから適用を別セッションで行うワークフローも成立する。

### なぜ `daytrace-session` が ask 0 回なのか

統合 skill の価値は「1 言で全部やってくれること」にある。途中で確認が入ると目的が崩れる。
判断ルールをテーブル化し、自己判断ログで何を判断したかを透明化することで ask なしでも信頼できる出力を担保している。
