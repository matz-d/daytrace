---
name: skill-miner
description: >
  Claude / Codex 履歴から反復パターンを抽出し、
  `CLAUDE.md` / `skill` / `hook` / `agent` のどれに固定すべきかを評価し、
  proposal を返す。
user-invocable: true
---

# Skill Miner

AI 会話履歴を横断して、固定化すべき作法を `extract / classify / evaluate / propose` するための skill。

## Goal

- Claude / Codex 履歴から反復パターンを抽出する
- 候補を `CLAUDE.md` / `skill` / `hook` / `agent` の 4 分類で判定する
- `提案成立 / 追加調査待ち / 今回は見送り` の main UX で返す
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
python3 <plugin-root>/scripts/skill_miner_prepare.py --days 7
```

全履歴を明示的に見る場合のみ:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --all-sessions
```

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
2. デフォルトは `--days 7`。`--all-sessions` を明示した時だけ日付制限を外す
3. `candidates` と `unclustered` を `ready` / `needs_research` / `rejected` に分ける
4. 正式提案は `proposal_ready=true` の候補だけを採用し、件数は **0-5 件** を正常系として扱う
5. `needs_research` 候補だけ、必要な場合に限って `research_targets` を使って 1 回だけ追加調査する
6. `skill_miner_research_judge.py` の結論を proposal に反映し、`提案成立 / 追加調査待ち / 今回は見送り` を返す
7. `提案成立` がある時だけ、次セッションでどれを apply するかを確認する
8. state file は持たない。実行モードは CLI 引数だけで決める

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
  - デフォルト期間。通常は `7`
- `config.all_sessions`
  - `true` の時だけ日付制限を無効化する
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
B0 の観測方法と優先順位ルールは `references/b0-observation.md` を参照する。

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

- 正式提案は **0-5 件** を正常系とする
- `0 件` でも失敗扱いにせず、理由と次回への示唆を返す
- `needs_research` 候補は必要な場合だけ detail を取る

## Proposal Format

proposal は次の 3 区分で返す。

```markdown
## 提案成立

1. 候補名
   分類: skill
   confidence: medium
   根拠:
   - 2026-03-08T10:00:00+09:00 claude-history: findings-first review を要求
   - 2026-03-10T09:00:00+09:00 codex-history: 同系の review 指示を再確認
   期待効果: 同種作業の再利用フローを安定化できる

## 追加調査待ち

1. 候補名
   confidence: weak
   根拠:
   - 2026-03-08T10:00:00+09:00 claude-history: 汎用 review 指示
   保留理由: 巨大クラスタで意味の異なる作業が混ざる可能性がある

## 今回は見送り

1. 候補名または項目種別
   理由: 単発または一般化の根拠不足
```

ルール:

- `提案成立 / 追加調査待ち / 今回は見送り` を main UX にする
- `提案成立` だけを重要度順に並べる
- `追加調査待ち` には `保留理由` を必ず書く
- `今回は見送り` には 1 文で理由を書く

## Deep Research Rules

`needs_research` 候補だけ追加調査してよい。

- 1 candidate あたり最大 5 refs
- 追加調査は 1 回まで
- `research_targets` と `research_brief` を優先して使う
- 追加調査しても粒度が粗い場合は `今回は見送り` に落とす

追加調査後:

- `promote_ready`
  - `提案成立` へ移す
- `split_candidate`
  - `追加調査待ち` に残し、必要なら分割軸を書く
- `reject_candidate`
  - `今回は見送り` に移す

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

- `提案成立` に候補がある場合だけ、次セッションで 1 件選んでもらう
- 選択候補の `session_refs` だけを `skill_miner_detail.py --refs ...` で取得する
- `CLAUDE.md` 以外は次セッションへ送る
- detail phase でも raw history 全量には戻らない

## Completion Check

- `prepare` は 1 回だけ実行している
- 期間 contract は `--days 7` / `--all-sessions` に固定されている
- 4 分類以外の古い説明が残っていない
- proposal phase の根拠が `evidence_items[]` だけで表示できる
- `0-5 件` を正常系として扱っている
