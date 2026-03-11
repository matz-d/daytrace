# TODO C2. Aggregator v2 / Scope Mode Metadata

Phase: Foundation
Depends on: C（現行 aggregator が動作していること）

## Goal

`daily-report` / `post-draft` の date-first UX を正しく説明できるように、source ごとのスコープ意味論を `aggregate.py` の出力に埋め込む。

この TODO でやるのは「全 source を全日化すること」ではない。やるのは、現行の hybrid 挙動を machine-readable にすることだけ。

## Non Goals

- 全ローカル repo を横断する git/file 集約
- `post-draft` の主題選定ロジック
- `daily-report` の mode ask 実装
- source CLI の全面書き換え

## Start Here

最初に以下を読む。

- `PLAN_update.v2.md` の `Input Surface Contract` と `Mixed-Scope Contract`
- `plugins/daytrace/scripts/aggregate.py`
- `plugins/daytrace/scripts/sources.json`
- `plugins/daytrace/scripts/tests/test_aggregate.py`
- `plugins/daytrace/scripts/README.md`

## Contract To Implement

- `sources.json` に source ごとの `scope_mode` を追加する
- 値は現時点では `all-day` または `workspace` の 2 種だけ使う
- 初期値は以下で固定する
  - `claude-history`: `all-day`
  - `codex-history`: `all-day`
  - `chrome-history`: `all-day`
  - `git-history`: `workspace`
  - `workspace-file-activity`: `workspace`
- `aggregate.py` の `sources[]` summary に `scope` を含める
- `scope` は `supports_all_sessions` から導出しない。`scope_mode` をそのまま使う

## Checklist

- [x] `plugins/daytrace/scripts/sources.json` の全 source に `scope_mode` を追加する
- [x] `aggregate.py` の source registry required fields に `scope_mode` を追加する
- [x] `summarize_source_result()` が `scope` を返すようにする
- [x] `scope` が `sources[]` の全 entry に入ることを保証する
- [x] `aggregate.py` の top-level contract は壊さず、既存 consumer が読める shape を維持する
- [x] `plugins/daytrace/scripts/README.md` に `scope_mode` と `scope` の説明を追加する
- [x] `plugins/daytrace/scripts/tests/test_aggregate.py` に `scope` 検証を追加する
- [x] `--all-sessions --date today` の時に `all-day` source が期待通り表示されるケースをテストする
- [x] `--workspace /path` 指定時に `workspace` source が期待通り表示されるケースをテストする

## Target Files

- `plugins/daytrace/scripts/sources.json`
- `plugins/daytrace/scripts/aggregate.py`
- `plugins/daytrace/scripts/README.md`
- `plugins/daytrace/scripts/tests/test_aggregate.py`

## Verification

- [x] `python3 -m unittest plugins.daytrace.scripts.tests.test_aggregate`
- [x] `python3 plugins/daytrace/scripts/aggregate.py --date today --all-sessions`
- [x] 出力 JSON の `sources[]` 全 entry に `scope` が入っていることを目視確認する

## Done Criteria

- [x] `scope_mode` が source registry に存在する
- [x] `aggregate.py` が `scope` を出力する
- [x] `scripts/README.md` が新 contract を説明している
- [x] `test_aggregate.py` が回帰なく通る
