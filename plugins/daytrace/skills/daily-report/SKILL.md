---
name: daily-report
description: >
  ローカル証跡を集約し、その日の活動を日報ドラフトとして自動生成する。
user-invocable: true
---

# Daily Report

その日のローカル証跡から、提出・共有前の下書きとして使える日報ドラフトを自動生成する。

## Goal

- ローカル証跡を自動収集し、3-6項目の日本語日報ドラフトにまとめる
- 各項目に根拠ソースを付ける
- 明日のアクションを提案する
- 不確実な点だけ最後に確認質問へ回す

## Inputs

- 対象日
  - 指定がなければ今日
  - 単日指定が基本。必要なら `YYYY-MM-DD` を明示する
- 対象 workspace
  - 指定がなければ現在の作業ディレクトリ

## Data Collection

必ず先に `aggregate.py` を実行し、中間 JSON を取得する。

`aggregate.py` はこの SKILL.md と同じ plugin 内の `scripts/` ディレクトリにある。
実行前に、まずこの SKILL.md の絶対パスからプラグインルートを特定し、そこからの相対パスで実行する。

今日の日報:

```bash
python3 <plugin-root>/scripts/aggregate.py --date today
```

特定日の日報:

```bash
python3 <plugin-root>/scripts/aggregate.py --date 2026-03-09
```

別 workspace を明示する場合:

```bash
python3 <plugin-root>/scripts/aggregate.py --workspace /absolute/path/to/workspace --date today
```

中間 JSON の主な読みどころ:

- `sources`: source ごとの `success / skipped / error`
- `timeline`: 時系列イベント
- `groups`: 近接イベントを束ねた活動グループ
- `summary`: 件数と source 利用状況

## Execution Rules

1. まず `aggregate.py` を 1 回だけ実行する
2. `groups` を優先して読み、必要に応じて `timeline` と `sources` を参照する
3. 日報の活動項目は 3-6 個に絞る
4. 単なる列挙ではなく、「その日何を進めたか」が伝わる粒度に再構成する
5. 根拠が弱い推定は断定しない
6. source が欠けていても処理を止めず、分かる範囲で出す

## Output Rules

出力は日本語 Markdown。以下の順序を守る。

```markdown
## 日報 YYYY-MM-DD

### 今日の概要
- 1-2文で全体要約

### 活動
1. 見出し
   内容: 2-4文
   根拠: git-history, codex-history
   Confidence: high

### 明日のアクション
- 2-4項目

### 確認したい点
- low confidence の項目だけ
```

各活動項目のルール:

- 3-6項目
- 1項目ごとに `根拠` と `Confidence` を必ず付ける
- `根拠` は source 名だけでなく、可能なら何のイベントを見たか短く添える
- 同じ内容を重複して書かない
- browser 履歴だけの項目は補助情報扱いにし、主項目にしすぎない
- `workspace-file-activity` だけで意味が確定しない場合は「作業痕跡」として控えめに表現する

## Confidence Handling

- `high`
  - そのまま本文に採用する
- `medium`
  - 本文に採用してよいが、推定を混ぜすぎない
- `low`
  - 本文に入れる場合は断定を避ける
  - 最後の `確認したい点` に回す

確認質問のルール:

- 質問は low confidence 項目だけ
- 最大 3 件まで
- yes/no か短文で答えられる聞き方にする
- high confidence / medium confidence の項目については原則質問しない

## Graceful Degrade

### source が 0 本

以下のような空日報を返す。

```markdown
## 日報 YYYY-MM-DD

### 今日の概要
- 利用可能なローカル証跡が見つからなかったため、自動生成できる情報はありませんでした。

### 明日のアクション
- Git、Claude/Codex、Chrome など少なくとも1系統の証跡が取れる状態で再実行する
```

### source が 1-2 本だけ

- 簡易日報として返す
- 断定的な振り返りを避ける
- `取得できた証跡は限定的` と明記してよい

## Authoring Prompt

中間 JSON を読んだら、以下の方針で日報を組み立てる。

- まず `sources` を見て、何が取れて何が欠けたかを把握する
- 次に `groups` を上から順に見て、その日の主要な活動塊を抽出する
- `git-history + claude/codex-history` が同じグループにある場合は、最優先で主要活動候補にする
- `chrome-history` は文脈補助として使い、単独では強い結論を作らない
- 進捗、実装、調査、整理、確認のどれに当たるかを短い動詞で表現する
- 未完了の作業が見える場合は、明日のアクションに自然につなぐ
- 事実と推定を混ぜない

## Completion Check

以下を満たすまで出力を確定しない。

- 日報本文が 3-6 項目に収まっている
- 各項目に根拠ソースがある
- 明日のアクションがある
- low confidence 項目だけが確認事項に分離されている
- source 欠損時も空出力ではなく、空日報または簡易日報になっている

この skill は、収集から日報ドラフト生成までを 1 コマンドで完走させる前提で使う。
