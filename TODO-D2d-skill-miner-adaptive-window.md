# TODO D2d. skill-miner / Adaptive Window

Phase: Output Skills
Depends on: D2c（`skill-miner` v2 realignment が入っていること）

## Goal

`skill-miner` の観測窓を v2.3 framing に合わせて更新し、`workspace` モードでは母数不足時だけ 30 日へ広げる adaptive window を導入する。

この TODO は `daily-report` / `post-draft` とは独立に進める。

## Non Goals

- classify 対象の変更
- `create / connect / apply` の復活
- `aggregate.py` 経由への統一

## Start Here

最初に以下を読む。

- `PLAN_update.v2.md` の `skill-miner` セクション
- `PLAN_skill-miner.md`
- `TODO-D2c-skill-miner-v2.md`
- `plugins/daytrace/scripts/skill_miner_prepare.py`
- `plugins/daytrace/skills/skill-miner/SKILL.md`
- `plugins/daytrace/scripts/README.md`

## Contract To Implement

- デフォルト観測窓は 7 日
- `all-sessions` は「workspace 制限を外す」モードであり、無制限読み込みではない
- `workspace` モードは 7 日で開始し、packet / candidate が少なすぎる場合だけ 30 日へ拡張する
- adaptive window は `workspace` モードにだけ持たせる
- 実行モードは CLI 引数だけで決める。state file は使わない

## Checklist

- [x] `skill_miner_prepare.py` の観測窓ロジックを現行 contract から v2.3 へ更新する
- [x] `workspace` モードの「少なすぎる」の判定基準をコード内定数または設定値として明示する
- [x] 30 日へ拡張した場合、その事実が output `config` または `summary` で分かるようにする
- [x] `all-sessions` が無制限読み込みではなく 7 日開始であることを docs に反映する
- [x] `plugins/daytrace/skills/skill-miner/SKILL.md` の CLI 説明を更新する
- [x] `plugins/daytrace/scripts/README.md` の contract を更新する
- [x] `plugins/daytrace/skills/skill-miner/references/cli-usage.md` を更新する
- [x] `plugins/daytrace/skills/skill-miner/references/b0-observation.md` に通常運用との違いを追記する
- [x] tests を追加または更新する
  - `workspace` で 7 日開始になる
  - しきい値未満なら 30 日へ拡張する
  - `all-sessions` は workspace 制限を外すが無制限にはならない

## Target Files

- `plugins/daytrace/scripts/skill_miner_prepare.py`
- `plugins/daytrace/skills/skill-miner/SKILL.md`
- `plugins/daytrace/scripts/README.md`
- `plugins/daytrace/skills/skill-miner/references/cli-usage.md`
- `plugins/daytrace/skills/skill-miner/references/b0-observation.md`
- `plugins/daytrace/scripts/tests/test_skill_miner.py`

## Verification

- [x] `python3 -m unittest plugins.daytrace.scripts.tests.test_skill_miner`
- [x] `skill_miner_prepare.py` の output で使用窓が確認できる
- [x] docs / code / tests で window contract が一致している

## Done Criteria

- [x] adaptive window が `workspace` モードだけに入っている
- [x] `all-sessions` の意味が docs / code / tests で一致している
- [x] `0件` 率を下げる狙いが説明できる
