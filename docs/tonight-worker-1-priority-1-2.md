# Tonight Assignment: Worker 1 (Priority 1-2)

## Mission

今夜の担当は、Priority 4 系 UX のうち **「重さを増やさないための classify 対象絞り込み」** と **「分類ステップを見せすぎないための圧縮」** を進めることです。

狙いは、After 案の信頼性を保ちつつ、初回実行で「遅い・くどい・情報が多い」と感じさせないことです。

## Owned Priorities

- Priority 1: classify 対象を絞る
- Priority 2: proposal / orchestration の見せ方を圧縮する

## Primary Outcome

次の状態を作ってください。

- classify は「曖昧候補だけ」にかかる
- 明らかな heuristic 一致候補は classify をスキップする
- ユーザー向け通常表示では classification の内部事情を見せすぎない
- それでも内部的には `classification_trace` や guardrail 情報を保持できる

## Recommended Scope

優先して触るファイル:

- [daytrace-session/SKILL.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/daytrace-session/SKILL.md)
- [skill-miner/SKILL.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-miner/SKILL.md)
- [classification-prompt.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-miner/references/classification-prompt.md)
- [classification.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-miner/references/classification.md)
- [test_skill_miner_proposal.py](/Users/makotomatuda/projects/lab/daytrace/tests/test_skill_miner_proposal.py)

できれば避けたい競合ファイル:

- [skill_miner_common.py](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/skill_miner_common.py)

もしこのファイルを触る必要がある場合は、**classify 対象の選別や表示圧縮に必要な最小変更だけ**に留めてください。トップ候補強調や carry-forward 表現は Worker 2 側の責務です。

## What To Build

### 1. Classify Target Narrowing

曖昧候補だけを classify に回すためのルールを定義し、必要なら実装してください。

最低限の候補:

- `skill vs agent` が揺れやすい候補
- `skill vs CLAUDE.md` が揺れやすい候補
- heuristic の確信が弱い候補
- `needs_research` から昇格しうる候補

原則 classify しない候補:

- 明らかな `hook`
- 強い `CLAUDE.md` signal を持つ候補
- `rejected`

期待する成果:

- 「なぜこの候補だけ classify するのか」が説明可能
- classify 件数を必要最小限にできる

### 2. Output Compression

通常表示の情報量を減らしてください。

方向性:

- 通常表示では「最終分類」「短い理由」「次の一手」中心
- `classification_trace` と `classification_guardrail_signals` は詳細確認時のみ参照する前提
- daytrace-session 側の判断ログも 1 行で読める密度に寄せる

注意:

- 内部 contract は壊さない
- 情報を削りすぎて説明責任が落ちないようにする

## Acceptance Criteria

- classify の対象ルールが docs 上で明文化されている
- `rejected` を原則 classify しない方針が反映されている
- daytrace-session / skill-miner docs を読めば Phase 4（Pattern Mining）の classify 方針が追える
- proposal の通常体験で classification の内部ノイズが増えない
- 既存テストを壊さない

## Non-Goals

- top candidate の演出強化
- carry-forward の UX 文言改善
- guardrail の大幅改造
- `content_key` 導入

## Suggested Sequence

1. classify 対象の選別ルールを先に文章化
2. daytrace-session の Phase 4 手順へ落とす
3. classification prompt / references を更新
4. 必要最小限のテストだけ追加

## Done Definition

以下を満たしたら完了です。

- classify の適用対象が docs / flow で明確
- 初回 UX を悪化させる「全件 classify / 全部見せる」状態を避けられている
- Worker 2 の proposal 表示改善と競合しにくい差分になっている
