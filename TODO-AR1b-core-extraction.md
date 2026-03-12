# TODO AR1b. Core Extraction / aggregate slimming

Phase: Architecture Refresh
Depends on: AR1a
Parent Plan Mapping: TODO 1b

## Goal

`aggregate.py` を compatibility shell として残しつつ、再利用可能な core logic を外へ抽出する。
ここでは外部挙動を変えず、責務分離とテスト容易性を上げる。

## 先行ゲート

- [x] AR1a の contract baseline が main branch 相当で安定している
- [x] 先に抽出する関数群と抽出しない関数群を明示する
- [x] 抽出先 module の責務分割を短い note にする

## Parallel Tracks

### Track A. Time / grouping / confidence extraction

- [x] `resolve_date_filters` を CLI 非依存 module へ移す
- [x] `group_confidence` を抽出する
- [x] `build_groups` を抽出する
- [x] grouping / evidence / confidence の unit テストを追加または移設する

### Track B. Source execution / normalization extraction

- [x] `build_command` を抽出する
- [x] `normalize_event` を抽出する
- [x] source result normalization を抽出する
- [x] source selection / preflight evaluation を必要範囲で抽出する

### Track C. Compatibility shell cleanup

- [x] `aggregate.py` を payload assembly と CLI 入口中心の構成に薄くする
- [x] import 境界が分かるように module 配置を整理する
- [x] `aggregate.py` から business logic が過度に残っていないことを確認する
- [x] AR1a の contract test がそのまま通ることを確認する

## Extraction Note

抽出先は `plugins/daytrace/scripts/aggregate_core.py` に集約する。

- `aggregate.py`
  - CLI parser
  - path 解決
  - compatibility payload assembly
  - error emission
- `aggregate_core.py`
  - date filter 解決
  - source registry selection / preflight / execution / normalization
  - timeline collect / grouping / summary

今回あえて抽出しないもの:

- `aggregate.py` の argparse 定義
- top-level JSON shape の最終 assembly
- platform 判定の薄い shell helper

## Deliverables

- 抽出済み core module 群
- 薄くなった `aggregate.py`
- CLI を呼ばずに実行できる unit-testable logic
- `plugins/daytrace/scripts/tests/test_aggregate_core.py`

## Done Criteria

- [x] 抽出した関数が CLI 非依存でテストできる
- [x] `aggregate.py` は compatibility shell として動作する
- [x] AR1a の contract tests が無修正または最小修正で通る
- [x] 外部 JSON 契約に破壊的変更がない

## Verification Notes

- `python3 -m unittest plugins/daytrace/scripts/tests/test_aggregate_core.py`
- `python3 -m unittest plugins/daytrace/scripts/tests/test_aggregate_contracts.py`
- `python3 -m unittest plugins/daytrace/scripts/tests/test_aggregate.py`
