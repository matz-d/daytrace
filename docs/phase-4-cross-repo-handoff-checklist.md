# Phase 4 Checklist: Cross-Repo Handoff and Target Repo UX

## Goal

フェーズ4の目的は、**別リポジトリ向け候補を current repo 向け候補と混同させないこと**です。

今回の実例では、DayTrace が別 repo 向けの skill 候補を出したにもかかわらず、

- handoff JSON に target repo 情報がない
- `[WORKSPACE]` しか見えない
- current CWD で `/skill-creator` を実行してしまう

という UX 事故が起きました。

## Status（実装済み · 2026-03）

- **検出・schema v2・proposal 表示・presentation_block・dedup（`handoff-{candidate_id}.json` latest-wins）** を `skill_miner_common.py` / `skill_miner_prepare.py` / `skill_miner_proposal.py` に実装済み。
- **仕様の正本:** `plugins/daytrace/skills/skill-miner/references/cross-repo-handoff.md`
- **未実装（スコープ外）:** selection prompt の current/other 差分、artifact の実ファイル存在チェックによる cross-repo 強制、`target_workspace_hint` の匿名化のみ方針の固定（Open Questions 参照）。

`Decisions To Lock` のチェックボックスは **実装ベースで同期**している。`[ ]` は未実装または Phase 6 / Open Questions に残す論点。

このフェーズでは、以下を固めます。

- cross-repo candidate detection
- handoff schema v2
- proposal / compact 表での見せ方
- current repo ではなく target repo で実行する導線
- handoff file の提示形式
- handoff 重複書き込みの扱い

## Scope

### このフェーズで固めること

- `cross_repo` を first-class な状態として扱う
- `target_workspace_hint` を handoff に持たせる
- proposal 画面で「これは別 repo 向け」と分かるようにする
- handoff を **path だけでなく、target repo + 実行手順つき**で出す
- current CWD と target repo の違いを明示する

### このフェーズでまだやらないこと

- `display_label` 自体の設計
- formatter の一般論
- `decision_key` / `content_key` 再設計
- 複数選択 UX

## Working Assumptions

- current CWD は検出できる
- session refs / workspace signal / evidence path から target repo のヒントは取れる可能性がある
- `skill-creator` は **対象 repo を開いた状態で実行する**のが正しい
- `[WORKSPACE]` プレースホルダーだけでは UX が弱い

## Decisions To Lock

### 1. Cross-Repo Detection Contract

- [x] `cross_repo` を bool で持つ
- [x] current CWD と target workspace の比較で cross-repo を判定する（`config.workspace` と `dominant_workspace` / `workspace_paths`）
- [x] 判定 signal を列挙する（`detection_signals`・正本は `cross-repo-handoff.md` の表）
- [x] confidence を持たせるか決める（**`cross_repo_confidence`（high/medium/low）を採用**。guardrail 分岐には使わず UX 注記用）

候補 signal（実装に対応するものは `[x]`）:

- [x] candidate の workspace 系（`dominant_workspace` / `workspace_paths`）に観測時 `--workspace` 外のパスがある → `packet_workspace_outside_config_workspace` 等
- [x] `dominant_workspace`（解決パス）≠ `config.workspace`（解決パス）→ `dominant_workspace_mismatch`
- [ ] anonymized path pattern が current repo の構造と一致しない（**未採用**）
- [ ] current repo に対象ファイル群が存在するかの **実ファイル実在チェック**（**未実装**。Open Questions）

### 2. Handoff Schema v2

- [x] handoff JSON に `cross_repo` を追加する
- [x] `target_workspace_hint` を追加する
- [x] `current_workspace` を追加する
- [x] `handoff_scope` を追加する
- [x] `execution_instruction` を追加する
- [x] `workspace_resolution_note` を追加する
- [x] `target_repo_display_name` を追加する
- [x] `target_path_examples` を追加する
- [x] `presentation_block` / `handoff_schema_version` / `cross_repo_confidence` / `detection_signals`（正本: `cross-repo-handoff.md`）

最低限入れたい shape:

- [x] `cross_repo: true | false`
- [x] `target_workspace_hint: string | null`
- [x] `current_workspace: string | null`
- [x] `handoff_scope: current_repo | other_repo`
- [x] `execution_instruction: string`
- [x] `workspace_resolution_note: string`

### 3. Proposal / Compact 表の表示

- [x] proposal 上で current repo 候補と cross-repo 候補を見分けられるようにする（`適用先:` + `workspace 注記:`）
- [x] compact 表・詳細 proposal 用の文言（golden / `build_proposal_sections` と整合）
- [x] 詳細版 proposal.md で補足する文言を決める
- [ ] selection prompt にも current repo / other repo の差を反映するか決める（**未実装 → Phase 6**）

叩き台（proposal 本文で使用）:

- [x] `適用先: 現在のリポジトリ`
- [x] `適用先: 別リポジトリ（…）`（表示名・ヒント付き）
- [x] `workspace 注記:` に `workspace_resolution_note`（別表現で「CWD と違う旨」は cross-repo 時に含まれる）

### 4. Handoff Presentation UX

ここが今回の追加論点です。**handoff のパスだけを出すのではなく、target repo と実行手順をセットで出す**ことを前提にします。

- [x] 永続 bundle に `presentation_block`（fenced）を持たせる
- [x] path 単体ではなく `target repo 目安 + 実行手順（`execution_instruction`）+ 永続後の handoff 参照` のセット（`presentation_block` / merge ロジック）
- [x] cross-repo 時は「現在の CWD だけを信頼しない」旨を `execution_instruction` に含める
- [x] `/skill-creator` は対象リポジトリを開いた状態で、と明示

推奨テンプレート（`execution_instruction` / bundle 構造で反映）:

- [x] 別 repo 向けであること・開き方の段階（番号付き）
- [x] `target_workspace_hint` / `target_repo_display_name` を出せる形
- [x] handoff file（`context_file`）は永続**後**に `presentation_block` に埋め込み

推奨表示イメージ:

```text
この候補は別リポジトリ向けです。現在の CWD ではなく、対象リポジトリを開いてから適用してください。

target repo: /absolute/path/to/other-repo
handoff file: /Users/.../.daytrace/skill-creator-handoffs/xxx.json

実行すること:
1. 対象リポジトリを開く
2. handoff file を参照して /skill-creator を実行する
```

コマンド例（**常に出すかは未決** — Open Questions）:

- [ ] `cd /absolute/path/to/other-repo` を **常に**出す（`execution_instruction` は推奨パスを文面に含めるが、シェル一行を固定テンプレにしているわけではない）
- [x] handoff file 参照 + `/skill-creator` の流れは `execution_instruction` に含まれる

### 5. Current Repo vs Target Repo Check

- [ ] current CWD に対象ファイルが存在するかを **実装で**確認する（**未実装**）
- [ ] 存在しない場合は cross-repo 強シグナルとして扱う（**未実装**）
- [x] workspace ログ由来のヒントで current / other を切り替える（`build_cross_repo_handoff_metadata` のルール）

判断ルール（実装済みは `[x]`）:

- [x] `dominant_workspace` と `config.workspace` が一致し packets が範囲内 → 通常は current_repo 寄り
- [x] 別 workspace のパスが混ざる / dominant が違う → `other_repo`
- [x] `--workspace` 未設定など曖昧な場合は保守的な `workspace_resolution_note`（完全な unavailable 固定文字列ではなく注記で表現）

### 6. Handoff Persistence and Dedup

- [x] 同一 candidate の handoff 重複書き込みを検討する → **latest-wins 上書きで解決**
- [x] dedup key を決める → **ファイル名 `handoff-{candidate_id_slug}.json`（candidate 単位）**
- [x] latest-wins にするか append-only にするか決める → **latest-wins（同一 `candidate_id` で上書き）**
- [x] schema v2 への切り替え時に既存 handoff とどう共存するか決める（**v1 は読み手が無視可能・新規は v2 のみ** — `cross-repo-handoff.md`「後方互換」）

当初の推奨（`content_key` 近傍）:

- [ ] `content_key + suggested_kind + target_workspace_hint` での strict dedup（**未採用**。実装は **candidate_id ベースの latest-wins** に寄せた）
- [x] append-only は採用しない（監査用途が必要なら別設計）

## Implementation Order

### Step 1: Detection Rule

- [x] cross-repo 判定条件を文章化する（`cross-repo-handoff.md`）
- [x] current repo / other repo の判断材料を列挙する（コード + 上記ドキュメント）

### Step 2: Schema v2

- [x] handoff JSON の追加フィールドを決める
- [x] backward compatibility 方針を決める

### Step 3: UX Copy

- [x] proposal 上の表示文言を決める
- [x] handoff 表示テンプレートを決める（`execution_instruction` / `presentation_block`）
- [x] fenced / コードブロック形式の提示文を決める（`presentation_block`）

### Step 4: Persistence

- [x] dedup ルールを決める（latest-by-candidate）
- [x] handoff 再生成時の上書き / 更新ルールを決める

## Done Definition

- [x] cross-repo 候補を proposal 上で見分けられる
- [x] handoff JSON だけ見て「どの repo で何をすべきか」が分かる
- [x] path 単体ではなく、target repo と実行手順つきで handoff できる
- [x] current repo で誤って `/skill-creator` を実行しにくくなっている
- [x] handoff の重複生成ルールが決まっている

## Open Questions

- [ ] `target_workspace_hint` に実パスを持たせるか、匿名化ヒントに留めるか（**現状の実装: 解決済み絶対パスを格納**。匿名化のみに寄せるかは未固定）
- [ ] current CWD から target repo へ直接 `cd` 可能なコマンドを常に出してよいか
- [ ] cross-repo 候補を選択 prompt の段階で明示するか、選択後に明示するか（**現状: proposal 本文では明示。selection prompt は Phase 6**）
- [x] handoff dedup は strict key にするか latest-by-candidate にするか → **決定: latest-by-candidate（`handoff-{candidate_id_slug}.json` 上書き）**
