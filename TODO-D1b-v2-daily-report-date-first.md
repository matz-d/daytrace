# TODO D1b. daily-report v2 / Date-First Rewrite

Phase: Output Skills
Depends on: C2（`aggregate.py` の `scope` 契約が見えていること。文章更新は先行可）

## Goal

`daily-report` を `workspace default` から `date-first default` へ再定義し、`自分用 / 共有用` の 2 モードと mixed-scope 注記を含む SKILL.md に更新する。

この TODO は「無質問化」ではなく、「mode が取れない時だけ入口で 1 回聞き、途中では止まらない」UX を作る。

## Non Goals

- `aggregate.py` 本体のスコープ実装
- README の全体 product copy 更新
- `post-draft` の narrative 仕様

## Start Here

最初に以下を読む。

- `PLAN_update.v2.md` の `Input Surface Contract`
- `PLAN_update.v2.md` の `daily-report` セクション
- `plugins/daytrace/skills/daily-report/SKILL.md`
- `plugins/daytrace/scripts/aggregate.py`
- `plugins/daytrace/scripts/README.md`

## Checklist

- [x] `plugins/daytrace/skills/daily-report/SKILL.md` の description / Goal / Inputs を v2.3 に合わせて書き換える
- [x] 対象スコープを `date-first default + optional workspace filter` として明記する
- [x] `自分用 / 共有用` の差分を SKILL.md 内で明確に定義する
- [x] mode が自然言語から抽出できた場合は ask しないことを明記する
- [x] mode が抽出できなかった場合だけ、最初の 1 ターンで 1 問 ask することを明記する
- [x] 途中で追加 ask しないことを明記する
- [x] low confidence を `確認したい点` セクションではなく本文内注記で扱うように変更する
- [x] mixed-scope 注記ルールを追加する
  - 全日 source と workspace source が混在すること
  - `scope` フィールドを見て注記文を組み立てること
- [x] graceful degrade の空日報 / 簡易日報ルールを現行より後退させない
- [x] sample output を `自分用` / `共有用` の 2 本に更新する

## Target Files

- `plugins/daytrace/skills/daily-report/SKILL.md`

## Suggested Execution Order

1. Goal / Inputs / mode 契約を書き換える
2. Output Rules を `自分用 / 共有用` の 2 モードへ分ける
3. Confidence Handling を注記運用へ更新する
4. mixed-scope 注記ルールを足す
5. sample output を差し替える

## Verification

- [x] `SKILL.md` だけ読んで、context のない実装者が mode の挙動を説明できる
- [x] `自分用` と `共有用` の差が構成・語彙・未完了の扱いまで見える
- [x] `確認したい点` 依存の旧フローが残っていない
- [x] mixed-scope の注記ルールが文中で一意に読める

## Done Criteria

- [x] `daily-report` が date-first skill として一貫して説明される
- [x] 入口 ask の条件が明文化されている
- [x] 低 confidence の扱いが v2.3 契約に揃っている
- [x] 2 モード分の sample output がある
