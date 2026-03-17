# Skill Miner Current State

このドキュメントは、`skill-miner` が現時点で何をできて、何がまだ弱いかを正直に共有するためのもの。
期待値調整、実装判断、外部説明のブレを減らすことを目的とする。

## 1. `skill-miner` の役割

- Claude / Codex の会話履歴を横断して反復パターンを抽出する
- パターンを `CLAUDE.md` / `skill` / `hook` / `agent` の 4 分類で評価する
- `提案成立 / 追加調査待ち / 今回は見送り` の 3 区分で proposal を返す
- `CLAUDE.md` 分類の候補だけ、`cwd/CLAUDE.md` への diff preview という immediate apply path を持つ

`aggregate.py` は使わず、skill-miner 専用 CLI だけを使う。

## 2. 現在できること

### 2-1. 抽出（`skill_miner_prepare.py`）

- Claude / Codex の生 JSONL を直接読み込み、logical session に分割する
  - Claude: 時間 gap と `isSidechain` フラグで session 境界を検出する
- セッションを **packet** 単位に圧縮し、`task_shape`, `tool_signature`, `artifact_hints`, `repeated_rules` を特徴量として抽出する
- packet を類似度ベースで **cluster** 化し、ranked `candidates` を生成する
- 各 candidate に `session_refs`（後続フェーズで使う安定参照）を発行する
- 観測窓: デフォルト 7 日。`--all-sessions` で workspace 制限解除（7 日窓は維持）
- workspace モード限定で、packet / candidate が少なすぎる場合だけ 30 日へ **adaptive 拡張**する
- `--dump-intents` 指定時だけ `intent_analysis`（B0 観測用）を出力する

### 2-2. 提案（`skill_miner_proposal.py`）

各 candidate に以下の属性が付き、proposal phase で使われる:

- `confidence`: `strong` / `medium` / `weak` / `insufficient`
- `proposal_ready`: そのままドラフト化できるかどうか（`true` / `false`）
- `triage_status`: `ready` / `needs_research` / `rejected`
- `quality_flags`: 候補の強さ・弱さの理由を示すフラグ群
- `evidence_summary`: 出現回数・source 多様性・直近性のサマリ
- `evidence_items`: 最大 3 件の proposal 用根拠チェーン（`session_ref`, `timestamp`, `source`, `summary`）
- `research_targets`: `needs_research` 候補に最大 5 件の detail 取得推奨 ref
- `research_brief`: 追加調査で見るべき観点と判断ルール

`proposal_ready=true` の候補だけを正式提案に採用し、返却上限は `prepare` 側の `top_n`（デフォルト 10）に従う。
**0 件でも正常系として扱い**、理由と次回への示唆を返す。

proposal phase は raw history を再読み込みしない。`evidence_items[]` だけで根拠表示を完結させる。

### 2-2a. current triage / scoring semantics（`skill_miner_common.py`）

`confidence` と `triage_status` は LLM の自由判断ではなく、prepare phase の shared heuristic で先に決まる。

主要しきい値:

- oversized cluster: `total_packets >= 8` かつ全 packet に対する share が `>= 0.5`
- generic tools: 先頭 4 tool signature のうち 3 つ以上が `bash`, `cat`, `ls`, `nl`, `read`, `rg`, `sed`
- generic task shape: 先頭 task shape が `review_changes`, `search_code`, `summarize_findings`, `inspect_files` のような汎用ラベルに偏る状態
- weak semantic cohesion: 代表 example 2 件の token Jaccard が `< 0.2`
- single session like: `total_packets <= 1`

score の current ルール:

- 加点: packet 数が 2 以上 / Claude と Codex の両方に出現 / recent 7d が 2 以上 / repeated rule がある / 非汎用 task shape がある
- 減点: oversized cluster / generic task shape / generic tools / weak semantic cohesion / single session like

判定結果:

- `confidence`: `strong` / `medium` / `weak` / `insufficient`
- `proposal_ready`: `strong` または `medium` で、oversized cluster・weak semantic cohesion・generic cluster・single session like に当てはまらない時だけ `true`
- `triage_status`:
  - `ready`: `proposal_ready=true`
  - `needs_research`: oversized cluster / weak semantic cohesion / generic cluster
  - `rejected`: single-session-like または `confidence=insufficient`、その他の一般化困難候補

このため proposal の質は、最終 markdown wording よりも **candidate clustering と quality heuristic** に強く依存する。
「LLM が気の利いた説明を書けば提案品質が上がる」構造ではない。

### 2-3. 追加調査（`skill_miner_detail.py` + `skill_miner_research_judge.py`）

`needs_research` 候補に限り:

- `skill_miner_detail.py --refs <ref1> <ref2>`: `session_ref` から `messages`（会話ログ）と `tool_calls` を再取得する
- `skill_miner_research_judge.py --candidate-file ... --detail-file ...`: 追加調査後の structured conclusion を出す

`judgment` フィールドの `recommendation`:
- `promote_ready`: `提案成立` へ昇格
- `split_candidate`: `追加調査待ち` に残し、分割軸を提示
- `reject_candidate`: `今回は見送り` へ

追加調査は 1 候補あたり最大 5 refs、1 回まで。

### 2-4. immediate apply（`CLAUDE.md` 分類のみ）

`CLAUDE.md` 分類の `ready` 候補だけ、以下の仕様で diff preview を返す:

1. 対象は `cwd/CLAUDE.md` のみ
2. 追記先は `## DayTrace Suggested Rules` セクション末尾（セクションが無ければ新規作成）
3. 既存文言の書き換え・並び替えはしない
4. 重複候補は skip して理由を返す
5. 衝突候補は diff preview のみ出して終了

`skill` / `hook` / `agent` 分類の候補は次セッションの apply フローへ送る。

### 2-5. store との連携

`--input-source auto` を使うと:
- store の該当 slice が **complete** かつ現行マニフェストと一致 → store から `observations` を使って packet を再構成
- それ以外 → raw history へフォールバック

`--store-path` を付けると候補を `patterns` テーブルへ保存し、`post_draft_projection.py` が cached patterns として参照できるようになる。

## 3. 現在できないこと

- `skill` / `hook` / `agent` の自動生成（提案止まり）
- `SKILL.md` の自動修正
- self-improving loop の本実装（skill run 観測 → amend → 採用率評価）
- 実運用での採用率評価
- `plugin` 分類（v2 では一次分類に使わない）

## 4. 現在の主要な弱点

### 4-1. oversized cluster

全 packet の大多数が 1 クラスタに集約される事象が起きやすい。
原因は `review_changes` / `search_code` / `bash` / `rg` のような汎用 task shape と tool signature に多くのセッションが乗るため。

実際の観測（2026-03-11, full-history）では 112 packets 中 56 packets 規模の oversized cluster が確認されており、
その中に「コードレビュー」「調査タスク」「ログ整理」「ドキュメント確認」など別目的の作業が混在していた。

### 4-2. `proposal_ready 0 件`

oversized cluster は `quality_flags` に `weak_semantic_cohesion` / `generic_tools` が立ち、`proposal_ready=false` になりやすい。
その結果、一見候補数は多く見えても正式提案に昇格できる件数が 0 になる場合がある。

この状態でも失敗ではなく正常系だが、UX としては「候補らしきものが出たが提案できなかった」という体験になる。

### 4-3. `suggested_kind` の安定化不足

4 分類（`CLAUDE.md` / `skill` / `hook` / `agent`）への割り当てが、候補の強さを吟味する前に「分類を埋める」方向に働く場合がある。
本来は `提案不成立 / 追加調査待ち` が適切なケースでも、いずれかの分類に押し込むリスクがある。

### 4-4. concretization 不足

代表スニペットが短いため、異なる目的の作業が同じ block に乗りやすく、「具体的に何を自動化すべきか」を 1 本に定義しにくい。
clustering / similarity 側の改善（block key / similarity rebalance, split-first 表示）が優先課題として認識されている。

## 5. 期待値として正しい説明

### 何を「できる」と言ってよいか

- Claude / Codex 会話履歴から反復パターンを自動抽出し、`提案成立 / 追加調査待ち / 今回は見送り` の 3 区分で返すことができる
- `提案成立` がある時は、根拠チェーン（どのセッションで何を繰り返したか）付きで提案内容を説明できる
- `CLAUDE.md` 候補だけ、diff preview による immediate apply path を持つ
- 0 件でも正常系として動作し、理由を返す

### 何は「提案止まり」か

- `skill` / `hook` / `agent` の実際の生成・インストールは次セッションへ送る
- 提案内容が正しいかどうかの最終判断はユーザーが行う

### 何をハッカソン後に回すべきか

- clustering 精度改善（split-aware candidate reconstruction、similarity rebalance）
- classification 安定化（分類前の `提案不成立` 判定の強化）
- `skill_run` 観測（skill を使った履歴を学習データにするループ）
- amend / evaluate loop（採用 → フィードバック → 改善）

## 6. 出力の読み方

### 6-1. `prepare` 出力（`skill_miner_prepare.py`）

```json
{
  "status": "success",
  "source": "skill-miner-prepare",
  "candidates": [...],
  "unclustered": [...],
  "sources": [...],
  "summary": {...},
  "config": {...}
}
```

**主な読みどころ**:

- `config.days`: 初期観測窓（通常 7）
- `config.effective_days`: 実際に使われた観測窓（adaptive window で 30 になる場合あり）
- `config.all_sessions`: workspace 制限解除フラグ
- `config.adaptive_window`: workspace モードの自動拡張メタデータ
- `summary.adaptive_window_expanded`: adaptive window が発火したかどうか
- `candidates[].support`: 出現回数・source 多様性・直近性
- `candidates[].confidence`, `proposal_ready`, `triage_status`: 候補の強さと triage 結果
- `candidates[].evidence_items`: proposal 用の根拠チェーン（最大 3 件）
- `candidates[].research_targets`: `needs_research` 候補で優先して detail を取る ref
- `candidates[].quality_flags`: 候補が強い / 弱い理由
- `unclustered[]`: クラスタを形成できなかった単発 packet

### 6-2. `detail` 出力（`skill_miner_detail.py`）

```json
{
  "status": "success",
  "source": "skill-miner-detail",
  "details": [
    {
      "session_ref": "claude:/path/to/file.jsonl:1710000000",
      "messages": [...],
      "tool_calls": [...]
    }
  ],
  "errors": []
}
```

- `messages`: 純粋な user / assistant 会話ログ
- `tool_calls`: 使われたコマンドやツールの集計

### 6-3. `judge` 出力（`skill_miner_research_judge.py`）

```json
{
  "status": "success",
  "source": "skill-miner-research-judge",
  "candidate_id": "codex-abc123",
  "judgment": {
    "recommendation": "promote_ready | split_candidate | reject_candidate",
    "proposed_triage_status": "ready | needs_research | rejected",
    "reasons": ["..."],
    "split_suggestions": [...]
  }
}
```

### 6-4. `proposal` 出力（`skill_miner_proposal.py`）

```json
{
  "status": "success",
  "source": "skill-miner-proposal",
  "ready": [...],
  "needs_research": [...],
  "rejected": [...],
  "selection_prompt": null,
  "markdown": "## 提案成立\n..."
}
```

- `ready`: 正式提案候補
- `needs_research`: 追加調査後もまだ保留の候補
- `rejected`: 不成立候補と unclustered の参照
- `markdown`: LLM/ユーザー向けの整形済み提案セクション（そのまま出力できる）

**Triage 区分の対応**:

| triage_status | 表示区分 |
|--------------|---------|
| `ready` | `提案成立` |
| `needs_research` | `追加調査待ち` |
| `rejected` | `今回は見送り` |

## 7. ハッカソン前に最低限強化したい方向

- **0 件時 UX**: 「候補なし」の場合も、なぜ候補が出なかったかと次回への示唆を明確に返す
- **split-first 表示**: oversized cluster を検出したときに自動的に分割軸を提示し、`追加調査待ち` に誘導する
- **暫定候補の見せ方**: `proposal_ready=false` だが観測価値のある候補を「参考候補」として見せる UX
- **統合フロー内での役割固定**: `daytrace-session` の Phase 3 における位置づけを安定させる

## 8. ハッカソン後の本命課題

- **split-aware candidate reconstruction**: oversized cluster を下位テーマに分割する機構
- **classification stabilization**: 4 分類の前に「提案不成立」「追加調査待ち」を明確に判定するゲート
- **`skill_run` 観測**: skill を実際に使った履歴を観測データとして取り込む
- **amend / evaluate loop**: 候補の採用 → フィードバック → 改善のサイクル実装

## 9. 関連ドキュメント

- `plugins/daytrace/skills/skill-miner/SKILL.md`: skill の実行仕様・分類ルール・proposal format
- `REPORT-skill-miner-primary-intent.md`: B0 観測結果（full-history での intent 分析と優先課題の特定）
- `REPORT-skill-miner-benchmark.md`: ベンチマーク結果
- `ISSUE-skill-miner-proposal-quality.md`: 提案品質に関する問題提起と対応策
