---
name: skill-miner
description: >
  Claude / Codex 履歴から反復パターンや定着させたい作法を抽出し、
  recurring workflow / repeated instruction を
  `CLAUDE.md` / `skill` / `hook` / `agent` のどれに固定すべきか評価して proposal を返す。
user-invocable: true
---

# Skill Miner

AI 会話履歴を横断して、固定化すべき作法を `extract / classify / evaluate / propose` するための skill。

## Goal

- Claude / Codex 履歴から反復パターンを抽出する
- 候補を `CLAUDE.md` / `skill` / `hook` / `agent` の 4 分類で判定する
- `提案（固定化を推奨） / 有望候補（もう少し観測が必要） / 観測ノート` の main UX で返す
- proposal phase では raw history を再読込せず、prepare の contract だけで根拠表示を完結させる

やらないこと:

- `plugin` 分類
- `skill` / `hook` / `agent` の即時生成
- `daily-report` / `post-draft` の処理

## Inputs

aggregator は使わない。`skill-miner` 専用 CLI だけを使う。

スクリプトはこの `SKILL.md` と同じ plugin 内の `scripts/` にある。
このディレクトリから `../..` を辿った先を `<plugin-root>` として扱う。

提案フェーズ:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --input-source auto --store-path ~/.daytrace/daytrace.sqlite3
```

workspace 制限を外して広域観測する場合:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --input-source auto --store-path ~/.daytrace/daytrace.sqlite3 --all-sessions
```

補足:

- デフォルト観測窓は 7 日
- `--all-sessions` は workspace 制限を外すだけで、7 日窓は維持する
- `--input-source auto` は store-backed `observations` を優先し、該当データが無い時だけ raw history へフォールバックする
- `--store-path` を付けると candidate を `patterns` として store へ更新し、旧 raw path との比較が必要な期間は `--compare-legacy` を併用できる
- `workspace` モード（`--all-sessions` を付けない通常実行。`--workspace` 未指定時は `cwd` を使う）だけ、packet / candidate が少なすぎる場合に 30 日へ自動拡張する
- full-history 相当の観測が必要な場合は、B0 観測（改善優先度を決めるための実データ観測）用に `--all-sessions --days 3650 --dump-intents` のように明示する

追加調査の detail 再取得:

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

## Execution Rules

1. まず `skill_miner_prepare.py` を 1 回だけ実行する
2. デフォルト観測窓は `7` 日
3. `--all-sessions` は workspace 制限を外すモードであり、無制限読み込みではない
4. `workspace` モード（`--all-sessions` なし）は 7 日で開始し、packet / candidate が少なすぎる時だけ 30 日へ自動拡張する
5. adaptive window は `workspace` モードにだけ持たせる
6. 実行モードは CLI 引数だけで決める。state file は持たない
7. `candidates` と `unclustered` を `ready` / `needs_research` / `rejected` に分ける
8. 正式提案は `proposal_ready=true` の候補だけを採用し、返却件数は `prepare` 側の `top_n` に従う（デフォルト `10`）。`0 件` でも正常系として扱う
9. `needs_research` 候補だけ、必要な場合に限って `research_targets` を使って 1 回だけ追加調査する
10. `skill_miner_research_judge.py` の結論を proposal に反映し、`提案（固定化を推奨） / 有望候補 / 観測ノート` を返す
11. `提案（固定化を推奨）` がある時だけ、次セッションでどれを apply するかを確認する

## Division of Labor

### Python side

- raw Claude / Codex JSONL を直接読む
- Claude は時間 gap と `isSidechain` で logical session に分割する
- packets を cluster 化して ranked `candidates` を返す
- `session_ref` を発行する
- candidate ごとに `evidence_items[]` を最大 3 件作る
- `--dump-intents` 指定時だけ `intent_analysis` を返す

### LLM side

- `candidates` を 3 区分にトリアージする
- 正式提案に進める候補だけを 4 分類へ仮分類する
- `なぜこの候補か` と `なぜその分類か` を説明する
- `CLAUDE.md` 候補だけ immediate apply の仕様説明を返してよい
- `skill` / `hook` / `agent` は次セッションの apply フローへ送る

やってはいけないこと:

- proposal phase で raw history を読み直す
- Python 側の cluster を捨てて candidate を再構築する
- ユーザーが選ぶ前に detail を大量取得する

## Prepare Output Reading Guide

`skill_miner_prepare.py` の主な読みどころ:

- `config.days`
  - 初期観測窓。通常は `7`
- `config.effective_days`
  - 実際に使われた観測窓。workspace adaptive window で `30` になる場合がある
- `config.all_sessions`
  - `true` の時は workspace 制限だけを外す
- `config.adaptive_window`
  - workspace モード（`--all-sessions` なし）で 30 日へ拡張したか、その判定基準と初期件数
- `summary.adaptive_window_expanded`
  - adaptive window が発火したかどうか
- `candidates[].support`
  - 出現回数、source 多様性、直近性
- `candidates[].confidence`, `proposal_ready`, `triage_status`
  - 候補の強さと triage 結果
- `candidates[].evidence_items`
  - proposal 用の根拠チェーン
- `candidates[].research_targets`
  - `needs_research` 候補で優先して detail を取る ref
- `candidates[].research_brief`
  - 追加調査で見るべき観点
- `intent_analysis`
  - `--dump-intents` 指定時だけ出る B0 観測用サマリ

`evidence_items[]` contract:

```json
{
  "session_ref": "codex:abc123:1710000000",
  "timestamp": "2026-03-10T09:00:00+09:00",
  "source": "codex-history",
  "summary": "SKILL.md の構造確認を行い、提案理由を整理"
}
```

注意:

- `primary_intent` は packet ごとの主目的を短く正規化した文字列
- `summary` は `primary_intent` 優先、空なら snippet 由来
- `proposal` 側は `evidence_items[]` を使って表示し、raw history を再読込しない
- path は `[WORKSPACE]`、URL はドメインだけにマスクされる

## Classification Rules

分類先は 4 つだけ使う。詳細な境界ケースは `references/classification.md` を参照する。
B0 観測の方法と優先順位ルールは `references/b0-observation.md` を参照する。

- `CLAUDE.md`
  - repo ローカルで毎回守らせたい原則
- `skill`
  - 明確な入出力を持つ多段フロー
- `hook`
  - 判断不要で自動実行向きの機械処理
- `agent`
  - 継続的な役割や行動原則が価値の中心

除外:

- `plugin`
  - v2 の一次分類では使わない

## Triage Rules

### `ready`

- `proposal_ready=true`
- `confidence` が `strong` または `medium`

### `needs_research`

- 巨大クラスタ
- 汎用 task shape / 汎用 tool に偏る
- `quality_flags` に注意信号がある

### `rejected`

- `unclustered`
- `confidence=insufficient`
- 単発に近い、または一般化が弱い

ルール:

- 正式提案の返却件数は `prepare` 側の `top_n` に従う（デフォルト `10`）
- `0 件` でも失敗扱いにせず、理由と次回への示唆を返す
- `needs_research` 候補は必要な場合だけ detail を取る

## Proposal Format

proposal の冒頭には観測範囲を明示し、3 区分で返す。
内部 triage key（`ready` / `needs_research` / `rejected`）はそのままで、ユーザー向け見出しだけを変更する。

```markdown
### 観測範囲
観測範囲: {workspace名} / 直近 {N}日間 / {使用した source リスト}

## 提案（固定化を推奨）

1. 候補名
   固定先: skill
   confidence: medium
   根拠:
   - 2026-03-08T10:00:00+09:00 claude-history: findings-first review を要求
   - 2026-03-10T09:00:00+09:00 codex-history: 同系の review 指示を再確認
   期待効果: 同種作業の再利用フローを安定化できる
   → この作法を固定すれば、毎回の指示が不要になります

## 有望候補（もう少し観測が必要）

1. 候補名
   confidence: weak
   出現: 3回 / 2ソース
   根拠:
   - 2026-03-08T10:00:00+09:00 claude-history: 汎用 review 指示
   現状: 巨大クラスタで意味の異なる作業が混ざる可能性がある
   次のステップ: 1-2 週間の運用後に再観測で分割判断

## 観測ノート

1. 候補名または項目種別
   理由: 単発または一般化の根拠不足
```

ルール:

- `提案（固定化を推奨） / 有望候補 / 観測ノート` を main UX にする
- `提案（固定化を推奨）` だけを重要度順に並べる
- `有望候補` には `現状` と `次のステップ` を書く
- `観測ノート` には 1 文で理由を書く
- `提案（固定化を推奨）` が 1 件以上ある時だけ、末尾に候補選択プロンプトを付けて次セッションの apply / draft 選択へ進める

### 0 件時の出力

`proposal_ready=true` の候補が 0 件の場合も正常系として、以下を返す:

```markdown
### 観測範囲
観測範囲: {workspace名} / 直近 {N}日間 / {source}

## 提案（固定化を推奨）
今回は有力候補なし

検出候補数: {N}件中 0 件が提案条件を満たした
見送り理由の傾向: {主な理由（例: 観測窓が短い / oversized cluster / セッション数が少ない）}
候補が増える条件: {いつ再実行すると候補が出やすいか（例: 同じ workspace で 2-3 週間使い続けると反復パターンが明確化しやすい）}
```

## Deep Research Rules

`needs_research` 候補だけ追加調査してよい。

- 1 candidate あたり最大 5 refs
- 追加調査は 1 回まで
- `research_targets` と `research_brief` を優先して使う
- 追加調査しても粒度が粗い場合は `観測ノート` に落とす

追加調査後:

- `promote_ready`
  - `提案（固定化を推奨）` へ移す
- `split_candidate`
  - `有望候補` に残し、必要なら分割軸を書く
- `reject_candidate`
  - `観測ノート` に移す

## CLAUDE.md Immediate Apply Spec

`CLAUDE.md` 分類だけは low-risk immediate apply path を仕様として持つ。
この skill ではコード実装を前提にしないが、次の contract を守る。

1. 対象は `cwd/CLAUDE.md` だけ
2. `cwd/CLAUDE.md` が無い場合は、新規作成として diff preview を作る
3. 追記先は `## DayTrace Suggested Rules` セクション末尾
4. セクションが無ければ新規作成する
5. 既存文言の書き換えや並び替えはしない
6. 重複候補は skip して理由を返す
7. 衝突候補は diff preview だけ出して終了する
8. `skill` / `hook` / `agent` は immediate apply しない

diff preview 例:

```diff
--- /dev/null
+++ cwd/CLAUDE.md
@@
+## DayTrace Suggested Rules
+
+- Use pytest for verification.
```

## Detail / Draft Rules

- `提案（固定化を推奨）` に候補がある場合だけ、次セッションで 1 件選んでもらう
- 選択候補の `session_refs` だけを `skill_miner_detail.py --refs ...` で取得する
- `CLAUDE.md` 以外は次セッションへ送る
- detail phase でも raw history 全量には戻らない

## Completion Check

- `prepare` は 1 回だけ実行している
- 期間 contract は `7 日開始 + workspace-only adaptive 30 日` / `--all-sessions` に固定されている
- 4 分類以外の古い説明が残っていない
- proposal phase の根拠が `evidence_items[]` だけで表示できる
- `0 件` を正常系として扱い、返却上限は `prepare` の `top_n` と一致している
