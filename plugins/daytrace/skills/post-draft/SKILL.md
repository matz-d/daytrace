---
name: post-draft
description: >
  ローカル証跡の集約結果から、テックブログ・チーム共有・Slack投稿の下書きを生成する。
user-invocable: true
---

# Post Draft

集約結果をもとに、用途別の投稿下書きを生成する。公開や送信は行わず、下書き生成で止める。

## Goal

- ローカル証跡から発信・共有用の下書きを自動生成する
- 用途ごとにトーンと粒度を切り替える
- source が欠けていても破綻しない短縮版を返す

## Inputs

- 用途
  - `tech-blog`
  - `team-summary`
  - `slack`
- 対象日
  - 指定がなければ今日
- 対象 workspace
  - 指定がなければ現在の作業ディレクトリ

## Purpose Selection

用途指定のインターフェースは対話で決める。

- ユーザーが `tech-blog` / `team-summary` / `slack` のいずれかを明示したら、そのまま使う
- 指定がない場合だけ、次の 1 問だけ聞く

```text
用途は tech-blog / team-summary / slack のどれにしますか？
```

## Data Collection

必ず先に `aggregate.py` を実行し、中間 JSON を取得する。

`aggregate.py` はこの SKILL.md と同じ plugin 内の `scripts/` ディレクトリにある。
実行前に、まずこの SKILL.md の絶対パスからプラグインルートを特定し、そこからの相対パスで実行する。

```bash
python3 <plugin-root>/scripts/aggregate.py --date today
```

特定日や別 workspace の場合:

```bash
python3 <plugin-root>/scripts/aggregate.py --date 2026-03-09
python3 <plugin-root>/scripts/aggregate.py --workspace /absolute/path/to/workspace --date today
```

中間 JSON の主な読みどころ:

- `sources`: 利用できた source と欠損 source
- `groups`: まとまりとして扱うべき活動塊
- `timeline`: 詳細な時系列
- `summary`: 件数と欠損状況

## Output Formats

### `tech-blog`

- 用途
  - 学びや実装の流れを、第三者が読める形で整理する
- トーン
  - 文章中心、説明的、再利用可能な学びを前に出す
- 粒度
  - 背景、やったこと、詰まった点、学び、次の改善まで含める
- 期待する長さ
  - 見出しつきの下書き 600-1200 字程度

### `team-summary`

- 用途
  - チームメンバーに進捗と判断材料を短く共有する
- トーン
  - 簡潔、実務的、箇条書き中心
- 粒度
  - 何を進めたか、何が決まったか、何が未解決か
- 期待する長さ
  - 5-10 bullet 程度

### `slack`

- 用途
  - Slack にそのまま貼れる短い共有文を作る
- トーン
  - カジュアル寄りだが業務利用前提
- 粒度
  - 今日の一番大きい進捗、次の一手、必要なら依頼
- 期待する長さ
  - 3-8 行程度

## Execution Rules

1. 用途を決める
2. `aggregate.py` を 1 回だけ実行する
3. `groups` を優先して読み、用途に合わせて並べ替える
4. 事実と推定を分ける
5. confidence が低い内容は過剰に膨らませない
6. 公開・送信はせず、下書きだけ返す

## Reconstruction Prompt

集約結果から用途別に要点を再構成するときは、以下の方針を守る。

- `git-history + claude/codex-history` が同じ活動グループにあるものを優先的に主題化する
- `chrome-history` は補助的文脈としてのみ使う
- `workspace-file-activity` 単独の場合は「作業痕跡」として控えめに扱う
- 何をしたかだけでなく、なぜ意味があるかを用途に応じて言い換える
- 実装、調査、設計、判断、詰まり、次アクションを切り分ける
- low confidence の内容は本文で断定せず、必要なら最後に確認事項として分離する

## Format Rules

### `tech-blog`

以下の構成で返す。

```markdown
# タイトル案

## 導入

## 今日やったこと

## 詰まった点 / 工夫した点

## 学び

## 次にやること
```

ルール:

- 事実ベースで書く
- 読者が再現しやすい粒度を意識する
- 具体的なファイル名や source 名を必要に応じて本文へ入れてよい
- marketing copy ではなく、実装記録寄りにする

### `team-summary`

以下の構成で返す。

```markdown
## Team Summary

- 今日の進捗:
- 主な証拠:
- 未解決:
- 次のアクション:
```

ルール:

- 箇条書き中心
- 判断・進捗・リスクを優先
- 長い背景説明は削る

### `slack`

以下の構成で返す。

```markdown
今日の進捗メモです。
- ...
- ...
次: ...
```

ルール:

- そのまま貼れる短さにする
- 1投稿に収まる密度を優先する
- 必要があれば最後に `確認したい点` を 1 行だけ入れる

## Graceful Degrade

### source が 0 本

用途を問わず、短縮版を返す。

- `tech-blog`
  - 記事化できる十分な証跡がなかった旨を明記し、次回必要な source を 1-2 行で添える
- `team-summary`
  - `共有できる自動収集証跡なし` と短く返す
- `slack`
  - `今日は自動収集できる証跡が少なく、下書きは簡易版です。` のように一言で返す

### source が限定的

- 出力は短縮する
- 断定表現を避ける
- `取得できた証跡は限定的` と明記してよい

## Sample Outputs

### Sample: `tech-blog`

```markdown
# DayTrace の source CLI をまとめる aggregator を実装した話

## 導入
今日は DayTrace の集約レイヤーを実装し、複数のローカル証跡を 1 つの中間 JSON に統合できる状態まで進めた。

## 今日やったこと
`sources.json` を起点に source CLI を並列実行する `aggregate.py` を追加した。`git-history`、`claude-history`、`codex-history`、`chrome-history`、`workspace-file-activity` の結果を正規化して、時系列の `timeline` と近接イベントの `groups` にまとめるようにした。

## 詰まった点 / 工夫した点
source ごとの成功・スキップ・エラーの shape が違うため、aggregator 側で統一した。Chrome や履歴系 source が欠けても全体が止まらないようにしている。

## 学び
実際の出力スキルを作る前に、中間 JSON の shape を固定したのが効いた。後段の daily-report や post-draft は `groups` と `sources` を読むだけで済む。

## 次にやること
daily-report と post-draft の SKILL.md を仕上げて、出力層をつなぐ。
```

### Sample: `team-summary`

```markdown
## Team Summary

- 今日の進捗: aggregator 本体を追加し、5 source の統合 JSON を返せるようにした
- 主な証拠: `aggregate.py`、stub 結合テスト、5 source 実行確認
- 未解決: Chrome 起動中ロック状態での読取確認は未完了
- 次のアクション: daily-report と post-draft の出力設計を固める
```

### Sample: `slack`

```markdown
今日の進捗メモです。
- DayTrace の aggregator を実装して、5 source を 1 つの JSON に統合できるようにしました
- `success / skipped / error` の正規化と近接イベントのグルーピングまで入っています
- 次は daily-report / post-draft の出力層を仕上げます
```

この skill は、用途指定だけで下書きを返す前提で使う。
