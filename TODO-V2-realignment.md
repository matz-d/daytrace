# TODO V2.3 Product Realignment

Phase: Output Skills / Polish
Depends on: `PLAN_update.v2.md` v2.3 が最新であること

## Goal

`PLAN_update.v2.md` v2.3 を、コンテキストのない実装者でもすぐ着手できる並列 TODO 群に分解する。

この TODO は実装本体ではなく、並列トラックの交通整理を担当する。

## Parallel Work Map

```text
Track 0: contract source of truth
  - PLAN_update.v2.md v2.3

Track 1: aggregate scope metadata
  - TODO-C2-v2-aggregate-scope-mode.md

Track 2: daily-report v2 rewrite
  - TODO-D1b-v2-daily-report-date-first.md

Track 3: post-draft v2 rewrite
  - TODO-D3b-v2-post-draft-narrative.md

Track 4: skill-miner adaptive window
  - TODO-D2d-skill-miner-adaptive-window.md

Track 5: README / demo alignment
  - TODO-E2b-v2-readme-demo-realignment.md
```

## Dependency Rules

- Track 1, 2, 3 は並列着手可
- Track 2 と Track 3 は `PLAN_update.v2.md` を仕様として進め、`aggregate.py` の `scope` フィールドは stub 前提で先に文章を書いてよい
- Track 4 は既存 `skill-miner` v2 系 TODO の後続。`TODO-D2c-skill-miner-v2.md` の完了前提で進める
- Track 5 は Track 1-4 の出力が見えた段階で着手する

## Task List

- [ ] `TODO-C2-v2-aggregate-scope-mode.md` を起票して実装する
- [ ] `TODO-D1b-v2-daily-report-date-first.md` を起票して実装する
- [ ] `TODO-D3b-v2-post-draft-narrative.md` を起票して実装する
- [ ] `TODO-D2d-skill-miner-adaptive-window.md` を起票して実装する
- [ ] `TODO-E2b-v2-readme-demo-realignment.md` を起票して実装する

## Done Criteria

- [ ] v2.3 の変更点が 5 本の TODO に分解されている
- [ ] 各 TODO が「対象ファイル」「非対象」「検証方法」を持つ
- [ ] 並列着手可能なものと依存が明記されている
