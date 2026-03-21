# Tonight Assignment: Worker 2 (Priority 3-4) — Revised

## Mission

Priority 3-4 を再定義し、「微妙な候補をゴリ押しする」罠を避けつつ、proposal の UX を最大化する。

狙いは、ユーザーが候補を見た瞬間に「これは何ができるようになるのか」「今採用すべきか」を迷わず判断できる状態を作ること。

## 元プランとの差分

### Priority 3: 「上位1件を強く推す」→「Kind-aware display + confidence-gated recommendation」

元の問題: ランキングの質が低いまま 1 位を派手にするだけでは、微妙な候補を強く推すだけのしょーもない UX になる。

新しいゴール: confidence tier と kind に応じた表示差別化で、ユーザーが根拠に基づいて判断できる状態を作る。

### Priority 4: 「carry-forward one-liner」→「Hook/agent apply path」

元の問題: carry-forward の一文は独立項目としては UX インパクトが弱い。それより hook/agent 候補が「提案されても行き止まり」な方が深刻。carry-forward delta は confidence display に統合する。

新しいゴール: hook/agent 候補も skill と同等の「adopt → 生成」パスを持つ。

## Owned Priorities

- Priority 3: Kind-aware display + confidence-gated recommendation
- Priority 4: Hook/agent guided creation path

## Primary Outcome

次の状態を作ってください。

- proposal の各候補が「何ができるようになるか」が kind-specific な言葉で伝わる
- confidence が高い候補ほど目立ち、弱い候補は正直に「まだ判断材料が少ない」と伝える
- ready 候補が根拠の強さ順にソートされている
- hook/agent 候補が提案で行き止まりにならず、skill-applier で実際に生成できる
- carry-forward delta は独立項目ではなく confidence 表示の一部として組み込まれている

## Recommended Scope

優先して触るファイル:

- [skill_miner_common.py](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/skill_miner_common.py)
- [test_skill_miner_proposal.py](/Users/makotomatuda/projects/lab/daytrace/tests/test_skill_miner_proposal.py)
- [skill-applier/SKILL.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-applier/SKILL.md)
- [hook-agent-nextstep.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-applier/references/hook-agent-nextstep.md)

新規作成:

- [hook-creation-guide.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-applier/references/hook-creation-guide.md)
- [agent-creation-guide.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-applier/references/agent-creation-guide.md)

できれば触らないファイル:

- [daytrace-session/SKILL.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/daytrace-session/SKILL.md)
- [classification-prompt.md](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/skills/skill-miner/references/classification-prompt.md)

## What To Build

### 3. Kind-aware display + confidence-gated recommendation

#### 3a. Ready 候補のソート

`build_proposal_sections()` で ready リスト構築後、markdown 生成前にソートする。

- ソートキー: confidence (strong=0 > medium=1 > weak=2) → total_packets 降順
- 1 番目に来る候補が実際に最も根拠がある状態にする

#### 3b. セクションヘッダ変更

- `"## 提案（固定化を推奨）"` → `"## 提案（アクション候補）"`

#### 3c. Kind-specific な表現に置き換え

「固定先: skill」のような内部用語を、ユーザーにとっての意味に変換する:

| suggested_kind | 旧表示 | 新表示 |
|---------------|--------|--------|
| `CLAUDE.md` | 固定先: CLAUDE.md | 種類: プロジェクト設定（CLAUDE.md） |
| `skill` | 固定先: skill | 種類: 再利用スキル |
| `hook` | 固定先: hook | 種類: 自動チェック（hook） |
| `agent` | 固定先: agent | 種類: 専用エージェント |

「期待効果」「この作法を固定すれば」を kind ごとの具体的なアクション説明に変える:

| suggested_kind | アクション説明 |
|---------------|--------------|
| `CLAUDE.md` | → プロジェクト設定に追加すれば、毎回の指示が不要になります |
| `skill` | → /skill-creator で再利用コマンドとして保存できます |
| `hook` | → 自動チェックとして設定できます |
| `agent` | → 専用エージェントとして作成できます |

#### 3d. Carry-forward delta の統合

- `prior_decision_state` がある場合、確度行に「（前回比 +N 観測）」を付加
- 独立した priority にせず、confidence display の一部として扱う

#### 3e. next_step_stub のプロンプト更新

hook/agent の `next_step_stub.prompt` を「次セッションで指示」から即時アクション可能な表現に変更:

- hook: `「{label} を hook として設定しますか？」`
- agent: `「{label} をエージェントとして作成しますか？」`

### 4. Hook/agent guided creation path

#### 4a. Reference ドキュメント追加

skill-applier の `references/` に Claude Code の正式フォーマット仕様を追加:

- `hook-creation-guide.md` — settings.json の hooks 構造、イベント種別、matcher、command/prompt hook の書き方
- `agent-creation-guide.md` — agents/ ディレクトリの .md ファイル構造、YAML フロントマター、システムプロンプト

#### 4b. hook-agent-nextstep.md の更新

- 「設計案の提示のみ」→「ユーザー承認後、実際に生成する」に変更
- hook: next_step_stub の情報を元に settings.json に hook 定義を書き込む手順
- agent: next_step_stub の情報を元に agents/ に .md ファイルを生成する手順

#### 4c. skill-applier SKILL.md の更新

dispatch table を変更:

| suggested_kind | 旧 | 新 |
|---------------|----|----|
| `hook` | Design Proposal → 次セッション | Guided Creation → 承認後 settings.json に生成 |
| `agent` | Design Proposal → 次セッション | Guided Creation → 承認後 agents/ に生成 |

## Acceptance Criteria

- ready 候補が confidence → total_packets でソートされている
- proposal に「固定化」「固定先」という内部用語が出ない
- kind ごとに「ユーザーにとって何が起きるか」が明確に伝わる
- confidence が strong の候補だけが目立ち、weak は正直な表示
- hook/agent 候補に skill-applier 経由の生成パスがある
- hook-creation-guide.md, agent-creation-guide.md が正確な Claude Code フォーマット仕様を含む
- 既存テストを壊さず、新しい表示ロジックに対するテストがある

## Non-Goals

- classify 対象の選別（Worker 1）
- classification prompt の改善（Worker 1）
- subagent orchestration
- hook/agent の自動テスト実行

## Suggested Sequence

1. skill_miner_common.py の display 変更（ソート、ヘッダ、kind-specific 表現）
2. テスト更新 + golden fixture 再生成
3. skill-applier reference docs 作成（hook-creation-guide, agent-creation-guide）
4. hook-agent-nextstep.md + SKILL.md 更新
5. 全テスト pass 確認

## Done Definition

以下を満たしたら完了です。

- proposal を読んだユーザーが「固定化」という概念を知らなくても、各候補で何ができるか分かる
- confidence が高い候補が先に来て、根拠の強さが表示から読み取れる
- hook/agent 候補を adopt したとき、skill-applier が実際に生成まで導く
- Worker 1 の classify 方針変更と競合しにくい差分になっている
