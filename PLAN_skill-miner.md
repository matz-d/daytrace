# Skill Miner Detailed Plan v2 — 2026-03-11

## Positioning

`skill-miner` は `daily-report` や `post-draft` と同じ日次出力 skill ではない。

役割:

- 過去セッションから反復パターンを抽出する
- 候補を `CLAUDE.md / skill / hook / agent` に分類する
- 各候補の提案理由と根拠（evidence chain）を返す
- 実装は次セッションへ渡す

これは `自動化を勝手に実装する skill` ではなく `自律的に昇格先を判定する skill` である。

Skill Lifecycle 上の責務:

- `skill-miner`
  - extract
  - classify
  - evaluate
  - propose
- 将来の別 skill
  - create
  - connect
  - apply

この境界を保つことで、現段階では精度と安全性を優先しつつ、将来的な拡張性を残す。

## Product Story

DayTrace は 3 つの独立 skill ではなく、1 つの継続体験として見せる。

- 日次
  - `daily-report`: その日の意味を整理（個人用 / チーム共有用）
  - `post-draft`: その日の一次情報をテックブログとして発信可能な形に変換
- 週次
  - `skill-miner`: 蓄積された行動から、固定化すべき作法を抽出

ユーザーに見せるメッセージ:

- 初回でも、直近 7 日に Claude Code / Codex 履歴があれば即価値が出る
- 審査員はヘビーユーザー。既存履歴が豊富にある前提で設計する
- 毎日は記録と要約を自動化する
- 使うほど evidence が蓄積される
- 週1で `skill-miner` が「次に固定化すべきもの」を提案する
- CLI エージェントを使うほど、DayTrace があなた専用に育っていく

育つ対象:

- 文脈理解
- post-draft の読者層推定
- skill-miner の提案精度
- `CLAUDE.md` に落とすべき作法の発見率

## Why Weekly

`skill-miner` は週次で設計する。

理由:

- 反復パターンは日次より週次で見た方が精度が高い
- 日次では単発タスクが多く、`0件` や giant cluster reject が出やすい
- `recent_packets_7d` を既に使っており、現行 scoring とも整合する

## Execution Mode

### 単一モード設計

lightweight demo mode は廃止する。

理由:

- 審査員は Claude Code / Codex ヘビーユーザーであり、既存履歴が十分にある
- demo 用の精度妥協は不要
- モード分岐による複雑さを排除し、品質を一本化する

### 期間ロジック

- デフォルト実行: 直近 7 日間（`--days 7`）
- 明示指定時のみ: `--all-sessions` で全履歴スキャン
- 全履歴が 7 日未満の場合: 実質的に全履歴が対象になる

判定ロジック:

```
if --all-sessions:
    対象 = 全履歴
else:
    対象 = 直近7日以内の履歴
```

state file は持たない。実行モードは CLI 引数だけで決める。

## Scope

### In Scope

- 反復パターンの抽出
- 候補分類（4 分類）
- 提案と根拠の提示（evidence chain 含む）
- `0件` の理由説明と次回への示唆
- 追加調査による triage 補強（split 判定を主目的とする）
- Python 側の特徴量・クラスタリング改善
- `CLAUDE.md` 候補の即適用パス

### Out Of Scope

- plugin 分類
- 実行中の自動ファイル生成
- グローバル設定の自動変更
- Slack / Google Drive / webhook などの外部連携実装
- `skill` / `hook` の即時生成
- `create / connect / apply` を `skill-miner` 自身が担うこと
- lightweight demo mode

## Classification Targets

分類先は 4 つに絞る。判定基準と境界ケース例は `references/classification.md` に分離する。

- `CLAUDE.md`
  - repo ローカルの原則
  - 毎回説明している作法やルール
- `skill`
  - 明確な入出力を持つ多段フロー
  - 再利用可能な手順
- `hook`
  - 機械的で自動実行向き
  - 判断の余地が少ない
- `agent`
  - 単一フローではなく、継続的な責務や行動原則が中心

除外:

- `plugin`
  - 配布単位であり、一次分類としては粗すぎる

## User Flow

### Main Flow

1. ユーザーが `skill-miner` を実行
2. `prepare` が直近 7 日分、または明示指定時のみ全履歴から candidate view を作る
3. `skill-miner` が候補を `提案成立 / 追加調査待ち / 今回は見送り` に分ける
4. `提案成立` がある場合は分類・根拠・evidence chain を返す
5. 次セッションで、対象候補だけ `apply` フローに進む

### Next Session Flow

- `CLAUDE.md`
  - そのまま追記内容を検討
- `skill`
  - ask_user モードで scope を決めて実装
- `hook`
  - ask_user モードで scope を決めて実装
- `agent`
  - role と trigger を固めてから実装

重要:

- `skill-miner` は中途半端に実装へ踏み込まない
- 代わりに `何を、なぜ、その形にするべきか` を高精度で返す
- `create / connect / apply` は別 skill へ送ることで lifecycle を分離する

### Low-Risk Immediate Apply Path

例外として、`CLAUDE.md` 分類だけは即適用パスを持つ。

理由:

- 4分類の中で最も副作用が小さい
- diff preview を見せやすい
- `提案して終わり` に見える問題を緩和できる
- デモで「環境が実際に良くなる瞬間」を作れる

適用条件:

- 候補分類が `CLAUDE.md`
- 追記内容が短く、repo ローカル原則として自然
- 既存ルールと矛盾しない
- 対象は `cwd/CLAUDE.md` に限定する

適用フロー:

1. `skill-miner` が `CLAUDE.md` 候補を提案
2. `cwd/CLAUDE.md` の末尾に `## DayTrace Suggested Rules` セクションを解決する
3. 既存文言との重複チェックと衝突チェックを行う
4. diff preview を生成
5. ユーザー承認を 1 回だけ取る
6. `CLAUDE.md` に末尾追記する

制約:

- `skill` と `hook` は即適用しない
- `CLAUDE.md` 以外は次セッションの apply フローへ送る
- 既存文言の書き換えや並び替えはしない
- 重複候補は skip して理由を表示する
- 衝突候補は diff preview の提示だけで終了する

## Evidence Chain

提案の根拠として、代表セッション 2-3 件の情報を添える。

含める情報:

- セッションのタイムスタンプ（日付 + 時間帯）
- 1 行要約（primary_intent ベース）
- source（Claude / Codex）

出力例:

```markdown
根拠:
  - 2026-03-08 午後 Claude: plugin 開発時に SKILL.md の構造確認を毎回実施
  - 2026-03-10 午前 Codex: 同様の SKILL.md 参照パターンを codex タスクでも確認
  - 2026-03-11 午前 Claude: 3 回目の同一パターン、artifact は markdown 出力
```

実装方針:

- `prepare` 側で candidate に `evidence_items[]` を埋める
- 各 item は `{session_ref, timestamp, source, summary}` を持つ
- `summary` は packet の `primary_intent` を 1 行表示向けに整形したものを使う
- `proposal` 側では `evidence_items[]` をそのまま表示し、raw history は再読込しない

candidate 出力契約:

```json
{
  "evidence_items": [
    {
      "session_ref": "codex:abc123:1710000000",
      "timestamp": "2026-03-10T09:00:00+09:00",
      "source": "codex",
      "summary": "SKILL.md の構造確認を行い、提案理由を整理"
    }
  ]
}
```

## Negative Proposal（0 件時の対応）

`0件` を失敗扱いにせず、理由と次回への示唆を返す。

出力例:

```markdown
## 今回は見送り

提案成立の候補はありませんでした。

理由:
- 直近 7 日間のセッション数が 4 件で、反復判定に必要な evidence が蓄積途上です
- 検出されたパターンは単一セッション内の作業が多く、cross-session の反復が確認できませんでした

次回への示唆:
- あと 2-3 セッション蓄積されると、反復パターンの検出精度が上がります
- 特に同じ種類の作業（例: レビュー、テスト実行）を複数日にまたがって行うと検出されやすくなります
```

## Data Sources

`skill-miner` は `aggregate.py` を使わない。

使う source:

- `claude-history`
- `codex-history`

使わない source:

- `git-history`
- `chrome-history`
- `workspace-file-activity`

補足:

- `daily-report` と `post-draft` は `aggregate.py` 経由で 5 source を使う
- `skill-miner` は AI 会話履歴に特化する
- 初回で提案が出るかどうかは `直近 7 日の Claude Code / Codex 履歴の量と質` に依存する

## Current Technical Diagnosis

昨日の `0件` は `何もなかった` のではない。

正しい解釈:

- 候補らしき塊はあった
- Python 側の中間表現が generic に寄りすぎた
- 巨大クラスタ + generic cluster として削がれた
- `安全に提案できる 1 件` まで細らなかった

主因は日次フィルタではなく、特徴量とクラスタリングの設計にある。

## Root Causes

### 0. `primary_intent` の抽出品質が未検証

現状:

- `primary_intent` は clustering と判定の重要な基盤
- 実データでの具体度・generic 率・同義語ばらつきが未分析

影響:

- `task_shape` や block key を改善しても、`primary_intent` 自体が曖昧なら精度の天井が低い

改善方針:

- 実データの `primary_intent` 分布を先に分析する
- 具体度、generic 率、空振り率、同義語のばらつきを確認する
- 結果を踏まえて feature extraction を調整する

分岐条件（B0 の結果による後続の優先度変更）:

- generic intent が 60% 超 → B（特徴量改善）を最優先。intent 抽出ロジック自体の見直しが先
- 同義語割れが主因 → B に正規化レイヤーを追加（intent synonyms map）
- 具体的 intent は取れているが shape が上書き → C（クラスタリング）の重み調整が先
- intent も shape も良好 → D（Quality Gate）の閾値調整のみで解決可能

### 1. `task_shape` が generic を先に拾いすぎる

現状:

- `TASK_SHAPE_PATTERNS` で `review_changes`, `summarize_findings`, `search_code`, `inspect_files` が先に評価される
- 3 件で打ち切り

影響:

- 異なる目的が `review/search` 系の generic shape に吸われやすい

改善方針:

- generic shape を後ろへ回す
- 具体的な shape を先に拾う

具体的な優先候補:

- `prepare_report`
- `write_markdown`
- `debug_failure`
- `implement_feature`
- `edit_config`
- `run_tests`

### 2. block key が粗すぎる

現状:

- `stable_block_keys` は `top_tool` と `first_shape` だけ
- 典型例は `tool:rg` や `task:review_changes`

影響:

- 比較対象の候補集合が広すぎる
- `bash/rg/sed` 中心の作業が giant cluster になりやすい

改善方針:

- 複合キーを追加する
  - `task + artifact`
  - `task + repeated_rule`
  - `artifact + repeated_rule`

### 3. similarity が「作業の型」に寄りすぎる

現状:

- `task_shapes` 0.40
- `rules` 0.25
- `snippet` 0.15
- `artifacts` 0.15
- `tools` 0.05

影響:

- 同じ review/search の作法を使う別目的作業がまとまりやすい

改善方針（目標値の叩き台）:

- task_shapes: 0.40 → 0.30（generic shape の影響を下げる）
- rules: 0.25 → 0.20
- snippet/intent: 0.15 → 0.25（目的の一致をより重視）
- artifacts: 0.15 → 0.20（成果物の一致をより重視）
- tools: 0.05 → 0.05（据え置き）

検証方法:

- 実データで現行重みと新重みの A/B 比較を行う
- giant cluster の発生率と提案成立数で評価

### 4. oversized cluster の扱い — split 優先への変更

変更前:

- oversized（8 packets + 50% share）は `needs_research` に送り、research judge で promote/reject
- 事実上の強いブレーキとして機能していた

変更後:

- oversized cluster の第一仮説は「複数の目的が混在している」
- research phase の目的を promote ではなく split 判定に変更
- split 後の sub-cluster を個別に triage する

処理フロー:

```
oversized cluster 検出
  ↓
research phase（detail sampling）
  ↓
split 判定: sub-cluster に分解可能か？
  ├── 可能 → sub-cluster 生成 → 各 sub に対して通常の triage
  ├── 不可能だが coherent → promote_ready
  └── 不可能で incoherent → reject_candidate
```

実装上の変更:

- `judge_research_candidate` に split 後の再クラスタリングパスを追加
- split 判定の基準: 2 つ以上の non-generic primary_shape が存在し、shape 間の overlap が低い（< 0.15）
- split 後の sub-cluster は最小 2 packets を要求

### 5. research judge の promote 条件が厳しい

現状:

- `shape_count >= 2`
- `avg_overlap >= 0.12`
- `repeated_rule_count >= 1` または `non-generic shape`

改善方針:

- detail 側では `primary_intent` と artifact をより重く扱う
- `shape_count` の条件をやや緩める（>= 2 → >= 1 でも intent 一貫性が高ければ可）
- repeated rule がなくても、目的一貫性が高ければ promote 可能にする

### 6. テストが中間ケースに弱い

足りないケース:

- レビュー + 記事調査 + 実装確認
- report 生成 + markdown 編集 + リサーチ
- config 更新 + feature 実装 + test 実行

改善方針:

- `半分似ていて半分違う` fixture を増やす
- promote / split / reject の境界ケースを増やす
- B0（実データ分析）の副産物として、代表的な packet パターンを匿名化して fixture 化する

## Detailed Workstreams

### Workstream A. Product / UX Rewrite

対象:

- `plugins/daytrace/skills/skill-miner/SKILL.md`
- `plugins/daytrace/skills/skill-miner/references/classification.md`（新規）

内容:

- 週次のみを明記（lightweight mode の記述を削除）
- 4 分類に整理
- 責務を `分類・提案・根拠提示` に絞る
- 実装は次セッションに渡す前提にする
- `0件` を失敗扱いしない（negative proposal + 次回への示唆）
- `CLAUDE.md` 即適用パスを low-risk 例外として定義する
- evidence chain の出力仕様を追加
- 4 分類の判定基準と境界ケース例を `references/classification.md` に分離

Done criteria:

- `skill-miner` の説明が `分類エージェント` として一貫する
- plugin や自動生成の記述が残っていない
- lightweight mode の記述が残っていない
- `CLAUDE.md` 即適用の位置づけが明確
- evidence chain の出力仕様が定義されている
- `references/classification.md` に 4 分類の判定基準と境界ケース例がある

### Workstream B0. Real Data `primary_intent` Analysis

対象:

- `plugins/daytrace/scripts/skill_miner_common.py`
- `plugins/daytrace/scripts/skill_miner_prepare.py`

内容:

- `prepare.py` に `--dump-intents` を追加し、全 packet の `primary_intent` を観測できるようにする
- マコさんの実データから全 packet の `primary_intent` 分布を見る
- generic intent の割合を確認する
- 同義語割れ率を確認する
- 具体度分布を確認する
- 具体的 intent の抽出に失敗しているパターンを分類する
- 匿名化は既存の path / URL mask をそのまま使う
- 成果物は `generic率 / 同義語割れ率 / 具体度分布` の 3 指標とする
- 代表的な packet パターンを匿名化して fixture 用に 5-10 件保存する

Done criteria:

- `primary_intent` の精度上限を把握できる
- 後続改善の優先順位が実データベースで決まる
- 匿名化 fixture が 5-10 件生成されている
- B0 の出力に 3 指標と代表 fixture 一覧が含まれている

分岐出力:

- B0 の結果レポートに「B/C/D のどれを最優先にすべきか」の判定を含める

### Workstream B. Feature Extraction Improvements

対象:

- `plugins/daytrace/scripts/skill_miner_common.py`

内容:

- `TASK_SHAPE_PATTERNS` の順序見直し（generic を後ろへ）
- generic pattern の後ろ倒し
- shape 打ち切りロジックの調整
- `artifact_hints` と `repeated_rules` の精度改善
- B0 の結果に応じて:
  - intent 正規化レイヤーの追加
  - intent synonyms map の導入

Done criteria:

- generic-only な shape に偏りにくくなる
- `primary_intent` と shape が矛盾しにくくなる

### Workstream C. Clustering Improvements

対象:

- `plugins/daytrace/scripts/skill_miner_common.py`
- `plugins/daytrace/scripts/skill_miner_prepare.py`

内容:

- `stable_block_keys` の複合化
- `similarity_score` の重み調整（目標値: shapes 0.30 / rules 0.20 / snippet 0.25 / artifacts 0.20 / tools 0.05）
- generic tool 依存の緩和
- giant cluster を発生させにくい入口へ変更

Done criteria:

- `tool:rg` 系 giant cluster の発生率が下がる
- 異なる目的作業の誤結合が減る
- 実データで A/B 比較を行い、提案成立数が改善する

### Workstream D. Quality Gate Rebalance

対象:

- `plugins/daytrace/scripts/skill_miner_common.py`

内容:

- `oversized_cluster` の処理を split 優先に変更
- `judge_research_candidate` に split 後の再クラスタリングパスを追加
- `proposal_ready` 条件の調整
- promote 条件の緩和（intent 一貫性ベース）
- `needs_research` から `ready` への復帰余地を増やす

Done criteria:

- oversized cluster は第一仮説として split を試みる
- split 後の sub-cluster が個別に triage される
- 実運用で `0件` しか出ない状態が緩和される

### Workstream E. Test Expansion

対象:

- `plugins/daytrace/scripts/tests/test_skill_miner.py`
- `plugins/daytrace/scripts/tests/fixtures/skill_miner_gold.json`

内容:

- B0 で生成した匿名化 fixture を組み込む
- 中間ケース fixture の追加
- `promote_ready`, `split_candidate`, `reject_candidate` の境界ケース追加
- oversized cluster の split → 再 triage フロー全体のテスト
- evidence chain 出力のテスト

Done criteria:

- きれいなケースと崩れたケースの間をテストできる
- 今回の 81 packet 型失敗を再現できる
- split 後の再クラスタリングが正しく動作する
- evidence chain が正しいフォーマットで出力される

## Quantitative Validation

比較指標は 3 つに絞る。

- giant cluster 発生率
  - `oversized_cluster` flag を持つ candidate の割合
- 提案成立数
  - `proposal_ready=true` の candidate 数
- `0件` 率
  - 提案成立 0 件で終了する実行の割合

検証方法:

- 改修前後で同一データセットに対して 3 指標を比較する
- 指標の改善が見られない場合は、B/C/D の閾値か重みを再調整する

## Suggested Execution Order

1. **A: Product / UX rewrite**（SKILL.md + references/classification.md）
2. **B0: Real data primary_intent analysis**（マコさんの実データ）
3. **B0 の結果を踏まえて B/C/D の優先順位を確定**
4. **B: Feature extraction improvements**
5. **C: Clustering improvements**
6. **D: Quality gate rebalance**（split 優先化）
7. **E: Test expansion**（B0 の匿名化 fixture を含む）
8. **実データで再検証**

B0 が分岐点であり、その結果次第で 4-6 の順序が変わりうる。

## Future Expansion

将来的には `skill-miner` の後段に別 skill を追加できるようにする。

想定レイヤー:

- `skill-miner`
  - extract / classify / evaluate / propose
- `skill-apply` または同等の別 skill
  - create / connect / apply

候補:

- `skill-builder`
  - `skill` を実際に作る
- `skill-connector`
  - 外部連携や環境接続を設定する
- `skill-apply`
  - 候補を実際の変更として適用する

将来設計メモ（confidence calibration）:

- 提案に対するユーザーの accept/reject を記録する仕組みを検討
- 次回の scoring に反映することで「育つ」ストーリーの実質を持たせる
- `~/.daytrace/feedback.json` のような形で蓄積

重要:

- 今回の plan は `未実装だから後回し` ではない
- 意図的に lifecycle を分け、`skill-miner` の説明性と精度を優先する判断である

## Success Criteria

- `skill-miner` を週次最適化モードとして一貫して説明できる
- 初回でも直近 7 日の Claude Code / Codex 履歴から提案価値を返せる
- `CLAUDE.md` 候補については、承認 1 回で即適用できる
- evidence chain により提案の根拠が具体的に見える
- `0件` の頻度が下がるか、少なくとも理由と次回への示唆が納得しやすい
- giant cluster が split 優先で処理され、提案成立率が上がる
- 提案成立の候補が `generic work style` ではなく `実際の reusable workflow` に近づく
- 次セッションで `CLAUDE.md / skill / hook / agent` 実装に繋げやすい出力になる
- `extract / classify / evaluate / propose` と `create / connect / apply` の境界を一貫して説明できる
- 4 分類の判定基準が `references/classification.md` に分離されている

## Demo Framing

デモではこう見せる。

1. `daily-report` と `post-draft` でその場の価値を見せる
2. `daily-report --team` でチーム共有用の簡潔な出力も見せる
3. `skill-miner` を回す（審査員の既存履歴があるので即結果が出る）
4. `あなたの作業習慣から、次に固定化すべきものはこれ` と分類 + evidence chain つきで返す
5. `CLAUDE.md` 候補なら diff preview → 承認 → 即適用まで見せる
6. 最後に `継続利用すると週次でさらに精度が育つ` と締める

この framing により:

- 初回で価値が出ないように見える問題 → 直近 7 日の既存履歴で即価値。必要なら `--all-sessions` で深掘り
- `0件` が失敗に見える問題 → negative proposal + 次回示唆
- 自動実装しないことが弱く見える問題 → CLAUDE.md 即適用で「変化する瞬間」を見せる
- `提案だけ` に見える問題 → evidence chain で納得感を担保

を抑えられる。
