---
name: daytrace-session
description: >
  「今日の振り返りをお願い」の一言で、ローカルログの収集・日報生成・反復パターン提案・投稿下書きまで
  自律的に完走する統合セッション。振り返りをまとめて、全部やって、1日のまとめ、と言われた時に使う。
user-invocable: true
---

# DayTrace Session

1 回の依頼で「収集 → 日報 → パターン提案 → 追加調査 → 投稿下書き」まで自律的に完走するオーケストレーション skill。

## Goal

- 1 回の依頼で全フェーズを追加指示なしで完走する
- 各ステップで自己判断の理由を `[DayTrace]` プレフィックス付きで報告する
- ソース欠損やデータ不足でも止まらず、できる範囲で最後まで進む
- 最後に実施内容のサマリを返す

やらないこと:

- 個別 skill の出力フォーマットや品質基準を上書きすること
- 途中で追加 ask すること
- フェーズ間で人の確認を待つこと（CLAUDE.md diff preview を除く）

## Inputs

- 対象日: 指定がなければ `today`
- workspace: 任意。補助フィルタ
- mode: `自分用` or `共有用`。未指定なら `自分用` + 条件付き共有用自動生成

## Entry Contract

- ask は 0 回に固定する
- 「今日の振り返りをお願い」「1日のまとめ」「全部やっておいて」「今日の活動を整理して」などから日付を抽出する
- mode / workspace / topic / reader は自然言語から抽出できればそれを使い、取れなければデフォルト
- 途中で追加 ask しない

## Scripts

スクリプトはこの `SKILL.md` と同じ plugin 内の `scripts/` にある。
このディレクトリから `../..` を辿った先を `<plugin-root>` として扱う。

Phase 1 Data Collection:

```bash
python3 <plugin-root>/scripts/daily_report_projection.py --date today --all-sessions
```

Phase 3 Pattern Mining:

```bash
python3 <plugin-root>/scripts/skill_miner_prepare.py --input-source auto --store-path ~/.daytrace/daytrace.sqlite3 --all-sessions
```

Phase 3 Detail (conditional):

```bash
python3 <plugin-root>/scripts/skill_miner_detail.py --refs "<ref1>" "<ref2>"
```

Phase 3 Judge (conditional):

```bash
python3 <plugin-root>/scripts/skill_miner_research_judge.py --candidate-file /tmp/prepare.json --candidate-id "<id>" --detail-file /tmp/detail.json
```

Phase 3 Proposal:

```bash
python3 <plugin-root>/scripts/skill_miner_proposal.py --prepare-file /tmp/prepare.json --judge-file /tmp/judge.json
```

Phase 4 Post Draft (conditional):

```bash
python3 <plugin-root>/scripts/post_draft_projection.py --date today --all-sessions
```

workspace 指定がある場合は全コマンドに `--workspace /absolute/path` を追加する。

## Execution Flow

5 つのフェーズを順に実行する。各フェーズで判断ログを出力し、追加指示なしで次に進む。

### Phase 1: Source Assessment

1. `daily_report_projection.py` を 1 回実行する
2. `sources[]` を読み、各ソースの `status` と `scope` を確認する
3. 判断ログを出力する:

```
[DayTrace] ログを収集しました
  git-history (12 events) — workspace scope
  claude-history (8 events) — all-day scope
  chrome-history → 権限不足のためスキップ
  codex-history (3 events) — all-day scope
  workspace-file-activity (24 events) — workspace scope
  → 4 ソースで続行します
```

4. 判断ルール:
   - `summary.source_status_counts.success >= 1` → 続行
   - `success == 0` → 空日報を出して Phase 5 へ飛ぶ

### Phase 1.5: DayTrace ダイジェスト

Phase 1 完了直後、Phase 2 に入る前に「今日の DayTrace ダイジェスト」を 3-5 行の散文で出す。
これは全フェーズの結果を先読みするものではなく、ログから読み取れる 1 日の概観を先に見せるためのもの。

```
## 今日の DayTrace ダイジェスト
今日は N 件のソースから X 件の活動を観測しました。
{主な活動の 1-2 文要約}。
パターン候補と投稿下書きの結果はこの後に続きます。
```

### Phase 2: Daily Report

1. Phase 1 の中間 JSON を使って日報を生成する
2. 出力ルールは `daily-report` skill の SKILL.md に従う
3. mode が明示されている場合はその mode で生成する
4. 自動判断 — 共有用の追加生成:
   - 条件: mode 未指定かつ `summary.total_groups >= 5`
   - 満たす場合: `自分用` に加えて `共有用` も自動生成する
   - 満たさない場合: `自分用` のみ
5. 判断ログは 1 行に圧縮する:

```
[DayTrace] 日報を生成しました（自分用 + 共有用）
```

または:

```
[DayTrace] 日報を生成しました（自分用のみ、グループ 3 件）
```

### Phase 3: Pattern Mining & Proposals

1. `skill_miner_prepare.py` を 1 回実行する
2. `candidates[]` を確認する
3. 自動判断 — 追加調査:
   - 条件: `needs_research` 候補が 1 件以上
   - 満たす場合: 各 `needs_research` 候補の `research_targets` 上位 refs で `skill_miner_detail.py` → `skill_miner_research_judge.py` を自動実行する
   - 1 候補あたり最大 5 refs、追加調査は 1 回まで
4. 分類判定（LLM が担当）:
   - `ready` および昇格した候補それぞれに `suggested_kind` を付与する
   - 分類ルールは `skills/skill-miner/SKILL.md` の Classification Rules に従う
   - 値は `CLAUDE.md` / `skill` / `hook` / `agent` のいずれか
   - 分類結果を候補 dict に書き込んでから次のステップに渡す
5. 提案の組み立て:
   - 分類済みの候補を含む prepare 出力と judge 出力（あれば）を `skill_miner_proposal.py` に渡して最終 proposal を生成する
   - `proposal.py` が返す `markdown` フィールドをそのまま出力する
   - `ready` が 0 件の場合: 0 件時テンプレート（skill-miner SKILL.md 参照）に従い、検出候補数・見送り理由・再実行の目安を出す
6. 自動判断 — CLAUDE.md 適用候補:
   - 条件: `ready` 候補の中に `suggested_kind == "CLAUDE.md"` が 1 件以上
   - 満たす場合: `skill-miner` skill の Immediate Apply Spec に従い diff preview を表示する
   - CLAUDE.md diff preview への反応だけは、ユーザーの確認を待ってよい（唯一の例外）
7. 判断ログは 1 行に圧縮する:

```
[DayTrace] パターン検出: 候補 6 件中 2 件を提案、1 件は有望候補、追加調査 1 件実施済み
```

0 件の場合:

```
[DayTrace] パターン検出: 候補 N 件を検出したが、提案条件を満たす候補なし（観測窓 7 日）
```

### Phase 4: Post Draft (conditional)

1. 自動判断 — 投稿下書きの生成:
   - 条件（いずれか 1 つ以上）:
     - Phase 1 の `sources` に `git-history` と (`claude-history` or `codex-history`) が両方 success
     - `summary.total_groups >= 4`
   - 満たす場合:
     - `post_draft_projection.py` を 1 回実行する
     - `post-draft` skill の SKILL.md に従って narrative draft を生成する
   - 満たさない場合: スキップ
2. 判断ログは 1 行に圧縮する:

```
[DayTrace] 投稿下書きを生成しました（AI + Git 共起パターンをもとに構成）
```

スキップ時:

```
[DayTrace] 投稿下書き: 生成条件を満たさないためスキップ (groups: 2, AI+Git 共起: なし)
```

### Phase 5: Session Summary

最後に全フェーズの実施結果を 3-5 行の散文でまとめる。チェックリストではなく、DayTrace がこのセッションで何をしたかの要約として書く。

```
[DayTrace] セッション完了
今日は N 件のソースから日報を生成し、パターン候補 X 件のうち Y 件を提案しました。
CLAUDE.md への適用候補が 1 件あり、diff preview を表示済みです。
投稿下書きは AI + Git の共起パターンをもとに 1 本生成しています。
```

## Output Order

各フェーズの出力は以下の順序で連続して出力する。

1. Phase 1 の判断ログ（ソース判定の詳細。自律性を見せる最重要ポイントなので圧縮しない）
2. Phase 1.5 の DayTrace ダイジェスト（3-5 行の散文で 1 日の概観を先に見せる）
3. Phase 2 の判断ログ（1 行）+ 日報出力（`daily-report` SKILL.md の Output Rules に準拠）
4. Phase 2 の共有用日報（条件付き）
5. Phase 3 の判断ログ（1 行）+ 提案出力（`skill-miner` SKILL.md の Proposal Format に準拠）
6. Phase 3 の CLAUDE.md diff preview（条件付き）
7. Phase 4 の判断ログ（1 行）+ 下書き出力（`post-draft` SKILL.md の Output Rules に準拠）
8. Phase 5 のセッションサマリ（散文）

判断ログは `[DayTrace]` プレフィックスで統一する。
Phase 1 のログだけ詳細に出し、Phase 2-4 のログは 1 行に圧縮する。
日報・提案・下書きの本文はそのまま読めるように、判断ログと明確に区切る。

## Sub-Skill Reference

各フェーズの出力ルールは個別 skill の SKILL.md を参照する。

- Phase 2: `skills/daily-report/SKILL.md` — Output Rules, Confidence Handling, Mixed-Scope Note Rules, Graceful Degrade
- Phase 3: `skills/skill-miner/SKILL.md` — Classification Rules, Proposal Format, Deep Research Rules, CLAUDE.md Immediate Apply Spec, Triage Rules
- Phase 4: `skills/post-draft/SKILL.md` — Narrative Policy, Reader Policy, Output Rules, Graceful Degrade

本 skill は orchestration のみを担い、個別 skill の出力フォーマットや品質基準を上書きしない。

## Error Handling

- Phase 1 で全ソース失敗 → 空日報を出して Phase 5 へ
- Phase 3 の prepare 実行失敗 → エラーを判断ログに記録し、Phase 4 へ進む
- Phase 3 の detail/judge 実行失敗 → 当該候補を `needs_research` のまま残し、次の候補または Phase 4 へ
- Phase 4 の projection 実行失敗 → エラーを判断ログに記録し、Phase 5 へ進む
- いずれのフェーズ失敗もセッション全体を中断しない

判断ログ例:

```
[DayTrace] パターン検出でエラーが発生しました: skill_miner_prepare.py timeout → スキップして投稿下書きへ進みます
```

## Decision Rules Summary

| 判断ポイント | 条件 | Yes | No |
|-------------|------|-----|-----|
| 続行 vs 停止 | success >= 1 | 続行 | 空日報 → Phase 5 |
| 共有用追加 | mode 未指定 & total_groups >= 5 | 両方生成 | 自分用のみ |
| 追加調査実行 | needs_research >= 1 | detail + judge 自動実行 | スキップ |
| 分類判定 | ready 候補 >= 1 | LLM が suggested_kind を付与 | スキップ |
| CLAUDE.md diff | ready に suggested_kind == "CLAUDE.md" | diff preview 表示 | スキップ |
| 投稿下書き | AI + Git 共起 or groups >= 4 | 生成 | スキップ |

## Completion Check

以下を満たすまでセッションを完了としない。

- 1 回の依頼で Phase 1 〜 5 が追加 ask なしで完走している
- 各判断ポイントで `[DayTrace]` 付きの判断ログが出力されている
- ソース欠損があっても Phase 5 まで到達している
- 個別 skill の出力品質基準が維持されている
- Phase 5 でセッション全体のサマリが出ている
- 判断をスキップした場合もその理由が記録されている
