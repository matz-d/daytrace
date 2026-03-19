# Issue: Observation Contract 完全一本化監査

Date: 2026-03-19

## Trigger

CodeRabbit 指摘:

- `observation_contract.adaptive_window.expanded` と `observation_contract.adaptive_window_expanded` の重複
- `observation_contract.input_fidelity` と `observation_contract.approximate` の重複

## 結論（監査結果）

- 指摘は妥当。現状は「主フィールド + 便宜ミラー」が混在しており、契約としては冗長。
- ただし現時点で即削除すると互換性を壊す。テスト・下流参照が残っているため、段階移行が必要。
- 最終形は以下に統一するのが妥当:
  - 残す: `input_fidelity`, `adaptive_window.expanded`
  - 廃止: `approximate`, `adaptive_window_expanded`（top-level）

## 現状の事実確認

### 1) 生成ロジック

`plugins/daytrace/scripts/skill_miner_common.py` の `build_observation_contract()` は:

- `approximate = (input_fidelity == "approximate")` として派生生成
- `adaptive_window_expanded = adaptive_window.expanded` の同値コピーを生成

すなわち現在は実装上も「重複を同期」している。

### 2) 参照箇所（影響範囲）

- 実装参照:
  - `plugins/daytrace/scripts/skill_miner_common.py`
- 仕様/ドキュメント:
  - `plugins/daytrace/skills/skill-miner/references/proposal-json-contract.md`
  - `plugins/daytrace/scripts/README.md`
  - `plugins/daytrace/skills/skill-miner/SKILL.md`
  - `plugins/daytrace/skills/skill-miner/references/cli-usage.md`
  - `docs/skill-miner-current-state.md`
- テスト参照:
  - `plugins/daytrace/scripts/tests/test_skill_miner_contracts.py`
  - `plugins/daytrace/scripts/tests/test_skill_miner_repair.py`
  - `plugins/daytrace/scripts/tests/test_skill_miner.py`

## 問題の本質

1. **契約の曖昧性**
   - 消費側が「どちらを正と見るか」を独自判断しうる。
2. **将来不整合リスク**
   - 生成側の改修時に片方だけ更新される事故余地がある。
3. **進化コスト**
   - フィールド追加/変更のたびに二重管理となり、テストの更新面積が増える。

## 完全一本化への段階的移行案

### Phase 0: 仕様固定（完了）

目的: 互換維持のまま主従関係を明文化する。

- 実施:
  - `proposal-json-contract.md` に「主フィールド/派生フィールド」ルールを記載
- 成果:
  - 現行の運用ブレを防止

### Phase 1: 非推奨化（deprecate）と可視化

目的: 削除前に利用実態を把握する。

- 変更:
  - `proposal-json-contract.md` に `approximate` / `adaptive_window_expanded` を deprecated と明記
  - `scripts/README.md` に移行先を明記
  - 生成時に `observation_contract.deprecations` を追加（例: `["approximate", "adaptive_window_expanded"]`）
- 受け入れ条件:
  - 既存 consumer が壊れない
  - CI で deprecated フィールドの利用箇所が追跡できる

### Phase 2: Consumer 切替（read path 一本化）

目的: 参照側を主フィールドのみに寄せる。

- 変更:
  - 実装/テストで参照を以下へ統一
    - `approximate` -> `input_fidelity == "approximate"`
    - `adaptive_window_expanded` -> `adaptive_window.expanded`
  - 可能なら static check を追加（deprecated key 参照を検出）
- 受け入れ条件:
  - テストが全 green
  - deprecated key を直接参照するコードが 0 件

### Phase 3: 互換維持付き停止（write path 段階停止）

目的: 削除前に実運用影響を最小化する。

- 変更:
  - 既定では deprecated key を出力しないフラグを導入（例: `--contract-v2`）
  - 旧 consumer 向けに当面は opt-in で旧出力を許可（例: `--legacy-observation-contract`）
- 受け入れ条件:
  - 新旧モード双方で契約テストを用意
  - 依存先の移行完了を確認

### Phase 4: 完全削除（single source of truth）

目的: 契約を一意化する。

- 削除対象:
  - `observation_contract.approximate`
  - `observation_contract.adaptive_window_expanded`
- 残す:
  - `observation_contract.input_fidelity`
  - `observation_contract.adaptive_window.expanded`
- 受け入れ条件:
  - 旧キー依存ゼロ
  - 移行ガイドに従った downstream 更新完了

## 推奨タイムライン

- Sprint N:
  - Phase 1 + Phase 2（参照切替まで）
- Sprint N+1:
  - Phase 3（新旧併存、移行監視）
- Sprint N+2:
  - Phase 4（削除）

## テスト戦略

1. 契約テスト
   - 新契約（重複なし）を golden 化
2. 互換テスト
   - 旧契約モードで既存 consumer が動くことを確認
3. 回帰テスト
   - degraded 判定 / adaptive window 拡張時の挙動が維持されること

## ロールバック方針

- Phase 3 までは旧出力フラグで即時ロールバック可能
- Phase 4 実施前に downstream 依存調査を再実行し、未移行が見つかれば削除延期

## 補足（判断の根拠）

- `input_fidelity` は enum で将来拡張しやすく、boolean より表現力が高い
- `adaptive_window` は理由・日数を含む構造体であり、`expanded` 単体コピーは説明力が低い
- よって主フィールドは構造/enum 側に寄せるのが設計として自然
