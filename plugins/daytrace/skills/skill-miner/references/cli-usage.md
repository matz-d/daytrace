# CLI 詳細仕様 & Prepare Output Reading Guide

## CLI コマンド詳細

スクリプトは plugin 直下の `scripts/` ディレクトリにある。
`SKILL.md` のあるディレクトリから `../..` を辿った先を `<plugin-root>` として扱う。

### skill_miner_prepare.py

提案フェーズ用。全セッションを圧縮 candidate view で横断分析する。

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py
```

広域観測:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --all-sessions
```

補足:

- デフォルト観測窓は `--days 7`
- `--all-sessions` は workspace 制限を外すだけで、日数窓は維持する
- `workspace` モードだけ、packet / candidate が少なすぎる場合に 30 日へ自動拡張する
- B0 のように full-history 相当を見たい場合は、十分長い `--days` を明示する

例:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --all-sessions --days 3650 --dump-intents
```

### skill_miner_detail.py

選択後の detail 再取得。

```bash
python3 <plugin-root>/scripts/skill_miner_detail.py --refs "<session_ref_1>" "<session_ref_2>"
```

### skill_miner_research_judge.py

追加調査後の結論判定。

```bash
python3 <plugin-root>/scripts/skill_miner_research_judge.py --candidate-file /tmp/prepare.json --candidate-id "<candidate_id>" --detail-file /tmp/detail.json
```

### skill_miner_proposal.py

最終 proposal 組み立て。

```bash
python3 <plugin-root>/scripts/skill_miner_proposal.py --prepare-file /tmp/prepare.json --judge-file /tmp/judge.json
```

### 実コマンド例

repo root をカレントディレクトリとした場合:

```bash
python3 plugins/daytrace/scripts/skill_miner_prepare.py
python3 plugins/daytrace/scripts/skill_miner_prepare.py --all-sessions
python3 plugins/daytrace/scripts/skill_miner_prepare.py --all-sessions --days 3650 --dump-intents
python3 plugins/daytrace/scripts/skill_miner_detail.py --refs "codex:abc123:1710000000"
python3 plugins/daytrace/scripts/skill_miner_research_judge.py --candidate-file /tmp/prepare.json --candidate-id "codex-abc123" --detail-file /tmp/detail.json
python3 plugins/daytrace/scripts/skill_miner_proposal.py --prepare-file /tmp/prepare.json --judge-file /tmp/judge.json
```

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
- `summary.adaptive_window_expanded`
  - workspace モードで 30 日 fallback が発火したか
- `config.effective_days`
  - 実際に使われた観測窓
- `config.adaptive_window`
  - しきい値、初期 packet / candidate 数、拡張理由
- `skill_miner_proposal.py` の出力
  - triage 済み candidate を人間向け proposal section に整形したもの

注意:

- `representative_examples` と `primary_intent` は圧縮済み
- path は `[WORKSPACE]` にマスクされる
- URL はドメインのみ残る
