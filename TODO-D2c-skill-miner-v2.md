# TODO D2c. Skill Miner v2 Realignment / Weekly Classification

Phase: Output Skills
Depends on: D2b（`skill-miner` staged compression + proposal quality が入っていること）

## Goal

`PLAN_skill-miner.md` の v2 方針を、何も知らない実装者でも迷わず着手できる実装 TODO に落とし込む。

今回の作業で揃えるものは次の 5 点。

- `skill-miner` を `extract / classify / evaluate / propose` 専用 skill として再定義する
- 実行モードを `--days 7` デフォルト + `--all-sessions` 明示指定の 2 モードに固定する
- `evidence_items[]` を prepare contract に追加し、evidence chain を raw history 再読込なしで出せるようにする
- `CLAUDE.md` の low-risk immediate apply path を安全側の制約つきで実装する
- B0 観測、特徴量改善、クラスタ改善、quality gate 改善、定量比較までを 1 セットで回せるようにする

## Non Goals

今回の TODO では、以下は対象外。

- `daily-report` / `post-draft` の更新
- `skill-miner` 自身による `skill` / `hook` / `agent` の自動生成
- plugin 分類の復活
- state file の導入
- embedding / 外部 API / ネットワーク依存の意味検索

## Parallel Work Map

```text
Track 0: contract lock
  -> Track 1: product / docs rewrite
  -> Track 2: prepare / proposal contract
  -> Track 3: B0 instrumentation

Track 2 + Track 3
  -> Track 4: feature extraction
  -> Track 5: clustering / similarity
  -> Track 6: research judge / quality gate

Track 1 + Track 2
  -> Track 7: CLAUDE.md immediate apply path

Track 1 + Track 4 + Track 5 + Track 6 + Track 7
  -> Track 8: tests / benchmark / E2E
```

補足:

- Track 4-6 は stub 実装までは並列で進めてよい
- ただし最終的な優先順位と閾値調整は Track 3 の観測結果を見て決める

## Track 0. Contract Lock

Parallel: 最優先。ここを固定してから各トラックへ分岐する

### Checklist

- [ ] `skill-miner` の分類先を 4 分類に固定する
  - `CLAUDE.md`
  - `skill`
  - `hook`
  - `agent`
- [ ] `plugin` 分類を v2 では使わないことを contract に明記する
- [ ] デフォルト実行モードを `--days 7` に固定する
- [ ] `--all-sessions` は明示指定時のみ使うことを contract に明記する
- [ ] state file を持たないことを contract に明記する
- [ ] `candidates[].evidence_items[]` の JSON schema を確定する
- [ ] `CLAUDE.md` 即適用の対象ファイル、挿入位置、重複・衝突時の挙動を確定する
- [ ] 定量比較の 3 指標を定義し、用語を固定する
  - `oversized_cluster` 発生率
  - `proposal_ready` 件数
  - `0件` 率

### Implementation Notes

- 対象ファイル:
  - `PLAN_skill-miner.md`
  - `plugins/daytrace/skills/skill-miner/SKILL.md`
  - `plugins/daytrace/scripts/README.md`
- `evidence_items[]` の shape:

```json
{
  "session_ref": "codex:abc123:1710000000",
  "timestamp": "2026-03-10T09:00:00+09:00",
  "source": "codex",
  "summary": "SKILL.md の構造確認を行い、提案理由を整理"
}
```

### Done Criteria

- [ ] 実装者間で mode / class / candidate schema の解釈差がない
- [ ] `SKILL.md`, `scripts/README.md`, tests の前提が一致している

## Track 1. Product / Docs Rewrite

Parallel: Track 0 完了後すぐ着手可

### Checklist

- [ ] `plugins/daytrace/skills/skill-miner/SKILL.md` の Goal を `extract / classify / evaluate / propose` に書き換える
- [ ] 「提案 → 選択 → 全分類ドラフト生成」の旧ストーリーを外す
- [ ] `0-5件` を正常系として明記する
- [ ] `提案成立 / 追加調査待ち / 今回は見送り` の 3 区分を main UX として明記する
- [ ] `plugin` 分類の記述を削除する
- [ ] `references/classification.md` を新規作成する
- [ ] `classification.md` に 4 分類の境界ケースを入れる
  - 同じ作法を repo ルールにするなら `CLAUDE.md`
  - 明確な入出力と手順があるなら `skill`
  - 判断不要の機械処理なら `hook`
  - 継続的な役割や行動原則なら `agent`
- [ ] `plugins/daytrace/scripts/README.md` の `skill-miner` contract を v2 に合わせて更新する
- [ ] `prepare` は raw history を読み、`proposal` は raw history を再読込しないことを README に明記する

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/skills/skill-miner/SKILL.md`
  - `plugins/daytrace/skills/skill-miner/references/classification.md`
  - `plugins/daytrace/scripts/README.md`
- `SKILL.md` では「`CLAUDE.md` 以外は次セッションへ送る」を強く明記する

### Done Criteria

- [ ] `skill-miner` の説明が `分類エージェント` として一貫する
- [ ] 4 分類以外の古い説明が残っていない
- [ ] 実装者が `classification.md` だけ見て境界判断を再現できる

## Track 2. Prepare / Proposal Contract Update

Parallel: Track 0 完了後すぐ着手可

### Checklist

- [ ] `skill_miner_prepare.py` に `--days` 引数を追加する
- [ ] `--days` のデフォルト値を `7` にする
- [ ] `--all-sessions` 指定時だけ日付制限を無効化する
- [ ] `skill_miner_prepare.py` の candidate に `evidence_items[]` を追加する
- [ ] `evidence_items[]` は各 candidate 最大 3 件に制限する
- [ ] 各 `evidence_item` に `session_ref`, `timestamp`, `source`, `summary` を埋める
- [ ] `summary` は `primary_intent` 優先、空なら `representative_snippets` から生成する
- [ ] `evidence_items[]` は packet から直接組み立て、raw history 再読込をしない
- [ ] `skill_miner_proposal.py` と `build_proposal_sections()` を更新し、evidence chain を `evidence_items[]` から描画する
- [ ] `skill_miner_research_judge.py` の merge 後も `evidence_items[]` が失われないことを保証する
- [ ] `plugins/daytrace/scripts/README.md` の prepare schema 例を更新する

### Selection Rules

- [ ] 代表 packet を 2-3 件選ぶ
- [ ] 可能なら複数 source / 複数 session にまたがる組み合わせを優先する
- [ ] 同一 candidate 内で summary が重複しすぎる packet は避ける
- [ ] 並び順は「代表性が高いもの → 補強になるもの → 異質だが同一候補を支えるもの」とする

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/scripts/skill_miner_prepare.py`
  - `plugins/daytrace/scripts/skill_miner_common.py`
  - `plugins/daytrace/scripts/skill_miner_proposal.py`
  - `plugins/daytrace/scripts/skill_miner_research_judge.py`
  - `plugins/daytrace/scripts/README.md`

### Done Criteria

- [ ] proposal phase が evidence chain のために raw history を再読込しない
- [ ] candidate JSON だけで timestamp + source + summary つきの根拠表示ができる
- [ ] `--days 7` がデフォルトで効き、`--all-sessions` だけが例外になる

## Track 3. B0 Instrumentation / Real Data Observation

Parallel: Track 0 完了後に着手可

### Checklist

- [ ] `skill_miner_prepare.py` に `--dump-intents` フラグを追加する
- [ ] `--dump-intents` 指定時、通常 payload に加えて `intent_analysis` を返せるようにする
- [ ] `intent_analysis.summary` に次の 3 指標を含める
  - `generic_rate`
  - `synonym_split_rate`
  - `specificity_distribution`
- [ ] `intent_analysis.items` に匿名化済み `primary_intent` サンプルを含める
- [ ] path / URL mask は既存ロジックをそのまま使う
- [ ] 実データで 1 回観測を実行し、結果を Markdown レポートに残す
- [ ] レポートに「B/C/D のどれを最優先にするか」の判定を書く
- [ ] 匿名化した代表 packet を fixture 用に 5-10 件保存する

### Deliverables

- [ ] `plugins/daytrace/scripts/skill_miner_prepare.py` の `--dump-intents`
- [ ] `REPORT-skill-miner-primary-intent.md`
- [ ] `plugins/daytrace/scripts/tests/fixtures/skill_miner_gold.json` または同等の fixture 更新

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/scripts/skill_miner_prepare.py`
  - `plugins/daytrace/scripts/skill_miner_common.py`
  - `plugins/daytrace/scripts/tests/fixtures/skill_miner_gold.json`
  - `REPORT-skill-miner-primary-intent.md`
- B0 は観測タスク。ここでは最適化しすぎない
- まず「何が壊れているか」を定量化し、その結果で Track 4-6 の優先度を決める

### Done Criteria

- [ ] 実データ観測の結果が repo 内で共有できる
- [ ] 3 指標と代表 fixture が揃っている
- [ ] Track 4-6 の優先順位が明文化されている

## Track 4. Feature Extraction Improvements

Parallel: Track 2 の schema 固定後、Track 3 の観測結果を見て着手

### Checklist

- [ ] `TASK_SHAPE_PATTERNS` の順序を見直す
- [ ] generic shape を後ろへ回す
  - `review_changes`
  - `summarize_findings`
  - `search_code`
  - `inspect_files`
- [ ] 具体的 shape を先に拾うようにする
  - `prepare_report`
  - `write_markdown`
  - `debug_failure`
  - `implement_feature`
  - `edit_config`
  - `run_tests`
- [ ] shape 打ち切りロジックを見直し、generic だけで 3 件埋まらないようにする
- [ ] `artifact_hints` の抽出精度を上げる
- [ ] `repeated_rules` の抽出精度を上げる
- [ ] B0 の結果が必要なら intent 正規化レイヤーを追加する
- [ ] B0 の結果が必要なら synonyms map を追加する

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/scripts/skill_miner_common.py`
- generic / specific の語彙は test で固定する
- B0 で intent 側が壊れていない場合、正規化は最小限に留める

### Done Criteria

- [ ] generic-only な packet が減る
- [ ] `primary_intent` と `task_shape` の矛盾が減る
- [ ] 実装者が pattern 順序の意図を tests から読める

## Track 5. Clustering / Similarity Rebalance

Parallel: Track 2 の schema 固定後、Track 3 の観測結果を見て着手

### Checklist

- [ ] `stable_block_keys()` に複合キーを追加する
  - `task + artifact`
  - `task + repeated_rule`
  - `artifact + repeated_rule`
- [ ] `tool` だけで巨大 block に入る確率を下げる
- [ ] `similarity_score()` の重みを v2 目標値へ寄せる
  - `task_shapes`: `0.30`
  - `rules`: `0.20`
  - `snippet / intent`: `0.25`
  - `artifacts`: `0.20`
  - `tools`: `0.05`
- [ ] `snippet / intent` の重みを上げ、目的一致を反映しやすくする
- [ ] giant cluster を生みやすい入口条件を A/B 比較できるようにする
- [ ] `near_matches` が research 用サンプルとして使えることを維持する

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/scripts/skill_miner_common.py`
  - `plugins/daytrace/scripts/skill_miner_prepare.py`
- Track 3 で `shape` より `intent` が壊れていると分かった場合は、Track 4 を優先してから重みを詰める

### Done Criteria

- [ ] `tool:rg` 起点の giant cluster が減る
- [ ] 異なる目的作業の誤結合が減る
- [ ] 同一 dataset で `proposal_ready` 件数または `0件` 率が改善する

## Track 6. Research Judge / Quality Gate Rebalance

Parallel: Track 2 固定後に stub 着手可。最終調整は Track 3-5 後

### Checklist

- [ ] `oversized_cluster` の第一対応を `split` 優先に変更する
- [ ] `judge_research_candidate()` に split-first path を追加する
- [ ] split 判定基準を実装する
  - `2 つ以上の non-generic primary_shape`
  - shape 間 overlap が低い
  - split 後 sub-cluster は最小 2 packets
- [ ] sub-cluster ごとに再 triage する流れを追加する
- [ ] promote 条件を「shape 数」だけでなく intent / artifact 一貫性でも通せるようにする
- [ ] `needs_research -> ready` の復帰パスを明示的に残す
- [ ] `build_candidate_quality()` の `proposal_ready` 判定を v2 仕様へ合わせる
- [ ] `build_proposal_sections()` で `0件` 正常系を壊さないことを確認する

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/scripts/skill_miner_common.py`
  - `plugins/daytrace/scripts/skill_miner_research_judge.py`
  - `plugins/daytrace/scripts/skill_miner_proposal.py`
- 「巨大だから reject」ではなく、「巨大だからまず split を疑う」に変える

### Done Criteria

- [ ] oversized cluster がそのまま最終提案へ流れにくくなる
- [ ] split 後に sub-cluster を ready / needs_research / rejected へ戻せる
- [ ] `0件` が発生しても理由説明が proposal 上に残る

## Track 7. CLAUDE.md Immediate Apply Path

Parallel: Track 1 と Track 2 完了後に着手可

### Checklist

- [ ] `CLAUDE.md` 即適用対象を `cwd/CLAUDE.md` に限定する
- [ ] `cwd/CLAUDE.md` が存在しない場合は、新規作成 diff として扱う方針を明記する
- [ ] 追記位置を `## DayTrace Suggested Rules` セクション末尾に固定する
- [ ] セクションがなければ新規作成する
- [ ] 既存文言との部分一致率が高い候補を duplicate 扱いにする
- [ ] duplicate は skip し、理由だけ表示する
- [ ] 既存ルールと衝突する候補は apply せず、diff preview の提示だけで終了する
- [ ] 既存文言の書き換え、並び替え、削除をしないことを明記する
- [ ] `skill` / `hook` / `agent` に apply path を作らないことを明記する
- [ ] `SKILL.md` に diff preview の出力フォーマット例を入れる

### Implementation Notes

- 対象ファイル:
  - `plugins/daytrace/skills/skill-miner/SKILL.md`
  - `plugins/daytrace/skills/skill-miner/references/classification.md`
- immediate apply は low-risk UX のための例外。自動生成フローへ拡張しない

### Done Criteria

- [ ] 実装者が `CLAUDE.md` apply の境界を誤解しない
- [ ] duplicate / conflict / missing file の 3 ケースが全部仕様化されている

## Track 8. Tests / Benchmark / E2E

Parallel: 各トラックの成果が揃い次第

### Checklist

- [ ] `test_skill_miner.py` に `--days 7` デフォルトのテストを追加する
- [ ] `test_skill_miner.py` に `--all-sessions` override のテストを追加する
- [ ] `evidence_items[]` の schema テストを追加する
- [ ] evidence chain markdown の出力テストを追加する
- [ ] `--dump-intents` の output shape テストを追加する
- [ ] `oversized_cluster -> split -> re-triage` のテストを追加する
- [ ] `proposal_ready 0 件` 正常系のテストを追加する
- [ ] 代表 fixture 5-10 件を tests に組み込む
- [ ] 改修前後の 3 指標を同一 dataset で比較する
- [ ] 比較結果を Markdown レポートに残す

### Deliverables

- [ ] `plugins/daytrace/scripts/tests/test_skill_miner.py`
- [ ] `plugins/daytrace/scripts/tests/fixtures/skill_miner_gold.json`
- [ ] `REPORT-skill-miner-benchmark.md`

### Done Criteria

- [ ] contract 変更が unit test で固定されている
- [ ] 3 指標の before / after が repo 内で確認できる
- [ ] `skill-miner` が `提案成立 / 追加調査待ち / 今回は見送り` を壊さず完走する

## Cross-Cutting Checklist

- [ ] `skill-miner` の default mode が docs / code / tests で一致している
- [ ] `plugin` 分類が code / docs / references から消えている
- [ ] `evidence_items[]` が prepare / proposal / tests で同じ schema になっている
- [ ] `CLAUDE.md` apply path が `cwd` 限定であることが全説明に反映されている
- [ ] B0 の観測結果が Track 4-6 の最終調整に反映されている
- [ ] 他 skill の TODO に影響する変更を混ぜていない

## Recommended Execution Order

1. Track 0 を即完了させる
2. Track 1, Track 2, Track 3 を並列着手する
3. Track 3 の観測結果を見て Track 4-6 の優先度を確定する
4. Track 7 は Track 1, 2 完了後に着手する
5. Track 8 で contract 固定、定量比較、E2E をまとめて行う

## Final Done Criteria

- [ ] `skill-miner` が 4 分類 + 週次モード + evidence chain つき proposal に整合している
- [ ] `prepare` が `evidence_items[]` を持つ candidate JSON を返す
- [ ] `proposal` が raw history 再読込なしで evidence chain を表示できる
- [ ] `CLAUDE.md` の low-risk immediate apply path が安全制約つきで説明・実行できる
- [ ] B0 観測、特徴量改善、クラスタ改善、quality gate 改善、定量比較まで一巡している
