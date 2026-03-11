---
name: post-draft
description: >
  1日の活動ログから、その日全体の流れを読者向け narrative draft に再構成する。記事を書きたい、ブログにまとめたい、ふりかえりを書きたい、学びを共有したい時に使う。topic / reader は任意で上書きできる。
user-invocable: true
---

# Post Draft

その日のローカル証跡から、date-first で narrative draft を組み立てる。
主目的は媒体を選ぶことではなく、その人だけが書ける一次情報ベースの `Context & Narrative` を下書き化すること。

## Goal

- 1 日全体の活動ログから、公開前の narrative draft を 1 本組み立てる
- `workspace default` ではなく `date-first default + optional workspace filter` として扱う
- 入口 ask なしで完走し、必要なら `topic` と `reader` だけ optional override として受け付ける
- 読者に応じてトーン、構成、説明粒度を自動で切り替える
- source が欠けていても narrative が破綻しない短縮版を返す

## Inputs

- 対象日
  - 指定がなければ `today`
  - 単日指定を基本とし、必要なら `YYYY-MM-DD` を使う
- reader
  - 任意
  - 未指定時は自動推定する
- topic
  - 任意
  - 未指定時は narrative policy で自動選定する
- workspace
  - 任意
  - 主軸ではなく補助フィルタ
  - 特定 workspace の git / file 根拠を強めたい時だけ使う
  - 現状の source 実装では、workspace を指定しても `claude-history` / `codex-history` / `chrome-history` はその日全体の証跡を返しうる
  - したがって strict な repo 限定指定ではなく、mixed-scope の内訳を制御する補助情報として扱う

## Entry Contract

入力は自然言語抽出と引数なし実行の 2 経路を前提にする。

### 自然言語からの抽出

- 「今日の記事を書きたい」「昨日の学びをブログ向けにまとめたい」などから日付を抽出する
- 「非エンジニア向けに」「個人ブログ向けに」などから `reader` を抽出する
- 「aggregate.py の話で」「scope の変更について」などから `topic` を抽出する
- 「daytrace の」「`/path/to/repo` で」などから workspace を抽出する

### 引数なし実行

- ask は 0 回に固定する
- 日付は `today` を使う
- `reader` は自動推定する
- `topic` は narrative policy で自動選定する
- workspace は未指定のまま date-first で進める

### 追加 ask の禁止

- 入口でも途中でも質問しない
- source 欠損や low confidence が見えても追加 ask しない
- 抽出できなかった情報はデフォルト値で埋める

## Data Collection

必ず最初に `aggregate.py` を 1 回だけ実行し、中間 JSON を取得する。

`aggregate.py` はこの `SKILL.md` と同じ plugin 内の `scripts/` ディレクトリにある。
この `SKILL.md` のあるディレクトリから `../..` を辿った先を `<plugin-root>` として扱う。

date-first デフォルト:

```bash
python3 <plugin-root>/scripts/aggregate.py --date today --all-sessions
```

特定日:

```bash
python3 <plugin-root>/scripts/aggregate.py --date 2026-03-09 --all-sessions
```

workspace の git / file 根拠を current repo に固定したい場合:

```bash
python3 <plugin-root>/scripts/aggregate.py --date today --all-sessions --workspace /absolute/path/to/workspace
```

この指定の意味:

- `git-history` と `workspace-file-activity` は `--workspace` で絞り込まれる
- `claude-history` / `codex-history` は `--all-sessions` が付くと workspace を無視する
- `chrome-history` は現状常に workspace を無視する
- したがって downstream の生成では `sources[].scope` を見て、repo ローカルの根拠と全日根拠を混同しない

中間 JSON の主な読みどころ:

- `sources`: source ごとの `success / skipped / error / scope`
- `groups`: 近接イベントを束ねた活動グループ
- `timeline`: 詳細な時系列
- `summary`: 件数と source 利用状況

## Scope Contract

この skill は date-first だが、source には `all-day` と `workspace` の 2 種類がある。

- `all-day`
  - その日全体を代表する証跡
  - 例: `claude-history`, `codex-history`, `chrome-history`
- `workspace`
  - 指定 workspace または current working directory に依存する証跡
  - 例: `git-history`, `workspace-file-activity`

workspace 未指定でも、出力は全日 source と cwd 起点の workspace source が混在しうる。
workspace 指定時も mixed-scope は解消されず、repo ローカルの根拠密度が上がるだけで `all-day` source まで strict な repo filter にはならない。
date-first の narrative を組み立てつつ、mixed-scope を隠さないこと。

## Narrative Policy

主題選定は Python helper に切り出さず、この `SKILL.md` の policy として実装する。
`aggregate.py` が返す `groups` / `events` を読み、主題選定と narrative 構成を一体で行うこと。

### 主題選定の優先順位

`--topic` が明示されている場合は、それを最優先する。
未指定時は `groups` から以下の 3 段フォールバックで主題を 1 つ選ぶ。

#### 優先度 1: AI + Git 共起グループ

- 条件: `sources` に `git-history` と (`claude-history` または `codex-history`) が両方含まれる
- 複数該当時: `event_count` が最大の group を選ぶ
- 根拠: AI との対話と実際のコミットが同時間帯にある group は、実作業の密度が最も高い

#### 優先度 2: AI 密度グループ

- 条件: `confidence_categories` に `ai_history` を含み、かつ group 内の `claude-history` / `codex-history` イベント数が 3 件以上
- 複数該当時: AI イベント数が最大の group を選ぶ
- 根拠: AI との対話が集中している group は、試行錯誤の narrative を組み立てやすい

#### 優先度 3: 最大イベント数グループ

- 条件: 上記に該当しない場合
- 選び方: `event_count` が最大の group を選ぶ
- 根拠: 補助証跡しかなくても、その日の中心的な活動塊を最低限拾う

### 主題の広げ方

- 選んだ group を narrative の中心に据える
- 周辺 group は背景、前提、判断、次の一手として補助的に接続する
- 主題が 1 つでも、本文は単なる group 要約にしない
- `events[].summary` や `type` から、転換点、詰まり、判断理由、学びを narrative 構成で拾う
- 「学びの転換点」の判定は決定論的 helper ではなく LLM の narrative 構成フェーズで行う

## Reader Policy

優先順位は `--reader` override > 自然言語から抽出した reader > デフォルト読者 とする。

### デフォルト読者

- 自然言語から `reader` を抽出できた場合はそれを使う
- 抽出できず、`--reader` override も無い場合のデフォルトは `同じ技術スタックを使う開発者`

### `--reader` override

- `reader` が明示されている場合は、その読者像に合わせてトーンと粒度を調整する
- 例: `--reader "社内の非エンジニア"` の場合、技術用語を減らし、背景、プロセス、成果を中心に書く
- 例: `--reader "個人ブログの読者"` の場合、一人称で試行錯誤や学びのストーリーを前に出す

### 自動判定ルール

ask は使わず、読者と主題から以下を自動で決める。

- トーン
  - 技術者向け: 具体的、再現可能、実装寄り
  - 非技術者向け: プロセス、判断、成果中心。技術用語は必要最小限に言い換える
  - 個人ブログ向け: 一人称、試行錯誤、学びの転換点を前に出す
- 構成
  - 実装系主題: 背景 / 何を変えたか / 詰まった点 / 学び / 次の一手
  - 調査系主題: 動機 / 比較したもの / 判断 / 結論
  - 設計系主題: 課題 / 選択肢 / 採用理由 / 残課題
- 長さ
  - 600-1200 字を基本とする
  - source が薄い日は短くしてよい
  - reader が非技術者寄りの場合は背景説明を少し厚くし、詳細実装は削る

## Execution Rules

1. `aggregate.py` を 1 回だけ実行する
2. 先に `sources` を読み、取得できた source と `scope` を把握する
3. 次に `groups` を読み、主題選定の 3 段フォールバックで中心 group を決める
4. 必要に応じて `timeline` を補助参照し、背景や前後関係を補う
5. workspace 指定があっても `all-day` source を repo 限定の根拠として扱わない
6. narrative は 1 本通った話として組み立てる
7. `chrome-history` は補助的文脈として使い、単独では主題化しすぎない
8. `workspace-file-activity` 単独の場合は「作業痕跡」として控えめに扱う
9. 事実と推定を分け、confidence が低い内容は過剰に膨らませない
10. 公開・送信はせず、下書きだけ返す
11. `team-summary` / `slack` を main UX に戻さない

## Output Rules

出力は日本語 Markdown。
少なくとも以下の要素を含む narrative draft として返す。

- `# タイトル案`
- 導入または背景
- その日の中心的な出来事
- 詰まり / 判断 / 学びのいずれか
- 次の一手

### 共通ルール

- 1 本の narrative として読み通せる流れにする
- group の列挙で終わらせず、背景と意味づけを入れる
- source 名やファイル名は必要な範囲で本文に出してよい
- 根拠が薄い箇所は断定しない
- `確認したい点` セクションは作らない
- low confidence は本文内の注記で処理する
- 読者に合わせて専門用語の量と説明密度を変える

### 技術者向けの基本構成

```markdown
# タイトル案

## 背景

## 何を進めたか

## 詰まった点 / 判断したこと

## 学び

## 次にやること
```

### 非技術者向け override の構成

```markdown
# タイトル案

## 何に取り組んだか

## どう進めたか

## 何が分かったか

## 次のアクション
```

## Mixed-Scope Note Rules

成功した `sources[]` の `scope` を見て、冒頭の注記要否を決める。

- `all-day` と `workspace` の両方が含まれる場合
  - 導入直後か blockquote で 1 回だけ mixed-scope 注記を入れる
  - 例:
    - `Claude/Codex/Chrome はその日全体の証跡、Git とファイル変更は current workspace に限定された証跡です。`
    - `1 日全体の流れをもとに構成していますが、repo ローカルの変更根拠は current workspace に限られます。`
- `all-day` のみ、または `workspace` のみの場合
  - mixed-scope 注記は必須ではない
- 注記は coverage の誤認を防ぐための事実説明に留める
  - narrative の価値を過度に弱めない

## Confidence Handling

- `high`
  - そのまま narrative に採用する
- `medium`
  - narrative に採用してよい
  - 必要なら `と見られる` `中心だった` などで断定を弱める
- `low`
  - narrative に入れる場合は inline 注記にする
  - 例:
    - `注記: ファイル変更からは確認できるが、最終的な意図は断定できない`
    - `注記: Chrome 履歴由来の補助情報で、着手の確度は高くない`
  - 別セクションへ分離しない
  - 追加 ask を発生させない

## Graceful Degrade

source 欠損の判定は `summary` と `sources` から行う。

- `summary.no_sources_available == true` または `source_status_counts.success == 0`
  - `source が 0 本` とみなす
- `source_status_counts.success` が 1-2
  - `source が 1-2 本だけ` とみなす
- `sources[].status` に `skipped` / `error` があっても、成功 source が残っていれば継続する

### source が 0 本

以下のような空 narrative を返す。

```markdown
# タイトル案

## 背景
利用可能なローカル証跡が見つからず、その日の活動から narrative を組み立てられなかった。

## 次にやること
- Git、Claude/Codex、Chrome など少なくとも 1 系統の証跡が取れる状態で再実行する
```

### source が 1-2 本だけ

- 短縮版 narrative として返す
- `取得できた証跡は限定的` と導入で明記してよい
- 断定的なストーリー化を避ける
- それでも `タイトル / 背景 / 中心的な出来事 / 次の一手` の骨格は維持する

## Compatibility Note

- 旧 `team-summary` 的な共有は、main UX ではなく `daily-report` の `共有用` へ役割を移したとみなす
- 旧 `slack` 用途は main UX から外す
- 互換説明は残してよいが、description や sample output の中心には置かない

## Verification Policy

- 主題選定そのものを unit test の pass/fail 条件にはしない
- 理由: `post-draft` の価値は wording と narrative continuity にあり、決定論的 helper に閉じないから
- 検証は fixture ベースの sample review で行う
- 自動テストは `aggregate.py` の shape、mixed-scope 表示、graceful degrade など決定論的な部分だけに限定する

サンプルと fixture review 手順は `references/sample-outputs.md` を参照すること。

## Completion Check

以下を満たすまで出力を確定しない。

- `post-draft` が `Context & Narrative` の skill として一貫して説明されている
- main UX が `0 ask + optional override` になっている
- `team-summary` / `slack` が main UX から外れている
- 主題選定の 3 段フォールバックが `SKILL.md` だけで読める
- 主題選定を Python helper に切り出さないと明記されている
- `reader` の自動推定と `--reader` override の扱いが読める
- workspace 指定が strict repo filter ではないと読める
- mixed-scope 注記ルールが `sources[].scope` ベースで一意に読める
- unit test を書かない理由と fixture review による代替検証が文書化されている

この skill は、その日の一次情報から narrative draft を 1 コマンドで完走させる前提で使う。
