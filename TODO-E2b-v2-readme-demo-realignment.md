# TODO E2b. README / Demo Realignment for v2.3

Phase: Polish & Submit
Depends on: C2, D1b, D3b, D2d（少なくとも文言が固まっていること）

## Goal

README とデモ導線を v2.3 の product framing に合わせ、審査員に `date-first / date-first / scope-first` を短時間で誤解なく伝えられる状態にする。

## Non Goals

- source CLI の新機能実装
- demo 用の大規模 UI 追加
- 動画編集の完成

## Start Here

最初に以下を読む。

- `PLAN_update.v2.md`
- `README.md`
- `TODO-E2-readme-demo.md`
- `plugins/daytrace/skills/daily-report/SKILL.md`
- `plugins/daytrace/skills/post-draft/SKILL.md`
- `plugins/daytrace/skills/skill-miner/SKILL.md`

## Checklist

- [x] `README.md` の 3 skill 説明を v2.3 framing に更新する
  - `daily-report`: Fact & Action
  - `post-draft`: Context & Narrative
  - `skill-miner`: scope-first analysis
- [x] `README.md` から古い `post-draft` 3 用途説明を外す
- [x] workspace の意味が skill ごとに違うことを README で明示する
- [x] mixed-scope の説明を README に入れる
- [x] 審査員向け最短検証手順を v2.3 に合わせて更新する
- [x] fallback plan を README または demo 手順書から辿れるようにする
- [x] fallback を repo 常設のサンプル出力に依存させず、録画バックアップ中心に整理する
- [x] `TODO-E2-readme-demo.md` と役割が重複しないよう、必要ならリンクまたは引継ぎメモを追記する

## Target Files

- `README.md`
- `PLAN_update.v2.md`（必要なら fallback wording の整合だけ）
- `TODO-E2-readme-demo.md`

## Verification

- [x] README の冒頭だけ読んで 3 skill の役割差が説明できる
- [x] mixed-scope と workspace semantics が README に残っている
- [x] fallback が録画バックアップ中心で説明されている

## Done Criteria

- [x] README が v2.3 framing と矛盾しない
- [x] demo fallback 方針が repo 内で共有できる
- [x] 3 分デモの説明が product copy と一致している
