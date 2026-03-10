# TODO D2b. Skill Miner Proposal Quality / UX Recovery

Phase: Output Skills
Depends on: D2a（`skill-miner` staged compression が入っていること）

## Goal

`skill-miner` の提案品質問題を解消し、「候補を無理に出す」のではなく「根拠が強い候補だけを、理由付きで提案する」体験に変える。

今回の作業は、単なるクラスタ精度改善ではなく、以下の 3 点を同時に満たすことを目的とする。

- Python 側で candidate の品質を機械的に足切りできる
- LLM 側が `0-5件` を自然に扱い、弱い候補を無理に分類しない
- 巨大クラスタや曖昧候補が出た場合に、深掘り調査へ自然に遷移できる

## Problem Summary

現状の問題は主に次の 4 つ。

- 巨大クラスタが 1 本にまとまりすぎる
- `unclustered` が件数合わせの提案候補として扱われやすい
- `3-5件` の期待が強く、弱い候補でも提案しやすい
- 候補が弱い理由を JSON 上で明示できず、LLM が説明責任を負いすぎる

## Desired UX

実装後の提案フェーズでは、ユーザーに次の 3 区分が見えること。

### 1. 提案成立

- `proposal_ready=true`
- そのまま選択してドラフト化できる

### 2. 追加調査待ち

- `proposal_ready=false`
- `triage_status=needs_research`
- 「巨大クラスタ」「汎用ツールに偏る」など、保留理由が分かる

### 3. 今回は見送り

- `triage_status=rejected`
- 単発・一般化不能・根拠不足を理由付きで除外する

## Non Goals

今回の TODO では、以下は必須ではない。

- クラスタリングアルゴリズムの全面刷新
- embedding や外部 API を使った意味検索
- raw history 全量を proposal phase に戻す設計

## Parallel Work Map

```text
Track 0: contract / UX shape 固定
  -> Track 1: Python quality scoring
  -> Track 2: label / summary 改善
  -> Track 3: SKILL.md triage / proposal UX

Track 1 + Track 2
  -> Track 4: deep research flow

Track 1 + Track 3 + Track 4
  -> Track 5: tests / E2E / docs verification
```

## Track 0. Contract / UX Shape Lock

Parallel: 最優先。ここを決めてから実装に入る

### Checklist

- [x] `candidate` JSON に追加する field を確定する
- [x] `confidence` の enum を確定する（`strong` / `medium` / `weak` / `insufficient`）
- [x] `triage_status` の enum を確定する（`ready` / `needs_research` / `rejected`）
- [x] `proposal_ready` の意味を確定する
- [x] `quality_flags` の初期 vocabulary を確定する
- [x] `confidence_reason` または `evidence_summary` の shape を確定する
- [x] proposal phase の最終 UX 区分を SKILL.md に反映する前提で文言を決める

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/scripts/skill_miner_prepare.py`
  - `plugins/daytrace/scripts/skill_miner_common.py`
  - `plugins/daytrace/skills/skill-miner/SKILL.md`
- `quality_flags` の初期候補例:
  - `oversized_cluster`
  - `generic_tools`
  - `generic_task_shape`
  - `weak_semantic_cohesion`
  - `single_session_like`
  - `unclustered_only`
- `proposal_ready` は「そのまま人に提案してよいか」の判定であり、「存在価値があるか」とは分ける

### Done Criteria

- [x] field 名と enum がコード・テスト・SKILL.md で矛盾しない
- [x] 実装者が JSON shape を迷わず追加できる

## Track 1. Python Quality Scoring

Parallel: Track 0 完了後すぐ着手可

### Checklist

- [x] `skill_miner_common.py` に candidate quality 判定関数を追加する
- [x] `support` と cluster metadata から `confidence` を算出する
- [x] `proposal_ready` を算出する
- [x] `triage_status` を算出する
- [x] `quality_flags` を配列で返す
- [x] `confidence_reason` または `evidence_summary` を生成する
- [x] `unclustered` を proposal-ready 扱いしないルールを明文化する

### Required Heuristics

- [x] 巨大クラスタ検知を追加する
- [x] 相対閾値だけでなく絶対閾値も入れる
- [x] 汎用 task shape 偏重を検知する
- [x] 汎用 tool 偏重を検知する
- [x] source diversity / recency が高くても、巨大で粗いクラスタは減点する
- [x] `total_packets=1` 相当の孤立 candidate は `proposal_ready=false` 相当にする

### Suggested Rules

- 巨大クラスタ:
  - `total_packets >= 8`
  - かつ `total_packets / total_packets_all >= 0.5`
- 汎用 task shape 偏重:
  - 上位 task shape が `review_changes`, `search_code`, `summarize_findings`, `inspect_files` だけで占められる
- 汎用 tool 偏重:
  - 上位 tool が `rg`, `sed`, `bash`, `read`, `nl`, `ls`, `cat` に寄る
- `proposal_ready=false` 条件:
  - `confidence in {"weak", "insufficient"}`
  - または `quality_flags` に `oversized_cluster` を含む
- `triage_status` の初期ルール:
  - `ready`: `proposal_ready=true`
  - `needs_research`: 候補としてはあるが、そのまま提案は危険
  - `rejected`: 単発または一般化困難

### Implementation Notes

- `candidate_score()` は ranking のために残してよいが、proposal 可否は別ロジックに分ける
- quality 判定ロジックは `cluster_packets()` の中に直接埋めず、共通関数へ寄せる
- `total_packets_all` など cluster 相対判定に必要な値を quality 判定関数へ渡す

### Done Criteria

- [x] candidate JSON に quality 系 field が追加される
- [x] 巨大クラスタが `proposal_ready=false` になる
- [x] 汎用開発クラスタが `strong` になりにくい

## Track 2. Candidate Label / Summary Repair

Parallel: Track 1 と並行可

### Checklist

- [x] 先頭 packet の `primary_intent` 依存ラベルをやめる
- [x] cluster 全体の頻出 signal から label を生成する
- [x] `representative_examples` の選び方が巨大クラスタで偏りすぎないよう見直す
- [x] cluster 全体を説明する `evidence_summary` を作る

### Labeling Rules

- [x] 第一候補: `common_task_shapes[0]`
- [x] 第二候補: `artifact_hints` 上位 1-2 件
- [x] 必要なら `rule_hints` の代表要素を suffix に付ける
- [x] 例: `review_changes (code, report)`
- [x] 巨大クラスタで代表性が低い文言は label に使わない

### Implementation Notes

- 対象関数:
  - `candidate_label()`
  - `cluster_packets()` 内の `representative_examples` 組み立て
- `representative_examples` は「頻出例だけ」でなく「異質例が混ざると分かる例」を 1 件含める余地を検討する
- `near_matches` は deep research の入力に使えるので維持する

### Done Criteria

- [x] 巨大クラスタでもラベルが単発セッション名にならない
- [x] ユーザーがラベルだけ見ても候補の種類を誤解しにくい

## Track 3. SKILL.md Triage / Proposal UX Rewrite

Parallel: Track 0 完了後着手可

### Checklist

- [x] `3-5件を目標` という記述を削除する
- [x] `0-5件を許容` に書き換える
- [x] `proposal_ready=true` または `confidence` が十分高い候補だけ提案するルールを追記する
- [x] `unclustered` は原則提案に含めないと明記する
- [x] `triage` フェーズを `prepare` と `proposal` の間に追加する
- [x] 「今回は有力候補なし」を正常系として定義する
- [x] `追加調査待ち` の説明フォーマットを追加する
- [x] `見送り` の説明フォーマットを追加する

### Required Output Format

- [x] `## 提案成立`
- [x] `## 追加調査待ち`
- [x] `## 今回は見送り`
- [x] 各候補に `confidence`, `根拠`, `保留理由または見送り理由`, `期待効果` を含める

### UX Rules

- [x] 候補が 0 件でも失敗扱いしない
- [x] 追加調査待ちしかない場合は、その理由を先に伝える
- [x] どの候補も弱いのに 5 分類へ無理に押し込まない
- [x] 分類不能時は `追加調査待ち` に残す
- [x] ユーザーが「なぜ今は提案されないのか」を 1 文で理解できるようにする

### Done Criteria

- [x] SKILL.md 単体で「候補ゼロ」「候補保留」「候補成立」を扱える
- [x] 提案数不足が UX 上の失敗に見えない

## Track 4. Deep Research Flow For Oversized / Ambiguous Clusters

Parallel: Track 1 と Track 2 完了後に着手

### Checklist

- [x] `needs_research` 候補に対する追加調査フローを SKILL.md に追加する
- [x] `session_refs` の抽出方針を決める
- [x] `skill_miner_detail.py --refs ...` を小さく呼ぶルールを定義する
- [x] 分析結果を親エージェントへ戻す観点を定義する
- [x] 再分類または見送り判断の条件を定義する
- [x] 深掘りの回数上限を定義する

### Sampling Rules

- [x] ランダム抽出ではなく代表抽出を採用する
- [x] 少なくとも以下を混ぜる:
  - 代表例に近い ref
  - `near_matches` に近い ref
  - 異質そうな ref
- [x] 1 candidate あたり detail 取得は最大 5 refs に制限する
- [x] 追加調査は 1 回までとする

### Analysis Prompt Requirements

- [x] 「本当に 1 つの automation candidate か」を判定させる
- [x] 「複数の別作業が混ざっているか」を判定させる
- [x] 「分割するならどの軸か」を書かせる
- [x] 「今回は見送りにすべきか」を書かせる

### Fallback Rules

- [x] サブエージェントが使えない環境では、親エージェントの second-pass 分析にフォールバックする
- [x] それでも判断不能なら `今回は見送り` に落とす

### Done Criteria

- [x] 巨大クラスタがそのまま提案に出ず、追加調査に回る
- [x] 追加調査後に「再提案」か「見送り」かを明示できる

## Track 5. Tests / Regression Fixtures / E2E

Parallel: 各トラックの成果が揃い次第

### Checklist

- [x] quality scoring 用 fixture を追加する
- [x] 巨大クラスタ検知テストを追加する
- [x] generic tools / generic task shape 減点テストを追加する
- [x] `proposal_ready=false` の contract テストを追加する
- [x] `triage_status` の contract テストを追加する
- [x] label 改善の回帰テストを追加する
- [x] `unclustered` が ready 候補として扱われないテストを追加する
- [x] SKILL.md 想定の E2E 手順を実データで確認する

### Required Test Cases

- [x] 75 packets 中 63 packets が 1 cluster に寄るケースを fixture 化する
- [x] review / search / summarize が混ざる generic cluster を fixture 化する
- [x] 単発で面白いが一般化不能な `unclustered` ケースを fixture 化する
- [x] 強い反復候補が 1 件しかないケースで `1件だけ提案` になることを確認する
- [x] 強い候補が 0 件のケースで `今回は有力候補なし` になる前提を確認する

### Verification Notes

- [x] `python3 -m unittest plugins.daytrace.scripts.tests.test_skill_miner` が通る
- [x] 実データで `skill_miner_prepare.py --all-sessions` を再実行し、巨大クラスタが `needs_research` になる
- [x] 実データで proposal list が `提案成立` / `追加調査待ち` / `見送り` に自然分離される

### Done Criteria

- [x] proposal quality の劣化をテストで検知できる
- [x] issue に書かれた症状を fixture で再現できる

## Recommended Execution Order

1. Track 0 で `candidate` quality contract を固定する
2. Track 1 で Python 側 quality 判定を実装する
3. Track 2 で label / evidence summary を修正する
4. Track 5 の unit test を先に追加し、quality regression を固定する
5. Track 3 で SKILL.md を triage 前提の UX に書き換える
6. Track 4 で deep research flow を追加する
7. 実データで E2E を回し、巨大クラスタが提案ではなく保留に回ることを確認する

## Final Done Criteria

- [x] `skill_miner_prepare.py` が candidate ごとに `confidence`, `proposal_ready`, `triage_status`, `quality_flags` を返す
- [x] `skill-miner` が `0-5件` の提案数を自然に扱える
- [x] 巨大クラスタが `提案成立` ではなく `追加調査待ち` になる
- [x] `unclustered` が件数合わせで proposal に混ざらない
- [x] ユーザーが「なぜ提案されたか / 保留か / 見送りか」を理解できる
