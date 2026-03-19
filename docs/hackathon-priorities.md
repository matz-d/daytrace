# Hackathon Priorities

このドキュメントは、ハッカソン提出前に DayTrace で何を優先し、何を設計止まりにするかを明確に残すためのメモ。
理想はすべて行うことだが、限られた時間で審査員体験を最大化することを優先する。

## 1. 現時点の判断

- 分類刷新（`LLM first + guardrails`）は価値が高いが、影響範囲が広い
- ハッカソン前は、審査員が直接触る体験の改善を優先する
- したがって、提出前の優先順位は以下の 4 つとする

## 2. 優先順位

### Priority 1. `README.md` を仕上げる

目的:

- 審査員が 1-3 分で価値を理解できる状態にする
- 作品のコンセプト、試し方、自律性、出力例を即座に伝える

最低限入れるもの:

- 1 行で伝わるコンセプト
- ヒーロー図
- すぐ試せる手順
- 実際の入力例
- 実際の出力例
- 自律性の説明（何を自動でやり、どこでだけ人に確認するか）
- `shared` / `workspace` / `all-day` の扱い

優先理由:

- README は審査員体験そのもの
- 実装を 1 つ良くするより、README を 1 段良くした方が評価に効く可能性が高い

### Priority 2. 共有用レポートから個人ログ臭を落とす

目的:

- `shared` モードで個人用ログがそのまま出てしまうリスクを減らす
- 審査員や第三者に見せられる出力へ寄せる

特に避けたいもの:

- Chrome 履歴由来の固有ページ名
- ローカルパス
- 生々しい会話断片
- 個人端末前提の行動ログ

やること:

- `shared` モードの出力ポリシーを明示する
- source ごとの扱いを見直す
- 最終出力での redact / abstract 化を強める

優先理由:

- これは品質だけでなく trust の問題
- README より下のレイヤだが、審査員が気づいた時のダメージが大きい

### Priority 3. 日報 / post-draft の最終文章を読みやすくする

現状の問題:

- 関数名、CLI 名、ファイル名、英単語列がそのまま本文に出やすい
- evidence はあるが、人が読む文章としては固い
- 技術者には読めても、審査員や第三者にはノイズが多い

やること:

- raw な実装名をそのまま列挙しすぎない
- 活動要約を日本語の行動レベルへ寄せる
- evidence は残しつつ、本文は自然文にする
- 自分用 / 共有用で語彙のレベル差を強める

例:

- `aggregate.py を修正` ではなく `ログ集約処理を改善`
- `infer_suggested_kind` ではなく `分類ロジック`
- `workspace-file-activity` ではなく `作業痕跡の補助ログ`

優先理由:

- 出力の第一印象に直結する
- 審査基準の「クオリティ」に最も効く
- 分類刷新より軽く、改善効果が見えやすい

### Priority 4. 分類刷新（`LLM first + guardrails`）

位置づけ:

- 理想的にはやりたい
- ただし、ハッカソン前は「余力があればやる」

狙い:

- `CLAUDE.md / skill / hook / agent` の境界を、ルールベースだけでなく意味判断で扱う
- 特に `CLAUDE.md` と `agent`、`skill` と `agent` の境界を自然にする

基本方針:

- LLM は一次判定
- Python は guardrail
- final kind は Python が確定

この方式の利点:

- 曖昧境界を柔軟に扱える
- `hook` のような危険な分類は deterministic に防げる
- テスト対象を guardrail に寄せられる

## 3. なぜ Priority 4 は重いのか

`LLM first + guardrails` は単純な分類関数差し替えではない。
以下に波及するため、提出直前に入れるにはやや重い。

- `skill_miner_common.py`
  - `infer_suggested_kind*`
  - `build_proposal_sections`
  - `build_candidate_decision_key`
  - `build_candidate_decision_stub`
  - `build_next_step_stub`
- `skill_miner_proposal.py`
  - classification overlay の入力口が必要
- decision log / carry-forward
  - `decision_key` に `suggested_kind` が含まれているため、分類変更が suppress / resurface に影響する
- docs / contracts
  - `skill-miner/SKILL.md`
  - `daytrace-session/SKILL.md`
  - `references/classification.md`
  - `references/proposal-json-contract.md`
- tests / fixtures
  - `test_skill_miner_repair.py`
  - `test_skill_miner_proposal.py`
  - `skill_miner_gold.json`

## 4. 分類刷新の難易度感

体感の難易度:

- 設計だけ: 中
- MVP 実装: 中〜高
- しっかり仕上げる: 高

目安:

- 最小 MVP: 1.5〜2.5 日
- carry-forward 整合、fixture 更新、fallback、docs まで含めて仕上げる: 3〜5 日

よって、ハッカソン前の最優先には置かない。

## 5. 分類刷新をやるならどう作るか

推奨形:

1. `prepare` が候補圧縮と triage を行う
2. LLM / subagent が classification overlay JSON を返す
3. Python guardrail が final kind を確定する
4. proposal は final kind を消費して payload を組み立てる

必要なもの:

- `candidate_id`
- `llm_suggested_kind`
- `llm_reason`
- `confidence`
- optional: `why_not_other_kinds`

proposal に残すもの:

- `suggested_kind`
- `suggested_kind_source = heuristic | llm | guardrail_override`
- `classification_trace`

guardrail の役割:

- `hook` にしてはいけない候補を止める
- `CLAUDE.md` に寄せすぎる誤判定を止める
- `agent` の条件不足を止める
- `skill` を安全なフォールバックにする

## 6. テスト方針

LLM 自体は非決定論なので、テスト対象にしない。
テストは guardrail と contract に寄せる。

基本方針:

- LLM 出力は fixture 化する
- guardrail は pure function にする
- proposal 統合は deterministic に検証する

保証したいこと:

- `hook` にしてはいけない候補は `hook` にならない
- malformed な overlay でも fallback する
- `decision_key` / carry-forward が壊れない
- `skill` / `hook` / `agent` ごとの payload 生成が壊れない

## 7. ハッカソン前の実行方針

提出前にやること:

1. `README.md` を仕上げる
2. 共有用レポートの privacy を締める
3. 日報 / post-draft の可読性を上げる

余力があればやること:

4. 分類刷新の実装、または少なくとも contract / 設計の固定

## 8. 一言まとめ

ハッカソン前は、アーキテクチャの理想よりも、審査員が触る体験を優先する。
分類刷新は重要だが重い。README・privacy・可読性の 3 点は、より軽く、より直接評価に効く。
