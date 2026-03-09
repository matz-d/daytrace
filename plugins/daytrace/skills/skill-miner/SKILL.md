---
name: skill-miner
description: >
  Claude / Codex の全セッションを横断して反復作業を抽出し、
  skill / plugin / agent / CLAUDE.md / hook のどれにすべきかを分類・ドラフト生成する。
user-invocable: true
---

# Skill Miner

AI 会話履歴の全セッションを横断して反復パターンを抽出し、自動化候補を提案し、選ばれた候補のドラフトまで生成する。

## Goal

- Claude / Codex の全セッションから反復作業パターンを見つける
- 各候補を `skill` / `plugin` / `agent` / `CLAUDE.md` / `hook` に分類する
- 各候補について「なぜその分類か」を説明する
- ユーザーが選んだ候補について、実装ドラフトまで返す

## Inputs

aggregator は経由せず、以下のソース CLI を直接実行する。

スクリプトはこの SKILL.md と同じ plugin 内の `scripts/` ディレクトリにある。
この `SKILL.md` のあるディレクトリから `../..` を辿った先を `<plugin-root>` として扱う。
`skills/skill-miner/scripts/` は見に行かず、必ず plugin 直下の `scripts/` を使う。

```bash
python3 <plugin-root>/scripts/claude_history.py --all-sessions
python3 <plugin-root>/scripts/codex_history.py --all-sessions
```

repo root が `/Users/makotomatuda/projects/lab/daytrace` の場合の実コマンド例:

```bash
python3 plugins/daytrace/scripts/claude_history.py --all-sessions
python3 plugins/daytrace/scripts/codex_history.py --all-sessions
```

期間制限なしで全セッションを対象とする。

## Execution Rules

1. `claude_history.py` と `codex_history.py` を全セッションモードで 1 回ずつ実行する
2. `session_summary` / `commentary` / `tool_call` から反復作業を抽出する
3. 類似した作業をまとめ、候補単位に要約する
4. 各候補を 5 分類のどれかに振り分ける
5. まず提案リストだけを出す
6. ユーザーに「どれをドラフト化するか」を確認する
7. 選択された候補だけドラフト生成に進む

## Pattern Mining Rules

反復作業パターンは、以下の条件を優先して見つける。

- 同じ種類の依頼や手順が複数セッションに出てくる
- 同じコマンド列や道具の組み合わせが繰り返される
- 毎回同じ説明や前提共有をしている
- 毎回同じ設定変更やテンプレート生成をしている
- 人間が毎回判断しているが、ルール化できそうなもの

候補化してよい例:

- 毎回似た形式のレポートや日報を作っている
- 毎回同じセットの履歴ソースを読んで分析している
- 毎回同じ repo 初期設定や review 手順を踏んでいる
- 毎回同じ承認境界や出力フォーマットを説明している

候補化しない例:

- 単発の調査依頼
- プロジェクト固有すぎて再利用性が低いもの
- 単に1回しか出ていない作業
- 外部事情に強く依存してテンプレ化しづらいもの

## Classification Rules

候補は必ず次の 5 分類のどれか 1 つにする。

### `skill`

使う条件:

- 1つの目的に対して複数ステップの定型フローがある
- 専用の入出力ルールや判断基準がある
- 将来も繰り返し使う価値がある

例:

- 日報作成
- 特定形式のレビュー
- まとめ記事ドラフト

### `plugin`

使う条件:

- 複数 skill を束ねて 1 つの配布単位にしたい
- install 可能なまとまりとして扱いたい
- skill 単体ではなく marketplace / plugin 導線が必要

### `agent`

使う条件:

- 長めの役割定義や意思決定方針が必要
- 複数タスクを横断する人格・責務・作法を持たせたい
- skill より広い振る舞いの一貫性が重要

### `CLAUDE.md`

使う条件:

- repo ローカルの常設ルールとして常に読ませたい
- 毎回同じ作法、禁則、出力方針を最初から共有したい
- 手順よりも作業原則の固定化が目的

### `hook`

使う条件:

- あるタイミングで自動実行したい
- 人が毎回明示的に呼ばなくてもよい
- lint, format, validation, logging のような機械的処理に向く

## Proposal Format

提案フェーズでは、必ず 3 件以上の候補を目標にし、以下の形式で返す。

```markdown
## 自動化候補

1. 候補名
   分類: skill
   なぜこの候補か: 反復している作業内容の要約
   なぜその分類か: skill に向く理由
   根拠: Claude 2件 / Codex 3件 / tool call 12件
   期待効果: 何が短縮・安定化されるか

2. 候補名
   分類: CLAUDE.md
   なぜこの候補か: ...
   なぜその分類か: ...
   根拠: ...
   期待効果: ...
```

提案ルール:

- 候補は重要度順に並べる
- 各候補に `なぜその分類か` を必ず書く
- `根拠` は出現頻度だけでなく、どのソースに現れたかも書く
- 曖昧な候補は順位を下げる

## Selection Flow

提案リストを出したら、次の 1 問だけ聞く。

```text
どの候補をドラフト化しますか？番号か候補名で指定してください。
```

複数選択は求めない。まず 1 件だけ進める。

## Draft Generation Rules

選択された候補に応じて、次の成果物を返す。

### `skill`

- `SKILL.md` ドラフト
- 必要なら補助スクリプト案

### `plugin`

- `plugin.json` ドラフト
- 代表 `SKILL.md` ドラフト
- plugin に含めるべき skill 構成案

### `agent`

- 役割定義
- 行動原則
- 入出力方針
- 想定トリガー

### `CLAUDE.md`

- 追記すべきルール案
- 適用対象
- 具体的な記述例

### `hook`

- hook の発火タイミング
- 実行内容
- 設定例
- 副作用や注意点

## Draft Output Format

ドラフト生成フェーズでは、最初に短い判断メモを付ける。

```markdown
## 選択候補
- 候補:
- 分類:
- この形にした理由:

## ドラフト
...
```

## Completion Check

提案フェーズでは以下を満たす。

- 候補が 3 件以上あることを目標にする
- 各候補に分類理由がある
- 根拠ソースがある

ドラフトフェーズでは以下を満たす。

- ユーザーが選んだ 1 件だけに集中する
- 選んだ分類に合った成果物になっている
- 実装可能な粒度まで落ちている

この skill は、提案 → 選択 → ドラフト生成までを一気通貫で進める前提で使う。
