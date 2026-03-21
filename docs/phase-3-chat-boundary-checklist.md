# Phase 3 Checklist: Chat Boundary, Sanitization, and Formatter Foundations

## Goal

フェーズ3の目的は、DayTrace の **chat output を semi-final summary に固定**し、保存 artifact 側へ品質責務を寄せるための境界を固めることです。

このフェーズでは、以下の 3 つを扱います。

- chat output sanitization
- source name normalization
- final formatter contract（機械的変換の基礎）

フェーズ2の `display_label` 導入は別担当で進行中の前提とし、このフェーズでは **chat と file の責務分離** に集中します。

## Scope

### このフェーズで固めること

- chat に出す情報 / 出さない情報の境界
- internal reasoning / shell 実行ログ / 英語内部文の遮断
- source 名の表示マッピング
- final formatter の機械的責務
- mixed-scope / footer / source 要約の適用位置

### このフェーズでまだやらないこと

- `display_label` の導入（別途 Phase 2 / 6 で進行）
- `candidate_label()` の Python 変更
- `decision_key` / `content_key` の再設計
- cross-repo handoff schema v2（**Phase 3 では扱わない** — 実装・チェックリストは `docs/phase-4-cross-repo-handoff-checklist.md` / `cross-repo-handoff.md` で完了）
- report-share / post-draft の語彙 polishing 本体

## Status（実装済み · 2026-03）

- **Chat Output Contract・Source Name Normalization・Mixed-Scope/Footer 配置** を `daytrace-session/SKILL.md`（`## Chat Output Policy`）と `docs/output-polish.md`（§5-5）に実装済み。
- **正本:** `plugins/daytrace/docs/output-polish.md`（chat/file 境界）、`plugins/daytrace/skills/daytrace-session/SKILL.md`（`## Chat Output Policy`・Source 名正規化テーブル）
- **未実装（スコープ外）:** §3 Formatter Contract 全体・§5 Failure/Degrade Policy・source ごとの短い表示名 vs 根拠用表示名の分離（Open Questions 参照）。
- **別トラック完了:** cross-repo handoff（`docs/phase-4-cross-repo-handoff-checklist.md` の Done Definition は満た済み）。TODO の **Phase 4: Formatter Contract** とは別名の論点なので混同しないこと。

## Working Assumptions

- `output-polish.md` を chat/file 分離の正本とする
- `daytrace-session` は chat 側で artifact 本文を全文展開しない
- final artifact は `~/.daytrace/output/YYYY-MM-DD/` に保存済み / 保存可能であることを前提にする
- mixed-scope 注記と再構成元の要約は **chat では必須**
- artifact 本文への mixed-scope 挿入は formatter contract の裁量に寄せる

## Decisions To Lock

### 1. Chat Output Contract

- [x] chat に出すものを固定する
- [x] chat に出さないものを固定する
- [x] internal reasoning を chat に出さないことを明文化する
- [x] shell command / tool trace を chat に出さないことを明文化する
- [x] artifact 本文は chat に全文貼りしない方針を固定する

最低限 chat に出すもの:

- [x] source 収集結果の要約
- [x] DayTrace ダイジェスト
- [x] artifact 生成結果
- [x] artifact 保存先
- [x] proposal の compact 表
- [x] selection prompt
- [x] セッション完了の短い散文要約
- [x] mixed-scope 注記
- [x] 再構成元の要約

chat に出さないもの:

- [x] internal trace
- [x] shell 実行ログ
- [x] reasoning 英文
- [x] 長い根拠一覧
- [x] artifact 本文フルテキスト
- [x] `candidate_id` / `triage_status` などの内部状態語

### 2. Source Name Normalization

- [x] source 表示名の mapping table を決める
- [ ] source ごとの「短い表示名」と「根拠用表示名」を分けるか決める（**保留: SKILL.md ルール運用で問題なし。必要なら Phase 7 で検討**）
- [x] Chrome / Claude / Codex / Git / workspace-file-activity の日本語表現を固定する
- [x] root/path を含む生の source 表示を禁止する

確定済み（`daytrace-session/SKILL.md` Source 名正規化テーブル）:

- [x] `git-history` → `Git の変更履歴`
- [x] `claude-history` → `Claude の会話ログ`
- [x] `codex-history` → `Codex の会話ログ`
- [x] `chrome-history` → `ブラウザの閲覧ログ`
- [x] `workspace-file-activity` → `workspace のファイル作業痕跡`

### 3. Formatter Contract (Mechanical)

**→ 未実装。TODO Phase 4（Formatter Contract）で対応。**

- [ ] Python で行う機械的変換を列挙する
- [ ] LLM / SKILL.md で行う意味変換を列挙する
- [ ] 両者の境界を文書化する

Python 側でやる候補:

- [ ] path sanitize
- [ ] source 名正規化
- [ ] mixed-scope 注記の定型挿入
- [ ] 再構成元フッターの定型生成
- [ ] 禁止語検知
- [ ] internal English leakage の検知
- [ ] 未完全文 / 切れ文の検知

LLM 側でやる候補:

- [ ] 行動レベル語彙への変換
- [ ] 共有用/自分用のトーン調整
- [ ] 背景説明の圧縮
- [ ] 事実/推測の自然な書き分け

### 4. Mixed-Scope and Footer Placement

- [x] mixed-scope 注記を chat に必須とすることを再確認する（`output-polish.md` §5-5）
- [x] artifact 本文で mixed-scope を必須にするか任意にするか決める（任意に決定: §5-5 "必須としない"）
- [x] `再構成元` フッターを chat では要約、artifact では詳細にするか決める（chat: 1–3 行・箇条書き。artifact: 任意。§5-5）
- [ ] 日報と投稿下書きで同じポリシーを使うか分けるか決める（**保留: 現状は同一ポリシー運用。差異が生じたら Phase 7 で分離**）

### 5. Failure / Degrade Policy

**→ 部分対応済み（`degrade_level={full|limited|empty}` trace は導入済み）。UX 文言の確定は TODO Phase 4（Formatter Contract）で対応。**

- [ ] artifact 保存失敗時の chat 表現を決める
- [ ] partial success の表現を決める
- [ ] formatter fail 時に chat summary へフォールバックする条件を決める（**保留: formatter 実装時に決定**）
- [ ] 「保存済み」と「生成済み」の違いを明文化する（**保留: `output-polish.md` Layer 2 の原則は記載済み。具体的な文言は formatter phase で**）

## Proposed Implementation Order

### Step 1: Contract First

- [x] `output-polish.md` に chat/file 境界の不足を追記する
- [x] source name normalization の表を追加する
- [x] internal leakage を明示的に禁止する

### Step 2: Runtime Guard

- [x] `daytrace-session/SKILL.md` に completion check を追加する
- [x] 「英語の内部思考・shell log・internal trace が chat に出ていない」をチェック項目化する
- [x] chat 側で artifact 本文を貼りすぎないようガードする

### Step 3: Formatter Draft

**→ TODO Phase 4（Formatter Contract）に移管。**

- [ ] Python でやる mechanical formatter の仕様を書く
- [ ] 入出力 shape を仮決めする
- [ ] report / post-draft / proposal で共通化できる処理を洗い出す

## Done Definition

以下を満たしたらフェーズ3の論点は固まったとみなす。

- [x] chat output に出すもの / 出さないものが明文化されている
- [x] source 名正規化ルールが 1 か所にまとまっている
- [ ] mechanical formatter と semantic rewrite の責務分離が説明できる（**→ TODO Phase 4 で対応**）
- [x] mixed-scope / footer のルールが決まっている（保存失敗時の UX 文言は TODO Phase 4 で確定）
- [x] cross-repo handoff スレッドは別ドキュメントで完了している（`docs/phase-4-cross-repo-handoff-checklist.md`）。Formatter Contract は **TODO.md の Phase 4** で未対応

## Open Questions

- [x] artifact 本文にも mixed-scope 注記を必須化するか（→ **任意に決定**。output-polish.md §5-5）
- [ ] `report-private` と `report-share` で footer の粒度を変えるか（**保留: 現状は同一ポリシー。Phase 7 で検討**）
- [x] source 名の正規化を Python で強制するか、SKILL.md ルールだけで運用するか（→ **SKILL.md 運用で決着**。Python 強制は formatter 実装時に判断）
- [ ] internal English leakage を lint 的に検知するか、formatter 時に落とすか（**保留: TODO Phase 4 で判断**）
