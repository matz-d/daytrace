# Skill Miner Staged Compression Plan

## Goal

`skill-miner` の全セッション横断分析を、CLI エージェントの強みを落とさずに安定動作させる。

達成したいこと:

- 全履歴をそのまま LLM に投げず、段階的に圧縮する
- ただし「意味」や「意外な発見」の余地は残す
- `skill` / `plugin` / `agent` / `CLAUDE.md` / `hook` の分類根拠を弱めない
- 提案フェーズとドラフト生成フェーズで必要な情報量を分ける
- 提案フェーズの前処理は deterministic にし、LLM は理由付けと 5 分類に集中させる

## Current Problem

現状の [`plugins/daytrace/skills/skill-miner/SKILL.md`](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-miner/SKILL.md) は、以下の 2 つの source CLI を直接実行する前提になっている。

- `python3 plugins/daytrace/scripts/claude_history.py --all-sessions`
- `python3 plugins/daytrace/scripts/codex_history.py --all-sessions`

問題は、これらの出力が「採掘用」ではなく「閲覧用」の event 粒度であること。

- Claude は 1 ファイル 1 event 寄りで、長い会話もまとめて 1 件になりやすい
- Codex は 1 session が `session_meta` / `commentary` / `tool_call` に分かれ、skill-miner には冗長
- 提案フェーズに不要な detail が多く、件数増加時にコンテキスト消費が先に効く
- 提案後に対象候補だけ detail を掘り直す経路も明示されていない

この環境での観測値:

- Claude: 36 events / 約 62.6 KB
- Codex: 81 events / 約 82.8 KB
- Claude event 平均: 約 1336 bytes
- Codex `commentary` 平均: 約 872 bytes
- Codex `session_meta` 平均: 約 556 bytes
- Codex `tool_call` 平均: 約 405 bytes

規模がさらに増えると、特に Codex 側の event 分割と excerpt 重複が先に効いてくる。

## Core Decision

圧縮は必要。ただし、**既存 source CLI の event contract に依存しない**。

採用方針:

- `skill-miner` 用に `skill_miner_prepare.py` と `skill_miner_detail.py` を新設する
- `prepare` は既存 CLI の stdout を再変換せず、raw JSONL を直接読んで mining packet を作る
- `detail` は `session_ref` を受け取り、選択候補に必要な会話 detail だけを返す
- Claude 履歴はファイル単位ではなく、時間 gap と `is_sidechain` を使って論理セッションに分割する
- packet clustering は `O(n^2)` 総当たりを避け、hard-blocking 後に block 内だけで類似度計算する
- Python 側で Top N candidate に絞り、LLM は候補比較・5 分類・理由付けに集中する

採用しない方針:

- 既存 source CLI の event JSON をそのまま parent agent に渡す
- 既存 source CLI の stdout をさらに変換するだけの薄い wrapper に留める
- 前処理だけで最終分類まで確定させる
- 代表例 1 件だけを残して元 session 参照を捨てる

## Design Principles

### 1. Compress representation, not meaning

削る対象:

- 同一論理セッション内で重複するメタ情報
- 長い excerpt の細部
- 候補抽出に不要な詳細時系列

残す対象:

- 何をやろうとしていたか
- どのツール列・手順が反復したか
- 何が成果物として出たか
- なぜその分類候補になるか
- 元 detail に戻るための参照

### 2. Prepare and detail are separate products

提案フェーズとドラフトフェーズは別 CLI に分ける。

- `skill_miner_prepare.py`: packet 化、cluster 化、candidate ranking まで
- `skill_miner_detail.py`: 選択候補の `session_ref` から detail を再取得

### 3. Logical session over physical file

Claude 側は「1 ファイル = 1 作業単位」とは扱わない。

- 最終発言から一定時間以上空いたら別 packet
- `is_sidechain` が切り替わったら別 packet
- 長大な会話ファイルを複数の論理セッションに切る

これにより、反復作業抽出の粒度を揃える。

### 4. Loss-aware compression

圧縮後の各 packet / candidate に必ず以下を残す。

- `session_ref`
- `representative_snippets`
- `support`
- `why this cluster exists`

### 5. Deterministic preprocessing, LLM for reasoning

Deterministic preprocessing の責務:

- 正規化
- packet 化
- block 作成
- cluster 化
- candidate の scoring と ranking

LLM の責務:

- 候補の価値判断
- 5 分類の仮説選択
- なぜその分類かの説明
- 候補 3-5 件への絞り込み
- 選択後 detail を読んだ上でのドラフト生成

## Target Architecture

### Stage 0. Raw source collection

既存 source CLI は残すが、`skill-miner` の main path では使わない。

読む raw source:

- Claude: `~/.claude/projects/**/*.jsonl`
- Codex: `~/.codex/history.jsonl`
- Codex: `~/.codex/sessions/**/rollout-*.jsonl`

既存スクリプトとの関係:

- `claude_history.py` / `codex_history.py` は daily-report / post-draft / debug 用として維持
- `skill-miner` は raw JSONL 直接読込 path を持つ
- sanitize や datetime utility は既存 [`plugins/daytrace/scripts/common.py`](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/common.py) を再利用する

### Stage 1. Logical session packet generation

新しい軽量な中間単位 `mining packet` を導入する。

原則:

- 1 packet = 1 論理セッション
- Claude はファイルをそのまま 1 packet にせず、時間 gap / `is_sidechain` で分割する
- Codex は `session_id` を軸に session を組み立てる

#### Claude packet boundary

Claude の packet 分割ルール:

- 同一ファイル内で発言 gap が 8 時間以上空いたら新 packet
- `is_sidechain` が切り替わったら新 packet
- 同一 packet には連続した user / assistant message を積む

初期値:

- `gap_hours = 8`

理由:

- 数ヶ月にわたる履歴ファイルでも、作業単位に近い塊へ分解できる
- ファイル単位より反復作業の抽出精度が高い

#### Packet schema

`prepare.py` の packet schema は以下で固定する。

```json
{
  "packet_id": "claude:projects_repoA_001",
  "source": "claude-history",
  "session_ref": "claude:/Users/.../session.jsonl:1710000000",
  "session_id": "session-abc",
  "workspace": "/repo/path",
  "timestamp": "2026-03-09T14:30:00+09:00",
  "top_tool": "rg",
  "tool_signature": ["rg", "sed", "git"],
  "task_shape": ["review_changes", "summarize_findings"],
  "artifact_hints": ["review", "markdown"],
  "primary_intent": "レビュー依頼への findings-first 対応",
  "representative_snippets": [
    "review findings を整理して返す",
    "指摘を severity 順で列挙する"
  ],
  "repeated_rules": [
    {
      "normalized": "findings-first",
      "raw_snippet": "findings を severity 順に並べる..."
    }
  ],
  "support": {
    "message_count": 12,
    "tool_call_count": 5
  }
}
```

必須フィールド:

- `packet_id`
- `source`
- `session_ref`
- `timestamp`
- `primary_intent`
- `representative_snippets`

#### Packet mapping rules

`claude-history`:

- `primary_intent`
  - 先頭 user message を優先し、無ければ packet 全体の短い要約を作る
- `tool_signature`
  - text と `tool_use` 表現からコマンド名 / tool 名を抽出
- `top_tool`
  - 最頻出 tool を 1 件採用。抽出できなければ `"none"`
- `artifact_hints`
  - message 内の語から推定
- `repeated_rules`
  - assistant 側の出力方針や禁則を正規化

`codex-history`:

- `primary_intent`
  - `history.jsonl` の user prompt excerpt を優先
- `tool_signature`
  - rollout 内 `function_call` の頻度順
- `top_tool`
  - 最頻出 tool を 1 件採用。抽出できなければ `"none"`
- `artifact_hints`
  - user / assistant excerpt と tool の組み合わせから推定
- `repeated_rules`
  - assistant commentary の定型方針を正規化

共通ルール:

- `primary_intent` は 1 文に正規化する
- `representative_snippets` は最大 2 件
- `raw_snippet` は 100 文字 cap
- path は `[WORKSPACE]/...` にマスク
- URL はドメインのみ残し query / fragment を除去する
- source 間で同じ意味になる語は同じラベルへ寄せる

#### `task_shape` vocabulary

`task_shape` は自由テキストではなく固定語彙を採用する。

初期語彙:

- `inspect_files`
- `search_code`
- `run_tests`
- `review_changes`
- `summarize_findings`
- `write_markdown`
- `edit_config`
- `implement_feature`
- `debug_failure`
- `prepare_report`

方針:

- 1 packet あたり最大 3 語まで
- 未知の作業は `artifact_hints` と `representative_snippets` に残す
- 語彙追加はゴールドセット比較で必要になった時だけ行う

### Stage 2. Candidate clustering

複数 packet をクラスタリングして候補にまとめる。

#### Hard-blocking

まず packet を block に分ける。

block key の初期案:

- `top_tool`
- 先頭 `task_shape`

block rule:

- `top_tool` が一致する packet は同 block 候補
- `top_tool` が `"none"` の場合は `task_shape[0]` を優先
- どちらも弱い packet は `misc` block に入れる

狙い:

- 類似度計算の対象を block 内だけに限定し、総当たりを避ける

#### Block 内 score

同じ block 内でのみ類似度を計算する。

MVP score:

- `representative_snippets` の単語集合 Jaccard
- `tool_signature` の Jaccard
- `artifact_hints` overlap
- `repeated_rules.normalized` overlap

実装方針:

- まずは Jaccard 中心で始める
- TF-IDF は必要になった時点で置換または追加する

初期閾値案:

- cluster 化: 0.60 以上
- near-match: 0.45-0.59

cluster 化:

- block 内で閾値以上の packet を union-find 的にまとめる

#### Candidate schema

`prepare.py` の candidate schema は以下で固定する。

```json
{
  "candidate_id": "repo-review-flow",
  "label": "レビュー依頼への findings-first 対応",
  "score": 8.4,
  "support": {
    "total_packets": 7,
    "claude_packets": 2,
    "codex_packets": 5,
    "total_tool_calls": 18,
    "unique_workspaces": 3,
    "recent_packets_7d": 3
  },
  "common_task_shapes": ["review_changes", "summarize_findings"],
  "common_tool_signatures": ["rg", "sed", "git"],
  "artifact_hints": ["review", "markdown"],
  "rule_hints": ["findings-first", "severity-ordering"],
  "representative_examples": [
    "review request -> inspect files -> findings output",
    "same report format repeated across repos"
  ],
  "session_refs": [
    "codex:abc123:1710000000",
    "claude:/Users/.../session.jsonl:1710003600"
  ],
  "near_matches": [
    {
      "packet_id": "codex:def456",
      "score": 0.52,
      "primary_intent": "PR を読んで改善提案をまとめる"
    }
  ]
}
```

#### Candidate ranking

LLM に渡す candidate は Python 側で並べ替えて絞る。

加重スコア:

- Frequency: 出現回数が多いほど高スコア
- Source Diversity: Claude と Codex 両方に出た候補にボーナス
- Recency: 直近 7 日の packet を追加加点

初期方針:

- `score = frequency_weight + diversity_bonus + recency_bonus`
- Top 10-15 件のみを LLM に渡す
- Top N 外でも score が近い候補は `near_matches` に残す

#### Unclustered の扱い

- どの cluster にも入らなかった packet は `unclustered` として保持する
- LLM に渡すのは timestamp 降順の上位 10 件まで
- cluster 候補が少ない時だけ参照する

### Stage 3. Prepare output to LLM

親エージェントに渡すのは raw event 群ではなく、次の圧縮ビューのみ。

- ranked candidates
- unclustered packets 上位 10 件
- schema 上の support / representative_examples / session_refs

親エージェントの責務:

- 候補 3-5 件を選ぶ
- 5 分類へ仮分類する
- なぜその分類かを説明する
- 価値が低い候補を落とす

やらせないこと:

- raw history 全量の再読
- clustering のやり直し
- top N 外の大規模探索

## Drill-down Architecture

### Stage 4. Detail retrieval for selected candidate

ユーザーが 1 候補を選んだら、その候補に紐づく `session_refs` だけを `skill_miner_detail.py` で再取得する。

`skill_miner_detail.py` の入力:

- `--refs <session_ref> ...`

`session_ref` 形式:

- Claude: `claude:/absolute/path/to/file.jsonl:1710000000`
- Codex: `codex:<session_id>:1710000000`

解決方針:

- Claude は file path と packet start timestamp から該当 packet を特定する
- Codex は `session_id` と packet anchor timestamp から該当範囲を特定する

#### Detail schema

```json
{
  "status": "success",
  "details": [
    {
      "session_ref": "codex:abc123:1710000000",
      "source": "codex-history",
      "workspace": "/repo/path",
      "timestamp": "2026-03-09T14:30:00+09:00",
      "messages": [
        {
          "role": "user",
          "text": "review をお願いします"
        },
        {
          "role": "assistant",
          "text": "まず差分を読み、findings を severity 順に整理します"
        }
      ],
      "tool_calls": [
        {"name": "rg", "count": 3},
        {"name": "sed", "count": 2}
      ]
    }
  ]
}
```

返すもの:

- user / assistant の純粋な会話ログ
- 必要なら集約済み tool_calls

返さないもの:

- system prompt
- 不要な session metadata
- proposal phase に不要な raw event 全量

## Ownership by Layer

### Source / preprocessing layer

責務:

- raw JSONL の読込
- 論理 session 化
- packet 生成
- block 作成
- cluster 生成
- candidate ranking
- `session_ref` の発行

非責務:

- 最終分類の断定
- ドラフト文章の生成
- UI 上の候補文言の最終調整

### Parent agent

責務:

- candidate 3-5 件の選定
- 5 分類への仮分類
- 理由付け
- ユーザーへの提案文生成
- 選択後の detail 読解
- ドラフト生成

## Classification Guidance

5 分類は均等ではなく、証拠閾値を変える。

### `skill`

強い証拠:

- 明示トリガーがある
- 複数ステップの定型フロー
- 出力フォーマットが安定

### `CLAUDE.md`

強い証拠:

- repo ローカルの常設ルール
- 毎回同じ作法説明
- 手順より原則の固定化が主目的

### `hook`

強い証拠:

- 実行タイミングが明確
- 判断不要の機械的処理
- 人が毎回呼ばなくてよい

### `agent`

強い証拠:

- 複数 task を横断する長い役割定義
- 振る舞いの一貫性が価値の中心

### `plugin`

強い証拠:

- 複数 skill をまとめて初めて価値が出る
- 配布単位としての理由が明確

優先度の考え方:

- DayTrace の履歴から直接観測しやすいのは `skill` / `CLAUDE.md` / `hook`
- `agent` / `plugin` は二次推論が多く、過剰提案を避ける

## SKILL.md Rewrite Direction

`skill-miner` の main path は staged flow に変える。

変更方針:

1. `skill_miner_prepare.py` を 1 回だけ実行する
2. candidate JSON から 3-5 件の提案リストを返す
3. ユーザーに 1 候補選ばせる
4. その候補の `session_refs` を使って `skill_miner_detail.py --refs ...` を実行する
5. 選択候補の分類に応じたドラフトを生成する

LLM への主指示:

- Python 側の cluster を尊重する
- 3-5 件に絞る
- 5 分類と理由付けに集中する
- detail を読むのは選択後だけ

## Interface Decision

`skill_miner_prepare.py` / `skill_miner_detail.py` は MVP では `sources.json` に登録しない。

理由:

- `aggregate.py` を通らない `skill-miner` 専用経路だから
- 既存 source registry 契約を増やさずに済むから
- `daily-report` / `post-draft` への影響を避けられるから

拡張パス:

- 将来、他 skill でも packet / detail 再取得を再利用したくなったら共通 library 化を検討する
- ただし初期は独立スクリプトとして保ち、責務を分ける

## Contract Documentation

実装前に固定する契約:

- `skill_miner_prepare.py` の出力 JSON
- `skill_miner_detail.py` の出力 JSON
- `task_shape` の固定語彙
- `session_ref` の文字列表現

文書化先:

- この plan
- 必要なら [`plugins/daytrace/scripts/README.md`](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/README.md)

要求:

- キー名を途中で変えない
- 配列と単一値の shape を固定する
- `summarize_findings` のような正規語彙を唯一の canonical name にする

## Validation Plan

以下を確認する。

1. 小規模履歴
   - 候補の質が落ちない
2. 長大な Claude 単一ファイル
   - gap 分割で packet 粒度が改善する
3. 大規模履歴
   - hard-blocking で prepare が安定して完走する
4. 提案フェーズ
   - Top N candidate が 100 KB を大きく超えない
5. ドラフト生成
   - detail 再取得で具体性が維持される
6. 手動ラベルとの比較
   - ゴールドセットと cluster 妥当性を照合する

評価指標:

- 候補 3 件以上を安定して出せるか
- 各候補に分類理由があるか
- 根拠 source と件数が示されるか
- 選択後ドラフトの具体性が維持されるか
- block 数と block 内比較数が想定内に収まるか
- ゴールドセット上で merge しすぎ / split しすぎが少ないか

ゴールドセット方針:

- まず 10-20 論理 session を人手で読む
- 期待 cluster と想定分類をメモする
- `skill` / `CLAUDE.md` / `hook` の境界が曖昧な例を意図的に含める
- tool や task_shape は違うが意味的に同じ作業のペアを意図的に含める
- 自動結果と比較し、merge しすぎ / split しすぎの両方を見る

## Risks

### Risk 1. Claude chunking が過剰分割になる

症状:

- 1 つの作業が複数 packet に割れすぎる

対策:

- `gap_hours` を fixture で調整する
- `is_sidechain` 単独ではなく時間条件も見て調整可能にする

### Risk 2. Hard-blocking が粗すぎて似た候補が別 block に分かれる

症状:

- cluster recall が下がる

対策:

- `top_tool` と `task_shape` のどちらか一致で block 候補にする
- `misc` block の上位だけを別途観察する

### Risk 3. raw_snippet が still too verbose

症状:

- 提案 JSON が再び膨らむ
- 不要な path / text が露出する

対策:

- 100 文字 cap
- `[WORKSPACE]` マスク
- URL ドメインのみ保持

### Risk 4. prepare / detail で parser が二重実装になる

症状:

- Claude / Codex parser の保守箇所が増える

対策:

- 共通 sanitize / datetime は `common.py` を再利用する
- raw reader の共通関数は `skill-miner` 用内部 helper に寄せる

### Risk 5. Added complexity hurts demo

症状:

- 実装が複雑になり説明しづらい

対策:

- MVP は `prepare` + `detail` + `SKILL.md` 改修に限定する
- TF-IDF や child agent は後回し

## Deliverables

提出前の最低成果物:

- `skill_miner_prepare.py`
- `skill_miner_detail.py`
- 更新された [`plugins/daytrace/skills/skill-miner/SKILL.md`](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-miner/SKILL.md)
- representative fixture / test
- 10-20 論理 session の手動ゴールドセット
- README への一文追記
  - `skill-miner` は提案時に圧縮 candidate view を使い、選択後のみ detail を読む

## Recommended One-Day Implementation Order

1. 契約の定義
   - `prepare.py` と `detail.py` の JSON schema を固定する
2. CLI の実装
   - raw JSONL 読込、Claude chunking、100 字マスク、blocking、candidate ranking を作る
3. detail の実装
   - `session_ref` から特定 packet の会話ログを抽出する
4. `SKILL.md` 改修
   - `prepare -> proposal -> select -> detail -> draft` に書き換える
5. テストと E2E 確認
   - 自身の履歴データで提案からドラフト生成まで通す

## Decision Summary

最終方針は次の通り。

- `skill-miner` は既存 source CLI の stdout 再利用ではなく raw JSONL 直接読込に切り替える
- `skill_miner_prepare.py` と `skill_miner_detail.py` を分ける
- Claude 履歴は時間 gap と `is_sidechain` で論理 session に分割する
- `raw_snippet` は 100 字 cap + `[WORKSPACE]` マスク + URL 正規化をかける
- clustering は hard-blocking 後の block 内類似度計算で行う
- candidate ranking は Frequency × Source Diversity × Recency を使う
- LLM は 3-5 候補の選定、5 分類、理由付け、選択後ドラフト生成に集中する
- `session_ref` は prepare と detail をつなぐ唯一の参照契約にする
- スキーマ語彙は plan 上で固定し、実装はそれに完全準拠させる
