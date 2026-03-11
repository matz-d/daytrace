# DayTrace 改修プラン v2 — 2026-03-11

## Context

DayTrace は「AIエージェント ハッカソン 2026」への提出を予定している Claude Code plugin。評価軸は以下。

- 自律性 40%
  - 一度任せたら、追加の細かい面倒を見なくてよいか
  - エラー時に自力で立て直そうとするか
  - 足りない情報を自分で探しに行けるか
- クオリティ 35%
  - 出力が実用レベルか
  - 体験が分かりやすく、試せる形か
- インパクト 25%
  - 本人以外にも使うイメージが湧くか
  - 誰の何を変えるかが見えるか

## Design Principles

- `Ask User` をゼロにすること自体は目的ではない
- 問題なのは、実行途中で agent が自分で判断すべきことをユーザーに戻して止まること
- 初回の入口で目的やスコープを 1 回だけ確認するのは許容される
- `skill-miner` の自律性は「最後まで勝手に環境を書き換えること」ではなく「過去の履歴を自律的に分類し、提案と根拠を返すこと」
- Skill Lifecycle を `extract/classify/evaluate/propose` と `create/connect/apply` に分離する

## Revised Product Positioning

DayTrace の 3 スキルは以下のように役割を分ける。

- `daily-report`
  - 日次の振り返りと進捗整理
  - 個人用と社内チーム共有用のモード切り替え
- `post-draft`
  - テックブログ専用の発信下書き生成
  - 一次情報を重視した narrative 形式
- `skill-miner`
  - 週次の反復パターン分析と昇格先分類
  - Skill Lifecycle 上の `extract/classify/evaluate/propose` を担当

framing:

- 初回でも、すでに Claude Code / Codex を使っている環境なら即価値が出る
- 審査員は Claude Code / Codex ヘビーユーザー。既存履歴が豊富にある前提で設計する
- `daily-report` と `post-draft` はその場で役立つ
- `skill-miner` は直近 7 日の既存 AI 会話履歴から初回でも提案を返す
- 継続運用で文脈理解・用途推定・反復パターン抽出の精度が上がる
- DayTrace は単発の要約ツールではなく `CLI エージェントを使うほど育つ振り返り環境`

## Core Plan

### 1. daily-report 改修

対象:

- `plugins/daytrace/skills/daily-report/SKILL.md`

#### 1-1. confidence 処理の変更

変更前:

- low confidence の項目を `確認したい点` セクションに分離
- source 欠損時にユーザーへ確認質問

変更後:

- `確認したい点` セクションは廃止
- low confidence の項目は本文中に含め、末尾に `※証跡からの推測です` と注記
- source 欠損時も質問せず、簡易日報として返す

#### 1-2. チーム共有モードの追加

個人用（デフォルト）:

- 現行の詳細 markdown 形式を維持
- 試行錯誤・失敗・低 confidence 情報も含む
- 構造: 概要 → 活動（詳細 2-4 文）→ 明日のアクション

チーム共有用（`--team`）:

- 5-10 行の bullet 形式
- 成果・決定・未解決・次アクションに絞る
- 試行錯誤の詳細は省略
- 構造: 進捗 bullets → 決定事項 → 未解決/ブロッカー → 次のアクション

出力例（チーム共有用）:

```markdown
## 日報 2026-03-11（チーム共有）

- DayTrace skill-miner のクラスタリング精度を改善（oversized cluster の split 優先化）
- PLAN_update.md / PLAN_skill-miner.md をレビュー結果を踏まえて v2 に刷新
- post-draft をテックブログ専用に再定義、daily-report にチーム共有モードを追加

決定: skill-miner の lightweight mode は廃止。デフォルトは直近 7 日、必要時だけ `--all-sessions`
未解決: 実データでの primary_intent 分布分析（明日着手予定）
次: skill_miner_common.py の TASK_SHAPE_PATTERNS 順序見直しと similarity_score 重み調整
```

#### 1-3. 狙い

- 自律性: 確認質問なしで完走する
- クオリティ: 個人用は振り返りに使える詳細さ、チーム用はそのまま共有できる簡潔さ
- インパクト: 1 コマンドで 2 つの用途を満たす

### 2. post-draft 改修

対象:

- `plugins/daytrace/skills/post-draft/SKILL.md`

#### 2-1. テックブログ専用化

変更前:

- 3 用途（tech-blog / team-summary / slack）から選択
- 用途確認で 1 回止まる

変更後:

- テックブログ専用に限定
- team-summary の機能は daily-report --team に移管
- slack 用途は削除（ログイン/認証系の外部連携はスコープ外のため、中途半端な用途を排除）
- 用途確認は不要になる

#### 2-2. 一次情報重視の方針

- narrative 形式を維持
- ネットの総和を上げるような、その人だけが書ける一次情報を重視
- 読者層は文脈に応じて LLM が自律判断する
  - 技術的な試行錯誤が中心 → 同業エンジニア向け
  - ツール活用やワークフローが中心 → AI × 開発に興味がある層向け
  - 思考や意思決定が中心 → 幅広い技術者向け
- 構造: Intro → 今日やったこと → 詰まった点/工夫した点 → 学び → 次にやること

#### 2-3. 自律性の改善

- 用途推定は不要（テックブログ一択）
- 読者推定は LLM が自律判断
- 実行途中で止まらない
- 曖昧な場合も「一次情報を最大限活かす narrative」にフォールバック

### 3. skill-miner 再定義

詳細は `PLAN_skill-miner.md` を参照。ここでは全体設計との関係を記す。

#### 3-1. 責務

- 過去セッションから反復パターンを抽出する
- 候補を `CLAUDE.md / skill / hook / agent` に自律的に分類する
- 各候補に提案理由と根拠（evidence chain 含む）を返す
- 実装は次セッションに渡す

データソース:

- `claude-history` と `codex-history` のみ使用（AI 会話履歴に特化）
- `git-history` / `chrome-history` / `workspace-file-activity` は使わない
- `daily-report` / `post-draft` が `aggregate.py` 経由で 5 source を使うのとは異なる

#### 3-2. 実行モード

- lightweight demo mode は廃止
- 理由: 審査員は Claude Code / Codex ヘビーユーザーであり、既存履歴が十分にある。デモ用の精度妥協は不要
- デフォルト: 直近 7 日間（`--days 7`）
- 必要時のみ: 全履歴スキャン（`--all-sessions`）
- 全履歴が 7 日未満の場合: 全履歴をそのまま使う

#### 3-3. CLAUDE.md 即適用パス

- 4 分類のうち CLAUDE.md のみ、低リスク例外として即適用パスを持つ
- diff preview → ユーザー承認 1 回 → 追記
- skill / hook / agent は次セッションの apply フローへ送る

編集仕様:

- 対象ファイルは `cwd/CLAUDE.md` のみに限定する
- 追記位置はファイル末尾の `## DayTrace Suggested Rules` セクションに限定する
- セクションがなければ新規作成し、その末尾にのみ追記する
- 既存テキストとの部分一致率が高い候補は重複と見なし、追記せず skip 理由を表示する
- 既存ルールと衝突する候補は適用せず、diff preview の提示だけで終了する
- 末尾追記以外の編集、並び替え、既存文言の書き換えは行わない

#### 3-4. evidence chain の可視化

- 提案の根拠として、代表セッション 2-3 件のタイムスタンプ + 1 行要約を添える
- `prepare` の candidate に `evidence_items[]` を追加し、`{session_ref, timestamp, source, summary}` を持たせる
- `proposal` 側で raw history を再読込せず、`prepare` が埋めた `evidence_items[]` をそのまま表示に使う
- ユーザーの「なぜこれが反復と判定されたのか」への納得感を向上

## Why This Still Counts As Autonomy

- 過去履歴の収集は自動
- 候補抽出とトリアージも自動
- 追加調査が必要なら自分で detail を取りに行く
- 曖昧な巨大クラスタは無理に提案せず、split / research / reject を自分で判断する
- evidence chain で判断根拠を透明化する

`skill-miner` の自律性は「勝手に世界を書き換えること」ではなく、反復の有無・昇格先・根拠の強さを自律的に判定することにある。

DayTrace は `既存の Claude Code / Codex 履歴がどれだけあるか` を価値の起点にできる。ここが初回体験の強みである。

## UX Principles

- 質問を完全禁止しない
- 実行途中の細かい面倒見を減らす
- ask が必要なら入口か次セッションに寄せる
- `daily-report` はモード切り替えで個人/チーム両方をカバー
- `post-draft` はテックブログ専用で用途選択を排除
- `候補 0 件` も価値ある結果として扱う
- 将来の `create / connect / apply` 拡張を妨げない責務分離を維持する

## Out Of Scope

- plugin 分類
- `skill-miner` 実行中の自動ファイル生成
- グローバル設定の自動書き換え
- Slack / Google Drive / 外部 webhook への直接連携
- `create / connect / apply` を `skill-miner` に持たせること
- lightweight demo mode

## Files To Update

- `plugins/daytrace/skills/daily-report/SKILL.md`
  - `確認したい点` セクション廃止
  - low confidence 注記化
  - --team モード追加（5-10 行 bullet 形式）
- `plugins/daytrace/skills/post-draft/SKILL.md`
  - テックブログ専用化
  - team-summary / slack 用途を削除
  - 読者層の自律推定ロジック追加
  - 一次情報重視の方針を明記
- `plugins/daytrace/skills/skill-miner/SKILL.md`
  - 週次前提、4 分類、提案と根拠までに責務を再定義
  - lightweight mode 記述を削除
  - evidence chain の出力仕様を追加
  - CLAUDE.md 即適用パスの定義
- `plugins/daytrace/skills/skill-miner/references/classification.md`
  - 4 分類の判定基準と境界ケース例を分離配置

技術改善（詳細は `PLAN_skill-miner.md` Workstream B0-E を参照）:

- `plugins/daytrace/scripts/skill_miner_common.py`
  - 特徴量改善（TASK_SHAPE_PATTERNS 順序、similarity_score 重み）
  - Quality Gate 再調整（oversized cluster の split 優先化）
- `plugins/daytrace/scripts/skill_miner_prepare.py`
  - クラスタリング改善（stable_block_keys 複合化）
  - `evidence_items[]` を candidate に埋める
- `plugins/daytrace/scripts/tests/test_skill_miner.py`
  - 中間ケース・split フロー・evidence chain のテスト追加
- `plugins/daytrace/scripts/tests/fixtures/skill_miner_gold.json`
  - 実データ由来の匿名化 fixture 追加

## Validation

### 1. 自律性

- `daily-report` が確認質問なしで完走する（個人/チーム両モード）
- `post-draft` が用途選択なしで完走する
- `skill-miner` が人間に分類をさせず、自分で提案区分を決める
- 既存の Claude Code / Codex 履歴がある環境では、初回実行でも直近 7 日の範囲で `skill-miner` が価値を返す

### 2. クオリティ

- 出力がそのまま読める
- `skill-miner` の提案理由が evidence chain で裏付けられている
- `0件` のときも、なぜ提案しなかったかと次回への示唆が分かる
- post-draft が一次情報を活かした narrative になっている

### 3. インパクト

- 日報は個人振り返りにもチーム共有にもそのまま使える
- テックブログ草案は一次情報ベースでネットの総和を上げる内容
- `skill-miner` は作業習慣から次の自動化候補を示す体験
- 継続利用で DayTrace が育つ未来を一貫して説明できる

### 4. 定量比較

- giant cluster 発生率: `oversized_cluster` flag を持つ candidate の割合
- 提案成立数: `proposal_ready=true` の candidate 数
- `0件` 率: 提案成立 0 件で終了する実行の割合
- 改修前後で同一データセットに対して上記 3 指標を比較する

## Success Criteria

- DayTrace の 3 スキルがそれぞれ異なる明確な役割を持って説明できる
- `daily-report` = 個人 + チーム共有の日次整理
- `post-draft` = テックブログ専用の一次情報発信
- `skill-miner` = 週次の自律分類エージェント
- `skill-miner` を「自律的な分類エージェント」として見せられる
- evidence chain により提案の納得感が担保されている
- 初回でも直近 7 日の既存 CLI エージェント履歴から価値が出る
- 継続利用で育つことを一貫して説明できる
- `skill-miner` の責務と将来の `create/connect/apply` の責務を分けて説明できる
