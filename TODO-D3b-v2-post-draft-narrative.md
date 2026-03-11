# TODO D3b. post-draft v2 / Narrative Rewrite

Phase: Output Skills
Depends on: C2（mixed-scope 契約が見えていること。SKILL.md 更新は先行可）

## Goal

`post-draft` を「3 用途の出力 skill」から「date-first の narrative draft skill」へ再定義し、0 ask・reader/topic override・fixture review 前提の運用へ更新する。

主題選定は Python helper に切り出さず、`SKILL.md` の narrative policy として実装する。

## Non Goals

- 主題選定の unit test 追加
- `team-summary` / `slack` を main UX に戻すこと
- LLM の最終文面を決定論的に固定すること

## Start Here

最初に以下を読む。

- `PLAN_update.v2.md` の `Input Surface Contract`
- `PLAN_update.v2.md` の `post-draft` セクション
- `plugins/daytrace/skills/post-draft/SKILL.md`
- `plugins/daytrace/skills/post-draft/references/sample-outputs.md`
- `README.md`

## Checklist

- [x] `plugins/daytrace/skills/post-draft/SKILL.md` の description を v2.3 の narrative draft 文言へ更新する
- [x] Goal / Inputs / UX を `0 ask + optional override` に更新する
- [x] `team-summary` / `slack` を main UX から外し、compatibility note 扱いにする
- [x] 主題選定の 3 段フォールバックを SKILL.md に実装する
- [x] 主題選定は `SKILL.md` の policy であり、Python helper には切り出さないことを明記する
- [x] 読者の自動推定ルールと `--reader` override の扱いを明記する
- [x] トーン / 構成 / 長さの自動判定ルールを更新する
- [x] mixed-scope を前提に narrative 冒頭や注記でどう扱うかを明記する
- [x] `plugins/daytrace/skills/post-draft/references/sample-outputs.md` を narrative 前提に差し替える
- [x] sample output を少なくとも 2 本用意する
  - reader override なし
  - `--reader "社内の非エンジニア"` あり
- [x] fixture review の手順を sample-outputs 側に書く

## Target Files

- `plugins/daytrace/skills/post-draft/SKILL.md`
- `plugins/daytrace/skills/post-draft/references/sample-outputs.md`

## Fixture Review Rules

- 同一 aggregate fixture を使う
- 1 回ごとの wording の差ではなく、次の点を見る
  - 主題が破綻していないか
  - narrative として一本通っているか
  - reader override で説明の粒度が変わるか
  - mixed-scope の注記が誤解を生まないか

## Verification

- [x] `SKILL.md` を読んだ実装者が「主題選定は prompt policy」であると理解できる
- [x] main UX から `team-summary` / `slack` が外れている
- [x] reader override の差が sample output で見える
- [x] fixture review 手順が文書化されている

## Done Criteria

- [x] `post-draft` が `Context & Narrative` として一貫して説明される
- [x] 主題選定の実装場所が未定義でない
- [x] unit test を書かない理由と代替検証が文書化されている
- [x] sample output / fixture review が揃っている
