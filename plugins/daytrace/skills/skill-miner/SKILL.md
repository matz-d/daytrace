---
name: skill-miner
description: >
  Claude / Codex の全セッションを圧縮 candidate view で横断分析し、
  skill / plugin / agent / CLAUDE.md / hook のどれにすべきかを提案し、
  選択候補だけ detail を再取得してドラフト生成する。
user-invocable: true
---

# Skill Miner

AI 会話履歴の全セッションを横断して反復パターンを抽出し、自動化候補を提案し、選ばれた候補のドラフトまで生成する。

## Goal

- Claude / Codex の全履歴から反復作業パターンを見つける
- Python 側で candidate を圧縮・ランキングし、LLM は理由付けと 5 分類に集中する
- 各候補を `skill` / `plugin` / `agent` / `CLAUDE.md` / `hook` に分類する
- ユーザーが選んだ候補について、detail 再取得後に実装ドラフトを返す

## Inputs

aggregator は経由しない。`skill-miner` 専用の 2 つの CLI を使う。

スクリプトはこの `SKILL.md` と同じ plugin 内の `scripts/` ディレクトリにある。
この `SKILL.md` のあるディレクトリから `../..` を辿った先を `<plugin-root>` として扱う。
`skills/skill-miner/scripts/` は見に行かず、必ず plugin 直下の `scripts/` を使う。

提案フェーズ:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --all-sessions
```

選択後の detail 再取得:

```bash
python3 <plugin-root>/scripts/skill_miner_detail.py --refs "<session_ref_1>" "<session_ref_2>"
```

追加調査後の結論判定:

```bash
python3 <plugin-root>/scripts/skill_miner_research_judge.py --candidate-file /tmp/prepare.json --candidate-id "<candidate_id>" --detail-file /tmp/detail.json
```

最終 proposal 組み立て:

```bash
python3 <plugin-root>/scripts/skill_miner_proposal.py --prepare-file /tmp/prepare.json --judge-file /tmp/judge.json
```

repo root をカレントディレクトリとした場合の実コマンド例:

```bash
python3 plugins/daytrace/scripts/skill_miner_prepare.py --all-sessions
python3 plugins/daytrace/scripts/skill_miner_detail.py --refs "codex:abc123:1710000000"
python3 plugins/daytrace/scripts/skill_miner_research_judge.py --candidate-file /tmp/prepare.json --candidate-id "codex-abc123" --detail-file /tmp/detail.json
python3 plugins/daytrace/scripts/skill_miner_proposal.py --prepare-file /tmp/prepare.json --judge-file /tmp/judge.json
```

## Execution Rules

1. まず `skill_miner_prepare.py` を 1 回だけ実行する
2. `candidates` と `unclustered` を読み、まず `ready` / `needs_research` / `rejected` にトリアージする
3. `proposal_ready=true` の候補だけを正式提案候補にする。提案数は **0-5 件** を許容する
4. `needs_research` の候補があり、巨大クラスタや曖昧クラスタが原因なら、代表 `session_refs` だけで 1 回だけ追加調査する
5. 追加調査後に `skill_miner_research_judge.py` を実行し、`promote_ready` / `split_candidate` / `reject_candidate` を得る
6. judge の結論に応じて、正式提案に昇格させるか、`追加調査待ち` または `今回は見送り` に残す
7. 必要なら `skill_miner_proposal.py` で `提案成立` / `追加調査待ち` / `今回は見送り` を組み立てる
8. ユーザーに「どれをドラフト化するか」を確認する
9. 選択された候補の `session_refs` だけで `skill_miner_detail.py --refs ...` を実行する
10. detail を読んで、その候補に対応するドラフトを返す

## Division of Labor

### Python side

- raw Claude / Codex JSONL を直接読む
- Claude は時間 gap と `isSidechain` で論理 session に分割する
- packet を cluster 化して ranked `candidates` を返す
- `session_ref` を発行する
- 提案フェーズで読む candidate 数を Top N に絞る

### LLM side

- `candidates` を `ready` / `needs_research` / `rejected` に分ける
- `proposal_ready=true` の候補だけを 0-5 件提案する
- 必要な場合だけ `needs_research` 候補を追加調査する
- 追加調査後は `skill_miner_research_judge.py` の結論を proposal へ反映する
- 提案する候補だけを 5 分類へ仮分類する
- `なぜこの候補か` と `なぜその分類か` を説明する
- ユーザー選択後だけ detail を読んでドラフトを書く

やってはいけないこと:

- 提案フェーズで raw history 全量を読みに行く
- Python 側の cluster を捨てて全 candidate を再構築する
- ユーザーが選ぶ前に detail を大量取得する

## Prepare Output Reading Guide

`skill_miner_prepare.py` の主な読みどころ:

- `candidates`
  - ranked cluster 一覧
- `candidates[].support`
  - 出現回数、source 多様性、直近性
- `candidates[].confidence`
  - 候補の強さ。`strong` / `medium` / `weak` / `insufficient`
- `candidates[].proposal_ready`
  - そのまま提案可能か
- `candidates[].triage_status`
  - `ready` / `needs_research` / `rejected`
- `candidates[].quality_flags`
  - 巨大クラスタや汎用クラスタなどの注意信号
- `candidates[].evidence_summary`
  - 根拠の短い要約
- `candidates[].representative_examples`
  - 候補の代表例
- `candidates[].session_refs`
  - 選択後 detail 取得に使う参照キー
- `candidates[].research_targets`
  - `needs_research` 候補で優先的に detail 取得する ref と理由
- `candidates[].research_brief`
  - 追加調査で何を確認し、どの基準で `ready` / `split` / `rejected` を判断するか
- `unclustered`
  - cluster に乗らなかった孤立 packet。原則として提案しない
- `summary`
  - packet 数、candidate 数、blocking の規模
- `skill_miner_proposal.py` の出力
  - triage 済み candidate を人間向け proposal section に整形したもの

注意:

- `representative_examples` と `primary_intent` は圧縮済み
- path は `[WORKSPACE]` にマスクされる
- URL はドメインのみ残る

## Pattern Mining Rules

反復作業パターンは、以下の条件を優先して見つける。

- 同じ種類の依頼や手順が複数論理 session に出てくる
- 同じコマンド列や道具の組み合わせが繰り返される
- 毎回同じ説明や前提共有をしている
- 毎回同じ設定変更やテンプレート生成をしている
- 人間が毎回判断しているが、ルール化できそうなもの

候補化してよい例:

- 毎回似た形式のレポートや日報を作っている
- 毎回同じ review 手順と findings-first 出力を繰り返している
- 毎回同じ repo 初期設定や config 更新をしている
- 毎回同じ承認境界や出力フォーマットを説明している

候補化しない例:

- 単発の調査依頼
- プロジェクト固有すぎて再利用性が低いもの
- 1 回しか出ていないもの
- 外部事情に強く依存してテンプレ化しづらいもの

## Classification Rules

正式提案に進める候補だけ、次の 5 分類のどれか 1 つにする。

### `skill`

使う条件:

- 1 つの目的に対して複数ステップの定型フローがある
- 専用の入出力ルールや判断基準がある
- 将来も繰り返し使う価値がある

### `plugin`

使う条件:

- 複数 skill を束ねて初めて価値が出る
- install 可能なまとまりとして扱いたい
- marketplace / plugin 導線を含む配布単位にしたい

### `agent`

使う条件:

- 長めの役割定義や意思決定方針が必要
- 複数タスクを横断する一貫した振る舞いが価値の中心

### `CLAUDE.md`

使う条件:

- repo ローカルの常設ルールとして常に読ませたい
- 毎回同じ作法、禁則、出力方針を最初から共有したい
- 手順よりも原則の固定化が目的

### `hook`

使う条件:

- あるタイミングで自動実行したい
- 人が毎回明示的に呼ばなくてもよい
- lint, format, validation, logging のような機械的処理に向く

## Triage Rules

prepare の出力を読んだら、まず候補を 3 区分に分ける。

### `ready`

- `proposal_ready=true`
- `confidence` が `strong` または `medium`
- そのまま提案してよい

### `needs_research`

- 巨大クラスタ
- 汎用 task shape / 汎用 tool に偏る
- `quality_flags` に注意信号がある
- そのまま 5 分類へ押し込まない

### `rejected`

- `unclustered`
- `confidence=insufficient`
- 単発に近い、または一般化が弱い

ルール:

- 正式提案は **0-5 件** を許容する
- 強い候補が 0 件なら「今回は有力候補なし」と返してよい
- `unclustered` は参考情報にとどめ、件数合わせで提案に混ぜない
- `needs_research` 候補は、必要な場合だけ限定的に detail を取りに行く

## Proposal Format

提案フェーズでは、以下の 3 区分で返す。

```markdown
## 提案成立

1. 候補名
   分類: skill
   confidence: medium
   なぜこの候補か: 反復している作業内容の要約
   なぜその分類か: skill に向く理由
   根拠: Claude 2件 / Codex 3件 / 直近7日 2件
   期待効果: 何が短縮・安定化されるか

## 追加調査待ち

1. 候補名
   confidence: weak
   保留理由: 巨大クラスタで意味の異なる作業が混ざる可能性がある
   根拠: 63 packets / generic tools / generic task shapes

## 今回は見送り

1. 候補名または項目種別
   理由: 単発または一般化の根拠不足

確認したい候補がある場合だけ最後に聞く:
どの候補をドラフト化しますか？番号か候補名で指定してください。
```

提案ルール:

- `提案成立` だけを重要度順に並べる
- 各正式候補に `なぜその分類か` を必ず書く
- `根拠` は source 内訳、頻度、`confidence` を含める
- `追加調査待ち` には `保留理由` を必ず書く
- `今回は見送り` には 1 文で理由を書く
- 候補が 0 件でも、失敗扱いにしない

## Deep Research Rules

`needs_research` 候補に対してだけ、限定的な追加調査を行ってよい。

ルール:

- 1 candidate あたり最大 5 refs まで
- 追加調査は 1 回まで
- `research_targets` があればそれを優先して使う
- `research_brief.questions` と `research_brief.decision_rules` をそのまま調査メモの骨子に使う
- ランダム抽出ではなく、代表例に近い ref / near-match に近い ref / 異質そうな ref を混ぜる
- detail を大量取得しない
- 追加調査しても粒度が粗い場合は `今回は見送り` に落とす

追加調査後:

- `skill_miner_research_judge.py` を 1 回だけ実行して structured conclusion を得る
- `promote_ready`
  - `提案成立` へ移す
- `split_candidate`
  - `追加調査待ち` に残し、必要なら「分割軸」を書く
- `reject_candidate`
  - `今回は見送り` に移す

追加調査で確認すべきこと:

- 本当に 1 つの automation candidate か
- コードレビュー、調査、ログ整理のような別作業が混ざっていないか
- 分割するならどの軸が自然か
- 今回の proposal phase で正式提案すべきか、保留すべきか

## Selection Flow

`提案成立` に候補がある場合だけ、次の 1 問だけ聞く。

```text
どの候補をドラフト化しますか？番号か候補名で指定してください。
```

複数選択は求めない。まず 1 件だけ進める。

`提案成立` が 0 件なら、無理に選択を迫らない。

## Detail Phase Rules

ユーザーが正式候補を選んだら、選択候補の `session_refs` だけを `skill_miner_detail.py --refs ...` で取得する。

detail フェーズのルール:

- `session_refs` をそのまま CLI に渡す
- raw history 全量を取りに戻らない
- detail は選択候補のドラフト作成に必要な範囲だけ読む
- `errors` があれば無視せず短く注記する

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

## Graceful Degrade

- `summary.no_sources_available == true`
  - 利用可能な履歴が見つからなかったため候補提案できない旨を返す
- `candidates == []` かつ `unclustered` のみ
  - 反復パターンがまだ弱いと説明し、孤立候補があれば参考として 1-2 件だけ挙げる
- `detail` で一部 `session_ref` が解決できない
  - 解決できた detail だけでドラフトし、不足分を注記する

## Completion Check

提案フェーズでは以下を満たす。

- `skill_miner_prepare.py` を 1 回だけ実行している
- 3-5 件の候補があることを目標にしている
- 各候補に分類理由がある
- 根拠 source と件数がある

ドラフトフェーズでは以下を満たす。

- ユーザーが選んだ 1 件だけに集中する
- `session_refs` から detail を再取得している
- 選んだ分類に合った成果物になっている
- 実装可能な粒度まで落ちている

この skill は、提案 → 選択 → detail 再取得 → ドラフト生成までを一気通貫で進める前提で使う。
