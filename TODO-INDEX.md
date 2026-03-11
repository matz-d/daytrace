# DayTrace TODO Index

並列トラックごとの TODO 一覧。

## Phase 1: Foundation（3/10 - 3/13）

- [TODO-A-packaging.md](TODO-A-packaging.md)
- [TODO-B1-git-history.md](TODO-B1-git-history.md)
- [TODO-B2-claude-history.md](TODO-B2-claude-history.md)
- [TODO-B3-codex-history.md](TODO-B3-codex-history.md)
- [TODO-B4-chrome-history.md](TODO-B4-chrome-history.md)
- [TODO-B5-workspace-file-activity.md](TODO-B5-workspace-file-activity.md)
- [TODO-C-aggregator.md](TODO-C-aggregator.md)

## Phase 2: Output Skills（3/14 - 3/18）

- [TODO-D1-daily-report.md](TODO-D1-daily-report.md)
- [TODO-D1b-v2-daily-report-date-first.md](TODO-D1b-v2-daily-report-date-first.md)
- [TODO-D2-skill-miner.md](TODO-D2-skill-miner.md)
- [TODO-D2a-skill-miner-compression.md](TODO-D2a-skill-miner-compression.md)
- [TODO-D2b-skill-miner-proposal-quality.md](TODO-D2b-skill-miner-proposal-quality.md)
- [TODO-D2c-skill-miner-v2.md](TODO-D2c-skill-miner-v2.md)
- [TODO-D2d-skill-miner-adaptive-window.md](TODO-D2d-skill-miner-adaptive-window.md)
- [TODO-D3-post-draft.md](TODO-D3-post-draft.md)
- [TODO-D3b-v2-post-draft-narrative.md](TODO-D3b-v2-post-draft-narrative.md)

## Phase 3: Polish & Submit（3/19 - 3/22）

- [TODO-E1-judge-install.md](TODO-E1-judge-install.md)
- [TODO-E2-readme-demo.md](TODO-E2-readme-demo.md)
- [TODO-E2b-v2-readme-demo-realignment.md](TODO-E2b-v2-readme-demo-realignment.md)
- [TODO-E3-hardening.md](TODO-E3-hardening.md)

## Phase 2.5: v2.3 Realignment Control

- [TODO-V2-realignment.md](TODO-V2-realignment.md)
- [TODO-C2-v2-aggregate-scope-mode.md](TODO-C2-v2-aggregate-scope-mode.md)

## 依存関係

```
C の最初の 1 項目（共通契約の確定 + sources.json）
  → B1-B5（各 source CLI はこの契約に従う）
  → C の残り（aggregator 本体）
  → D1, D3（aggregator の中間 JSON を使う）

B2, B3（claude/codex CLI）
  → D2（skill-miner は B2, B3 を直接使う。aggregator は経由しない）

D2
  → D2a（skill-miner compression refactor は現行 skill-miner の上に載せる）

D2a
  → D2b（proposal quality / UX recovery は compression 導入後の改善）

D2b
  → D2c（weekly classification / evidence chain / CLAUDE.md apply / B0-Validation の再整理）

C
  → C2（scope metadata を追加し、v2.3 の mixed-scope contract を機械可読にする）

C2
  → D1b, D3b（daily-report / post-draft は `scope` を前提に書き換える）

D2c
  → D2d（adaptive window は skill-miner v2 契約の後続）

C2, D1b, D3b, D2d
  → E2b（README / demo の最終整合）

A（packaging）は他と並行して進められる

E3（hardening）→ E1（judge install）→ E2（README / demo 最終化）
```

## 運用ルール

- 実装者は着手・完了した項目を都度チェックする
- 管理者は各ファイルのチェック状況を見て進捗確認する
- 順番固定ではなく、並列トラックごとに前進させる
- 依存がある場合でも、インターフェース確定・stub 実装・テスト作成は先行してよい
