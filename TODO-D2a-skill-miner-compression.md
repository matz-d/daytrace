# TODO D2a. Skill Miner Compression Refactor

Phase: Output Skills
Depends on: D2（現行 `skill-miner` が一度動いていること）

## Goal

`skill-miner` を raw JSONL 直接読込 + staged compression + detail 再取得の 2 CLI 構成へ移行する。

## Parallel Work Map

まず `Track 0` で契約を固定し、その後は `Track 1-5` を並列で進める。

```text
Track 0: 契約固定
  -> Track 1: raw reader / Claude chunking
  -> Track 2: packet extraction / masking
  -> Track 3: blocking / clustering / ranking
  -> Track 4: detail CLI
  -> Track 5: SKILL.md / docs integration

Track 1 + Track 2
  -> Track 3

Track 0 + Track 1
  -> Track 4

Track 3 + Track 4
  -> Track 5

Track 1-5
  -> Track 6: tests / gold set / E2E verification
```

## Track 0. Contract Lock

Parallel: これは最優先。完了後に他トラック着手。

### Checklist

- [x] `skill_miner_prepare.py` の出力 JSON schema を確定する
- [x] `skill_miner_detail.py` の出力 JSON schema を確定する
- [x] `session_ref` の文字列表現を確定する
- [x] `task_shape` の canonical vocabulary を確定する
- [x] `raw_snippet` の 100 文字 cap / `[WORKSPACE]` マスク / URL 正規化ルールを明文化する
- [x] Claude chunking の初期境界条件（`gap_hours=8`, `is_sidechain`）を明文化する
- [x] `plugins/daytrace/scripts/README.md` か plan に契約を反映する

### Done Criteria

- [x] 実装者間で key 名と shape の解釈差がない
- [x] `summarize_findings` などの語彙揺れが解消されている

## Track 1. Raw Reader / Claude Chunking

Parallel: Track 0 完了後すぐ着手可
Depends on: Track 0

### Checklist

- [x] `skill_miner_prepare.py` の CLI 骨組みを追加する
- [x] Claude raw reader を実装する（`~/.claude/projects/**/*.jsonl`）
- [x] Codex raw reader を実装する（`history.jsonl` + `sessions/**/rollout-*.jsonl`）
- [x] Claude の論理セッション分割を実装する
- [x] `is_sidechain` 切替で packet を分ける
- [x] 発言 gap 8 時間以上で packet を分ける
- [x] Codex の `session_id` ベース packet 組み立てを実装する
- [x] `session_ref` を source ごとに安定生成する
- [x] missing / permission denied の graceful degrade を設計する

### Done Criteria

- [x] Claude の長大ファイルが複数 packet に分かれる
- [x] Codex packet が `session_ref` で一意に引ける

## Track 2. Packet Extraction / Masking

Parallel: Track 0 完了後すぐ着手可
Depends on: Track 0

### Checklist

- [x] `primary_intent` 抽出を実装する
- [x] `top_tool` / `tool_signature` 抽出を実装する
- [x] `artifact_hints` 抽出を実装する
- [x] `repeated_rules.normalized` 抽出を実装する
- [x] `representative_snippets` を最大 2 件に制限する
- [x] `raw_snippet` 100 文字 cap を実装する
- [x] path を `[WORKSPACE]/...` にマスクする
- [x] URL をドメインのみ残す正規化を `common.py` ベースで実装する
- [x] packet schema を JSON 出力できるようにする

### Done Criteria

- [x] packet 1 件ごとに必須フィールドが埋まる
- [x] snippet に長すぎる path / URL query が残らない

## Track 3. Blocking / Clustering / Ranking

Parallel: Track 1 と Track 2 の中盤以降で着手可
Depends on: Track 0, Track 1, Track 2

### Checklist

- [x] `top_tool` / `task_shape` ベースの hard-blocking を実装する
- [x] `misc` block への退避ルールを実装する
- [x] block 内 similarity 計算を実装する
- [x] `representative_snippets` の Jaccard を実装する
- [x] `tool_signature` / `artifact_hints` / `repeated_rules` の overlap score を実装する
- [x] union-find ベース cluster 化を実装する
- [x] `near_matches` を生成する
- [x] `unclustered` を生成する
- [x] Frequency × Source Diversity × Recency の candidate ranking を実装する
- [x] LLM に渡す Top N（10-15）だけを出力する

### Done Criteria

- [x] 総当たりではなく block 内比較だけで完走する
- [x] candidate JSON が proposal phase 用に十分小さい
- [x] ranking 順が説明可能である

## Track 4. Detail CLI

Parallel: Track 0 完了後、Track 1 と並行可
Depends on: Track 0, Track 1

### Checklist

- [x] `skill_miner_detail.py` の CLI 骨組みを追加する
- [x] `--refs` で複数 `session_ref` を受けられるようにする
- [x] Claude `session_ref` 解決ロジックを実装する
- [x] Codex `session_ref` 解決ロジックを実装する
- [x] user / assistant の純粋会話ログを返す
- [x] 不要な metadata / system prompt を除外する
- [x] 必要なら集約済み `tool_calls` を返す
- [x] 参照不能 `session_ref` のエラー shape を決める

### Done Criteria

- [x] candidate の `session_refs` をそのまま detail 取得に渡せる
- [x] 選択候補のドラフトに必要な detail が取得できる

## Track 5. SKILL.md / Docs Integration

Parallel: Track 0 完了後に着手可能。仕上げは Track 3,4 後
Depends on: Track 0, final merge requires Track 3, Track 4

### Checklist

- [x] `plugins/daytrace/skills/skill-miner/SKILL.md` を `prepare -> select -> detail -> draft` フローに書き換える
- [x] LLM の責務を「候補の選定・5分類・理由付け」に寄せる
- [x] proposal phase で raw history を読まないことを明記する
- [x] selection 後に `skill_miner_detail.py --refs ...` を呼ぶ手順を明記する
- [x] README に `skill-miner` の staged compression 概要を追記する
- [x] `plugins/daytrace/scripts/README.md` に prepare/detail CLI を追記する

### Done Criteria

- [x] SKILL.md だけで `prepare -> user selection -> detail -> draft` が迷わず実行できる
- [x] README と plan の説明が矛盾しない

## Track 6. Tests / Gold Set / E2E

Parallel: 各トラックの成果が揃い次第
Depends on: Track 1, Track 2, Track 3, Track 4, Track 5

### Checklist

- [x] `skill_miner_prepare.py` の fixture を作る
- [x] Claude chunking のユニットテストを作る
- [x] masking / snippet cap のユニットテストを作る
- [x] blocking / clustering / ranking の fixture テストを作る
- [x] `skill_miner_detail.py` の `session_ref` 解決テストを作る
- [x] broken / missing / permission denied ケースを確認する
- [x] 10-20 論理 session の手動ゴールドセットを作る
- [x] E2E で「提案 -> 選択 -> ドラフト」を通す

### Done Criteria

- [x] 主要 contract がテストで固定されている
- [x] ゴールドセットで明らかな merge しすぎ / split しすぎが少ない
- [x] 自身の履歴データで提案からドラフトまで完走する

## Cross-Cutting Checklist

- [x] 既存 `claude_history.py` / `codex_history.py` の contract を壊していない
- [x] `daily-report` / `post-draft` に影響が出ていない
- [x] `sources.json` を変更せずに成立している
- [x] `session_ref` が prepare/detail 間で唯一の参照契約として機能している
- [x] proposal phase 入力が 100 KB を大きく超えない

## Recommended Execution Order

1. Track 0 を即完了させる
2. Track 1, 2, 4 を並列着手する
3. Track 3 は Track 1, 2 の初版が出た時点で着手する
4. Track 5 は前半を先行し、最終反映は Track 3, 4 完了後に行う
5. Track 6 で contract 固定と E2E を行う

## Final Done Criteria

- [x] `skill_miner_prepare.py` が raw JSONL から candidate JSON を返す
- [x] `skill_miner_detail.py` が `session_ref` から detail JSON を返す
- [x] `skill-miner` が提案時に圧縮ビュー、選択後に detail を使う
- [x] テスト / ゴールドセット / README まで含めて運用可能な状態になる
