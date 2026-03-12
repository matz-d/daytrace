# TODO AR3. Derived Layers / activities + patterns

Phase: Architecture Refresh
Depends on: AR2
Parent Plan Mapping: TODO 4

## Goal

`observations` の上に `activities` と初期 `patterns` を作り、projection が再利用できる machine-readable layer を整える。
ここでは generic query system は作らず、明示的で狭い query API に留める。

## 先行ゲート

- [x] `observations -> activities` mapping を設計ノートに固定する
- [x] `skill-miner prepare output -> patterns` mapping を設計ノートに固定する
- [x] derivation version / input fingerprint / rebuild rule を固定する

## Parallel Tracks

### Track A. Activities derivation

- [x] `observations` から `activities` を生成するロジックを実装する
- [x] current `aggregate.py` grouping semantics に合わせる
- [x] `group_window` など derivation 条件を記録する
- [x] activities の再現性テストを追加する

### Track B. Initial patterns persistence

- [x] current `skill_miner_prepare.py` 出力との対応を整理する
- [x] 初期 `patterns` の保存形式を実装する
- [x] input fingerprint と derivation version を持たせる
- [x] stale pattern の検出または再生成ルールを実装する

### Track C. Query API and versioning

- [x] `get_observations(...)` を整える
- [x] `get_activities(...)` を実装する
- [x] `get_patterns(...)` を実装する
- [x] projection から import しやすい module 配置にする
- [x] derived data versioning note を書く

## Deliverables

- activity derivation logic
- 初期 pattern persistence / query path
- minimal query API
- versioning / rebuild note
- `plugins/daytrace/scripts/derived_store.py`
- `plugins/daytrace/scripts/derived-layer-note.md`

## Done Criteria

- [x] `activities` を stored `observations` から再生成できる
- [x] 初期 `patterns` を current skill-miner logic と追跡可能に対応付けられる
- [x] `aggregate.py` / `skill-miner` 本体の外から import できる shared layer がある
- [x] derivation version / rebuild rule が固定されている

## Verification Notes

- activity derivation unit/integration テスト
- pattern persistence テスト
- query API を使う簡易 consumer テスト
- `python3 -m unittest plugins/daytrace/scripts/tests/test_derived_store.py`
