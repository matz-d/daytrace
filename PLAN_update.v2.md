# DayTrace 改修プラン v2.3 — 2026-03-11

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

## Document Status

この文書は、実装済み仕様の完全な再記述ではなく、次の 3 つを分けて管理するための移行計画である。

- `Current`
  - 現在のコードベースと SKILL.md が実際にそうなっていること
- `Agreed Target`
  - すでに合意したが、まだ実装や文言反映が完了していないこと
- `Decided`
  - v2.2 以降で Open Design から昇格させた確定事項

この方針により、過去の合意事項を消さずに保持しつつ、現状との差分だけを前に進める。

## Design Principles

- `Ask User` をゼロにすること自体は目的ではない
- 問題なのは、実行途中で agent が自分で判断すべきことをユーザーに戻して止まること
- 初回の入口で目的やスコープを 1 回だけ確認するのは許容される
- `skill-miner` の自律性は「最後まで勝手に環境を書き換えること」ではなく「過去の履歴を自律的に分類し、提案と根拠を返すこと」
- Skill Lifecycle を `extract/classify/evaluate/propose` と `create/connect/apply` に分離する

## Cross-Skill Framing

DayTrace の 3 スキルは、同じ履歴を別用途に再解釈するのではなく、役割の異なる 3 層として説明する。

- `daily-report`
  - date-first
  - **Fact & Action** — 1 日全体の活動をどう意味づけるかを扱う
  - 主目的は「その repo で何をしたか」ではなく「その日全体で何をしていたか」の再構成
- `post-draft`
  - date-first
  - **Context & Narrative** — 1 日の一次情報から、外部に出せる narrative を作る
  - workspace は主軸ではなく、必要時だけ使う補助フィルタ
- `skill-miner`
  - scope-first
  - どの範囲の履歴から反復パターンを読むかが主題
  - `workspace` と `all-sessions` の区別が UX 上重要

この役割分担により、各 skill の対象範囲と UX の違いを自然に説明できる。

## Product Positioning

- 初回でも、すでに Claude Code / Codex を使っている環境なら即価値が出る
- 審査員は Claude Code / Codex ヘビーユーザー。既存履歴が豊富にある前提で設計する
- `daily-report` と `post-draft` はその場で役立つ date-first の出力層
- `skill-miner` は蓄積履歴から反復を読む scope-first の分析層
- DayTrace は単発の要約ツールではなく、CLI エージェント利用が積み上がるほど育つ振り返り環境

## Input Surface Contract

3 スキル共通の入力インターフェース契約。skill は Claude Code の slash command として呼び出される前提で、入力は以下の 2 経路で受け取る。

### 経路 1: 自然言語からの抽出

ユーザーが slash command に続けて自然言語を書いた場合、LLM が以下のパラメータを抽出する。

- 日付: 「今日」「昨日」「3/9」→ `--date` に変換
- workspace: 「daytrace の」「/path/to/repo で」→ `--workspace` に変換
- mode (daily-report): 「チーム用に」「共有用で」→ 共有用と判定
- reader (post-draft): 「非エンジニア向けに」→ `--reader` に変換
- topic (post-draft): 「aggregate.py の話で」→ `--topic` に変換

### 経路 2: 引数なし実行

引数なしで実行された場合は、各スキルのデフォルト動作に従う。

- `daily-report`: 入口 ask 1 問（「自分用？共有用？」）
- `post-draft`: 0 ask（全自動）
- `skill-miner`: 現行通り（workspace デフォルト、`--all-sessions` で広域）

### 契約

- SKILL.md は「どのパラメータを受け付けるか」と「デフォルト値」を定義する
- パラメータの抽出ロジックは LLM の自然言語理解に委ねる（パーサーは書かない）
- 抽出できなかったパラメータはデフォルト値を使う
- 実行途中での追加 ask は行わない（入口で取れなかった情報はデフォルトで埋める）
- `daily-report` の mode は、自然言語から抽出できた場合は ask しない。抽出できなかった場合だけ最初の 1 ターンで確認する
- 入口 ask は Claude Code の標準対話フローに従って行い、専用の Python パーサーや別 CLI は追加しない

## 1. daily-report

### Current

- `aggregate.py` を 1 回実行し、`groups` と `timeline` を読んで日報を組み立てる
- 対象日は単日指定が基本で、未指定時は今日
- 対象 workspace は未指定時に現在の作業ディレクトリ
- source 欠損時も graceful degrade する
- low confidence 項目は `確認したい点` に分離する運用になっている

### Agreed Target

- `daily-report` は `date-first` の skill として扱う
- デフォルトでは 1 日全体の活動を対象にする
- workspace は主軸ではなく補助フィルタとし、特定 repo に絞りたい場合だけ使う
- 必要に応じて、特定 workspace の git / file 根拠を強めた mixed-scope 日報を生成できるようにする
- 主目的は「その日全体でどんな活動をしていたか」の再構成
- `確認したい点` に依存せず、可能な限り質問なしで完走する
- `daily-report` は `Fact & Action` を担い、`自分用` と `共有用` の 2 パターンを持つ

### Decided (v2.2)

#### 2パターンの差分定義

`自分用` と `共有用` は同じ「事実の構造化」を行うが、読者が自分だけか他者を含むかで以下が変わる。

**自分用:**

- 構成: 時系列ベース（やった順に並べる）
- 語彙: メモ的・省略OK（「PR出した」「rebase した」で十分）
- 未完了の扱い: そのまま残す（「途中」「TODO」で切ってよい）
- 文脈補足: 不要（自分が分かればよい）
- 分量の目安: 3-6 項目、各 1-3 文

**共有用:**

- 構成: カテゴリベース（実装 / 調査 / 設計 / 判断 など機能軸で分類）
- 語彙: 第三者が読める表現（背景を1文添える）
- 未完了の扱い: 成果と課題を明示的に分離する
- 文脈補足: 必要（「なぜやったか」の背景を添える）
- 分量の目安: 3-6 項目、各 2-4 文 + カテゴリ見出し

#### 入口 ask

- 1問: 「自分用ですか？ 共有用ですか？」
- mode が自然言語入力から抽出できた場合は ask しない
- mode が抽出できなかった場合だけ、Claude Code の標準 ask で最初の 1 ターンに確認する
- 日付は `today` デフォルト。変更は引数で指定（ask しない）
- workspace は未指定なら date-first mixed-scope、指定時も主に git / file 根拠を絞る補助情報として扱う（ask しない）
- 途中での追加 ask は行わない

### Decided (v2.3): Mixed-Scope Contract

#### 背景

現行 `aggregate.py` は全 source に同じ `--workspace` を渡す（`build_command` L117-134）。ただし source CLI の解釈は一様ではない。

- `claude-history` / `codex-history`: `--all-sessions` が付くと workspace を無視する
- `chrome-history`: `--workspace` を常に無視する
- `git-history` / `workspace-file-activity`: `--workspace` で絞り込まれる

この差分を後段 skill が説明できるようにするには、`supports_all_sessions` のような capability flag ではなく、source ごとのスコープ意味論を明示メタデータとして持つ必要がある。

#### source のスコープ分類

`sources.json` の `scope_mode` により、各 source のスコープ特性を以下のように固定する。

| source | `scope_mode` | スコープ特性 |
|---|---|---|
| `claude-history` | `all-day` | `--all-sessions` 付き date-first 実行ではその日の全セッションを返す |
| `codex-history` | `all-day` | 同上 |
| `chrome-history` | `all-day` | workspace に依存せず、その日の閲覧履歴を返す |
| `git-history` | `workspace` | `--workspace` の git repo / pathspec に限定される |
| `workspace-file-activity` | `workspace` | `--workspace` 配下のファイル活動に限定される |

#### date-first 実行の契約

`daily-report` / `post-draft` が date-first で実行される場合:

1. `aggregate.py` は `--all-sessions` 付きで実行する
2. 全日対応 source（claude-history, codex-history, chrome-history）はその日の全イベントを返す
3. workspace 依存 source（git-history, workspace-file-activity）は、workspace 未指定時は **current working directory**、workspace 指定時は **指定 path** を使う
4. workspace を指定しても `claude-history` / `codex-history` / `chrome-history` は strict な repo filter にはならず、引き続き `all-day` evidence を返しうる
5. 出力 JSON の各 source summary に `"scope"` フィールドを追加する:
   - `"all-day"`: 全日スコープで実行された source
   - `"workspace"`: workspace 限定で実行された source
6. SKILL.md 側は、日報・記事の冒頭に「全日スコープ source + workspace 限定の git/file」であることを注記する
7. downstream の LLM は `sources[].scope` を見て narrative を調整してよいが、strict repo-only coverage を主張してはならない

#### なぜ hybrid を許容するか

- 全 source を全日化するには git-history / workspace-file-activity が全ローカル repo をスキャンする必要があり、コスト・複雑性が跳ね上がる
- 実際の利用シーンでは、ユーザーは作業中の repo で `/daily-report` を実行する。cwd の git 履歴が取れれば十分なケースが大半
- hybrid であることを出力に明示すれば、「1日全体」と説明しつつ実態は workspace 限定、という誤解を防げる

#### 実装変更の最小差分

1. `sources.json`: 全 source に `scope_mode` を追加する
2. `aggregate.py` の出力: `summarize_source_result()` に `"scope"` キーを追加し、`scope_mode` をそのまま出す
3. SKILL.md: date-first 実行時のスコープ注記ルールを追加し、workspace 指定が strict repo-only ではないことも明記する

### Open Design

- strict repo-only な `daily-report` / `post-draft` を将来 separate mode として設計するか

### Migration Notes

- まず文言を `workspace default` 前提から `date-first` 前提へ変える
- 文言先行で未実装の strict repo-only を示唆しない
- team 向け短縮出力は `共有用` パターンとして daily-report 内で扱う

### Implementation Tasks

この section は、次に TODO へ落とすためのタスク粒度を先に固定する。

- scope contract を `date-first default + optional workspace filter` に書き換える
- workspace 指定時も `all-day` source は残ることを SKILL.md と README に明記する
- `自分用 / 共有用` の 2 パターンを仕様として固定する（差分定義は Decided v2.2 参照）
- mode 決定は `入口 ask 1 回`（「自分用？共有用？」）で行う
- low confidence を `確認したい点` ではなく注記で処理する仕様へ更新する
- mixed-scope contract を実装する（Decided v2.3 参照）
  - `summarize_source_result()` に `scope` フィールドを追加
  - SKILL.md にスコープ注記ルールを追加
- sample output を 2 パターン分更新する

### TODO Candidates

- `TODO-D1-v2-daily-report-date-first.md`
  - date-first scope と workspace 補助フィルタの整理
  - mixed-scope contract の実装
- `TODO-D1-v2-daily-report-modes.md`
  - 自分用 / 共有用の 2 パターン整理（差分定義の実装）
- `TODO-D1-v2-daily-report-low-confidence.md`
  - 注記化と graceful degrade の整理

## 2. post-draft

### Current

- `aggregate.py` を前提にする出力 skill
- 用途は `tech-blog / team-summary / slack` の 3 つ
- 用途未指定時は 1 問だけ聞いて決める
- 対象 workspace は未指定時に現在の作業ディレクトリ
- narrative 形式だけでなく、共有・短文投稿も同居している

### Agreed Target

- `post-draft` も `date-first` の skill として扱う
- 主目的は、その日全体の一次情報から「その人だけが書ける narrative」を組み立てること
- デフォルトでは 1 日全体を対象にする
- workspace は repo を絞り込みたい時だけ使う補助フィルタ
- 用途選択は廃止し、`一次情報ベースの narrative draft` に集中する
- 名前は `post-draft` のままとする（「post = 投稿」は媒体を限定しない。「draft」は下書きという設計思想を名前で伝える）
- `team-summary` 的な共有は `daily-report` 側で受ける
- `post-draft` は `Context & Narrative` を担う

### Decided (v2.2)

#### ask 設計

- デフォルトは **0 ask**。topic も reader も指定なしで実行できる
- `--topic` と `--reader` を optional override として受け付ける
- 指定がない場合は、以下の自動判定ルールで決める

#### 読者の自動推定ルール

- デフォルト読者: **「同じ技術スタックを使う開発者」**
- override で `--reader` が指定された場合は、その読者像に合わせてトーンと粒度を調整する
  - 例: `--reader "社内の非エンジニア"` → プロセスと成果を中心に、技術用語を避ける
  - 例: `--reader "個人ブログの読者"` → 一人称で、試行錯誤のストーリーを前に出す

#### トーン・構成の自動判定

以下は ask せず、読者と主題から自動で決める。

- **トーン**: 読者から導出（技術者向け→具体的・再現可能、非技術者向け→プロセス・成果中心）
- **構成**: 主題の性質から導出（実装系→背景/実装/詰まり/学び、調査系→動機/比較/結論、設計系→課題/選択肢/判断理由）
- **長さ**: 600-1200 字を基本とし、source の密度に応じて自動調整

#### description の書き方

SKILL.md の description フィールド（トリガーに直結する1行）は以下とする。

```
1日の活動ログから、読者に向けた narrative の下書きを生成する。記事を書きたい、ブログにまとめたい、ふりかえりを書きたい、学びを共有したい時に使う。
```

「テックブログ」という語は description に入れない。

### Decided (v2.3): 主題の自動選定シグナル

v2.2 では「試行錯誤の密度」「学びの転換点」という意味ラベルで主題選定を記述したが、`aggregate.py` の `groups` は時間近接で束ねたイベント群であり、こうした意味ラベルを持たない。v2.3 では、現行の `groups` データ shape から機械的に判定可能なシグナルに落とす。

#### groups の持つフィールド（現行実装）

各 group は以下を持つ:

- `sources[]`: グループに含まれる source 名のリスト
- `confidence_categories[]`: source のカテゴリ（`git`, `ai_history`, `browser`, `file_activity`）
- `event_count`: イベント数
- `confidence`: `high` / `medium` / `low`
- `events[]`: 個別イベント。各イベントは `source`, `type`, `summary`, `details`, `timestamp` を持つ

#### 主題選定: 3段フォールバック

aggregate 結果の `groups` から、以下の優先順位で主題を1つ選ぶ。

**優先度 1: AI + Git 共起グループ**

- 条件: `sources` に (`claude-history` or `codex-history`) AND `git-history` が両方含まれる
- 複数該当時: `event_count` が最大のものを選ぶ
- 根拠: AI との対話と実際のコミットが同時間帯にある = 最も実作業の密度が高い

**優先度 2: AI 密度グループ**

- 条件: `confidence_categories` に `ai_history` を含み、かつ `ai_history` source のイベントが 3 件以上
- 複数該当時: AI イベント数が最大のものを選ぶ
- 根拠: AI との対話が集中している = 試行錯誤が多い作業

**優先度 3: 最大イベント数グループ（フォールバック）**

- 条件: 上記に該当しない場合
- `event_count` が最大のグループを選ぶ

#### 「学びの転換点」の扱い

v2.2 で記述した「エラー→解決」「方針変更」「新ツール導入」の判定は、`events[].type` と `events[].summary` のテキストパターンに依存するため、LLM の narrative 構成フェーズに委ねる。主題選定（どのグループを中心にするか）は上記の機械的シグナルで決め、選ばれたグループ内のストーリー構成（どこが転換点か）は LLM が `events` を読んで判断する。

この分離により、主題選定は安定し、narrative の質は LLM の強みに委ねられる。

### Decided (v2.3): 実装場所と検証方針

#### 実装場所

- `post-draft` の主題選定は Python の決定論的 helper には切り出さない
- 実装場所は `plugins/daytrace/skills/post-draft/SKILL.md` の narrative policy とする
- `aggregate.py` が返す `groups` / `events` を LLM が読み、主題選定と narrative 構成を一体で行う
- したがって、このロジックの責務は「前処理コード」ではなく「SKILL.md の出力ポリシー」に属する

#### 検証方針

- 主題選定そのものを unit test の pass/fail 条件にはしない
- 検証は fixture ベースのサンプル確認で行う
- 同じ aggregate fixture に対して、`post-draft` が一貫して narrative を組み立てられるかを人間がレビューする
- 自動テストは `aggregate.py` の shape、mixed-scope 表示、graceful degrade など決定論的な部分だけに限定する

### Open Design

- date-first 化後に、複数 workspace にまたがる 1 日を 1 本の記事としてどう自然にまとめるか

### Migration Notes

- 文言上は「3 用途 skill」から「一次情報ベースの narrative draft skill」へ整理する
- ただし既存実装との不整合を避けるため、移行完了までは compatibility note を残す
- `team-summary` は削除ではなく `daily-report` 側へ統合した役割整理であることを明記する
- `slack` 用途は main UX から外す。compatibility note として残すが、description やサンプルからは除去する
- `post-draft` の価値は用途選択より一次情報の narrative 化にあることを明記する

### Implementation Tasks

この section は、次に TODO へ落とすためのタスク粒度を先に固定する。

- role definition を `tech-blog 媒体専用` から `narrative draft` へ再定義する
- description フィールドを Decided v2.2 の文言に書き換える
- `team-summary` を `daily-report` 側へ統合したことを明文化する
- `slack` 用途を main UX から外し、compatibility note に移す
- default UX を `0 ask` とし、`--topic` / `--reader` を optional override にする
- 主題の自動選定ルールを SKILL.md に記載する（Decided v2.3 の 3 段フォールバック）
- 読者の自動推定ルールを SKILL.md に記載する（Decided v2.2 参照）
- トーン・構成の自動判定ルールを SKILL.md に記載する（Decided v2.2 参照）
- sample output を `Fact ではなく Narrative` として更新する
- local-first な narrative 資産として将来保存する前提を明記する

### TODO Candidates

- `TODO-D3-v2-post-draft-role.md`
  - post-draft の役割再定義 + description 書き換え
- `TODO-D3-v2-post-draft-ux.md`
  - 0 ask デフォルト + optional override + 自動選定/推定ルール
- `TODO-D3-v2-post-draft-samples.md`
  - sample output と description の更新

## 3. skill-miner

`skill-miner` の詳細は `PLAN_skill-miner.md` を参照する。ここでは、今回の framing に関係する差分だけ記す。

### Agreed Framing

- `skill-miner` は `scope-first` の skill である
- 目的は 1 日の活動の要約ではなく、反復パターンを抽出して昇格先を判定すること
- `workspace` は意味論的な「その repo に関係する作業」ではなく、各 Claude/Codex セッションの `cwd` が対象 path 配下かで絞る局所フィルタである
- `all-sessions` は workspace 制限を外した広域観測モードとして扱う
- state file は持たず、実行モードは CLI 引数だけで決める

### Remaining Gap

現状実装と今回の整理の差分は、主に期間設計にある。

- 現状:
  - デフォルトは `--days 7`
  - `--all-sessions` を付けると日付制限を外す
- 今回の整理:
  - `all-sessions` でも、まずは直近 7 日をデフォルト観測窓にする
  - `workspace` は同じく 7 日で開始し、packet / candidate が少なすぎる時だけ 30 日へ自動拡張する
  - adaptive window は `workspace` にだけ持たせる

補足:

- `--days 7` デフォルトと `--all-sessions` 例外の contract 自体は docs / code / tests で既に一致している
- 差分は adaptive window を v2 framing にどう乗せるかにある

### Design Intent

- `all-sessions` は母数が大きいので、初期観測窓は小さく保つ
- `workspace` は `cwd` ベースで対象が狭いため、必要時だけ 30 日に広げて `0件` を減らす
- これにより、不要に巨大クラスタを増やしすぎず、母数不足も避ける
- `evidence_items[]` による evidence chain は既に導入済みで、proposal phase は raw history を再読込しない contract になっている
- B0 観測のための `--dump-intents` / `intent_analysis` も実装済みで、primary_intent の実データ分析経路は確保されている

### Non-Goals

- `skill-miner` の責務を `daily-report` 的な日次要約へ寄せない
- `workspace` を repo 意味論へ再定義しない
- `create/connect/apply` をこの phase に戻さない

## Invariants We Are Keeping

前回合意のうち、今回も保持するものを明示する。

- `skill-miner` は `aggregate.py` を使わない
- `skill-miner` は AI 会話履歴に特化する
- `skill-miner` の classify 対象は `CLAUDE.md / skill / hook / agent`
- `CLAUDE.md` だけ immediate apply path を持つ
- `proposal` 側は raw history を再読込せず、prepare contract を主根拠にする
- `daily-report` / `post-draft` は `aggregate.py` 経由の出力層として維持する

## Out Of Scope

- plugin 分類の復活
- Slack / Google Drive / 外部 webhook への直接連携
- `skill-miner` に `create / connect / apply` を戻すこと
- `daily-report` / `post-draft` の date-first 化と同時に source 全体を全面作り直すこと

## Files To Update

### Primary

- `plugins/daytrace/skills/daily-report/SKILL.md`
  - date-first への再定義
  - workspace を補助フィルタとして再記述
  - `自分用 / 共有用` の 2 パターン整理
  - mixed-scope 注記ルール
- `plugins/daytrace/skills/post-draft/SKILL.md`
  - date-first への再定義
  - `Context & Narrative` への再定義
  - description フィールドの書き換え
  - 0 ask + optional override の UX 記載
  - 自動選定 / 推定ルールの記載（v2.3 シグナル定義）
  - `team-summary` 統合の役割整理
- `README.md`
  - 3 skill の役割分担説明を current wording から更新する

### Secondary

- `plugins/daytrace/scripts/aggregate.py`
  - `summarize_source_result()` に `scope` フィールドを追加
  - date-first に沿うスコープ契約を再設計する場合の中心
- `plugins/daytrace/scripts/claude_history.py`
  - date-first / workspace-first の切り替え契約見直し
- `plugins/daytrace/scripts/codex_history.py`
  - date-first / workspace-first の切り替え契約見直し
- `plugins/daytrace/scripts/skill_miner_prepare.py`
  - workspace-only adaptive window を導入する場合の中心

### Tests

- `plugins/daytrace/scripts/tests/test_aggregate.py`
  - mixed-scope: `scope` フィールドが source summary に含まれることの検証
  - date-first: `--all-sessions --date today` で全日 source が `scope: "all-day"` を返すことの検証
  - workspace: `--workspace /path` 指定時に git/file が `scope: "workspace"` を返すことの検証

### References And Samples

- `plugins/daytrace/skills/post-draft/references/sample-outputs.md`
  - `team-summary` / `slack` の扱いを整理
  - 同一 aggregate fixture に対する narrative sample を保持し、主題選定と構成を人間レビューする
- `plugins/daytrace/skills/skill-miner/references/cli-usage.md`
  - `all-sessions` と観測窓の説明を整理
- `plugins/daytrace/skills/skill-miner/references/b0-observation.md`
  - B0 観測と通常運用の window の違いを整理

## Migration Order

SKILL.md と PLAN は並行して進める。PLAN は SKILL.md の上位仕様書ではなく、差分を記録する文書である。

1. `daily-report/SKILL.md` と `post-draft/SKILL.md` を書き始める（PLAN と並行）
   - 書きながら PLAN の記述が足りない箇所を発見したら、PLAN も同時に更新する
   - 整合性は Validation で担保する
2. `aggregate.py` に `scope` フィールドを追加し、テストを書く
3. `README.md` の product framing を合わせる
4. その後に残りの `aggregate.py` と source CLI の date-first 契約を設計する
5. 最後に `skill-miner` の adaptive window を設計・実装する

この順序にする理由:

- SKILL.md の実物を書くことで Open Design の未決事項が具体化する
- PLAN だけを先に完成させようとするウォーターフォールを避ける
- `aggregate.py` の `scope` フィールド追加は小さい変更で、早期に入れて SKILL.md と整合させる
- `skill-miner` は大枠が揃っているため、最後に残差だけ詰めればよい

## Validation

### 1. Framing Validation

- `daily-report` / `post-draft` が date-first であると一貫して説明できる
- `skill-miner` が scope-first であると一貫して説明できる
- workspace が 3 skill で同じ意味に見えないよう整理されている

### 2. Documentation Validation

- `PLAN_update.md`, `SKILL.md`, `README.md` のあいだで用語が衝突しない
- 未実装事項が、実装済みのように書かれていない
- 既存合意事項が消えていない
- 実装済み contract（`--days 7`, `--all-sessions`, `evidence_items[]`, `CLAUDE.md` immediate apply, `--dump-intents`）が plan から欠落していない

### 3. Mechanical Validation

以下は自動テストまたは手動実行で機械的に検証する。

- `aggregate.py --date today --all-sessions` を workspace 未指定で実行し、1 日分の timeline が返ること
- 出力の `sources[]` 各エントリに `scope` フィールド（`"all-day"` or `"workspace"`）が含まれること
- `aggregate.py --date today --all-sessions --workspace /path` を実行し、workspace source が絞られつつ `all-day` source は残ること
- `daily-report` を `自分用` / `共有用` それぞれで実行し、構成の違いが出力に反映されること
- `daily-report` を自然言語で `共有用` 指定した場合は ask なしで進み、mode 未指定時だけ入口 ask 1 回が出ること
- `post-draft` を引数なしで実行し、ask なしで narrative が生成されること
- `post-draft --reader "社内の非エンジニア"` で実行し、トーンが変わること
- `post-draft` の fixture サンプルをレビューし、主題選定と narrative 構成が破綻していないこと

### 4. Test Coverage

- `test_aggregate.py`: mixed-scope の `scope` フィールド検証を追加
- `post-draft` の主題選定は unit test 化せず、fixture ベースのサンプル確認で運用する
- 既存テストが全パスすること（回帰なし）

### 5. Future Implementation Validation

- date-first 化後も `daily-report` / `post-draft` が graceful degrade を維持できる
- scope-first のまま `skill-miner` の adaptive window を追加できる
- `0件` を減らしつつ巨大クラスタ増加を抑える説明ができる

## Demo Scenario (3 min)

ハッカソン審査員向けの 3 分デモシナリオ。

### 前提

- 審査員は Claude Code / Codex ヘビーユーザー
- デモ環境にはその日の実際の作業履歴がある
- 話す文言は「」内に記載。操作と画面の動きは [] 内に記載

### シナリオ

**0:00-0:30 — Hook（問題提起 → プロダクト紹介）**

「皆さん、今日ここまでに Claude Code で何をやったか、全部覚えていますか？」

「セッションを 3 つ、4 つと重ねると、朝やったことはもう曖昧ですよね。200 ターン回しても、翌朝には消えている。あの試行錯誤が、どこにも残らない。」

「DayTrace はそれを解決します。ローカルの証跡——Git、Claude Code、Codex、ブラウザ——を自動で集めて、日報にも、記事にも、スキルにも変える Claude Code plugin です。」

**0:30-1:15 — daily-report（Fact & Action）**

「まず、日報。今日の自分が何をしていたかを一撃で構造化します。」

[ターミナルで `/daily-report` を実行]

「共有用で出します。」

[「共有用」を選択。agent が aggregate.py を実行し、数秒で日報が生成される]

「質問は一切来ません。証跡を拾って、カテゴリに分けて、成果と課題を分離して、ここまで全自動です。」

[生成された日報を上からスクロールして見せる。カテゴリ分け・根拠ソース・Confidence が付いていることを指差す]

「source が足りない時も止まりません。取れた範囲で簡易版を出します。これが DayTrace の Fact & Action 層です。」

**1:15-2:15 — post-draft（Context & Narrative）**

「次に、同じ 1 日のデータから、記事の下書きを作ります。」

[ターミナルで `/post-draft` を実行。引数なし]

「引数ゼロ、質問ゼロ。今日一番密度が高かった作業を自動で選んで、narrative に仕立てます。」

[agent が実行を開始。数秒で記事の下書きが生成される]

「さっきの日報は『何をしたか』の事実整理でした。こっちは『なぜそれが面白いか』の物語です。同じデータから、Fact と Narrative の両方が出る。これが DayTrace のコントラストです。」

[下書きのタイトル・導入・学びセクションをスクロールして見せる]

「読者を変えたければ、`--reader` で指定するだけです。社内の非エンジニア向けなら、技術用語が消えてプロセスの話に変わります。」

**2:15-2:50 — skill-miner（反復抽出）**

「最後に、DayTrace の本丸です。」

[ターミナルで `/skill-miner` を実行]

「skill-miner は日報とは別の軸で動きます。過去 1 週間の AI との会話履歴を読んで、繰り返し現れるパターンを見つけます。」

[agent が prepare → triage → proposal のフェーズを進行する様子を見せる]

「見つかったパターンは、CLAUDE.md に書くべきルールなのか、skill にすべきか、hook にすべきかまで分類して提案します。」

[proposal の出力をスクロール。分類ラベルと根拠が付いていることを指差す]

「使えば使うほど、自分だけの作法が見えてくる。DayTrace は記録するだけでなく、成長を加速させます。」

**2:50-3:00 — Wrap（まとめ → Future Work）**

「collect、structure、narrate、learn。DayTrace は CLI エージェントの活動を、振り返りと成長に変えます。」

「今回はローカル証跡のみですが、将来的には抽出した文脈を構造化して蓄積し、skill-creator のような外部ツールに最高品質のデータを供給する Knowledge Pipeline を目指しています。」

「DayTrace でした。ありがとうございます。」

### デモ演出ノート

- 各スキルの実行中、ターミナルに aggregate.py や skill_miner_prepare.py のログが流れる。この「裏で動いている」感が自律性の説得力になる。無理に隠さない
- 日報と記事が「同じデータから出る」ことを強調するため、daily-report → post-draft の間に別の操作を挟まない。間を空けない
- skill-miner は proposal が出るまでの数秒間が一番緊張する。沈黙を恐れず「今、過去 1 週間の会話を読んでいます」と実況する
- Future Work は「1行だけ」言う。広げすぎない。Registry の schema スライドを1枚用意しておき、質疑で聞かれたら見せる

### Recovery Plan

本番環境で live 実行の条件が想定より薄い場合の切り返し方。固定 `demo/` 資産には頼らず、その場のローカル証跡と graceful degrade をそのまま説明する。

#### 事前準備（必須）

1. **source preflight の確認**: `python3 plugins/daytrace/scripts/aggregate.py --date today --all-sessions` を一度走らせ、`Source preflight:` と `sources[]` の見方を把握しておく
2. **当日メモ**: mixed-scope の説明、`daily-report` の mode 差分、`skill-miner` の 3 区分を短く言い直せるメモを手元に用意する
3. **広域観測の逃げ道**: `skill-miner` は必要なら `--all-sessions` で workspace 制限を外せることを把握しておく

#### 本番中の判断基準

- **source 0 本 / 履歴密度不足**: aggregate.py の空結果をそのまま見せ、「source が無い環境でも壊れず完走する」ことを説明する
- **aggregate.py がエラー**: まず `Source preflight:` と `sources[]` の確認に戻り、どの source が unavailable / skipped かを説明して live 実行を続ける
- **skill-miner が 0 件 proposal**: 「履歴が少ない、または反復が閾値未満だと 0 件も正常結果」と説明し、必要なら `--all-sessions` に切り替える
- **個別スキルの出力が薄い**: daily-report / post-draft は mixed-scope 注記や簡易出力も含めて graceful degrade の実例として扱う
- **全スキルで密度が不足**: README の最短検証手順に戻り、source 可用性と設計意図を説明して締める

#### やってはいけないこと

- デモ中に環境のデバッグを始めない
- 「本当はこう動くはずなんですが」と言わない
- その場の出力より、存在しない固定 fixture を正解扱いしない

## Success Criteria

- DayTrace の 3 skill が `date-first / date-first / scope-first` の役割分担で説明できる
- `daily-report` と `post-draft` の workspace は主軸ではなく補助フィルタだと明示されている
- workspace 指定が strict repo-only ではないと明示されている
- `skill-miner` の workspace は `cwd` ベース局所フィルタだと明示されている
- 前回合意事項を消さずに、新しい framing を上書きではなく積み上げで表現できている
- `daily-report` の 2 パターンの差分が定義されている
- `post-draft` の ask 設計・自動選定/推定ルールが確定し、実装可能なシグナルで定義されている
- mixed-scope contract が確定し、aggregate.py への変更差分が明確になっている
- description フィールドが媒体を限定しない文言になっている
- 入力インターフェース契約（自然言語抽出 / 引数なしデフォルト）が明記されている
- テスト計画が Files To Update に含まれ、追加すべきテストケースが特定されている
- 3 分デモシナリオに fallback plan が付いている
- Mechanical Validation の全項目が実行可能な状態になっている
