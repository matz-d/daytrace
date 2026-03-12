# DayTrace Architecture Refresh TODO Index

並列実行を前提にした、アーキテクチャ刷新トラックの TODO 一覧。

親プラン:

- [PLAN_architecture-refresh.md](/Users/makotomatuda/projects/lab/daytrace/PLAN_architecture-refresh.md)

## 実行順

1. [TODO-AR1a-contract-baseline.md](TODO-AR1a-contract-baseline.md)
2. [TODO-AR1b-core-extraction.md](TODO-AR1b-core-extraction.md)
3. [TODO-AR2-store-introduction.md](TODO-AR2-store-introduction.md)
4. [TODO-AR3-derived-layers.md](TODO-AR3-derived-layers.md)
5. [TODO-AR4-skill-migration.md](TODO-AR4-skill-migration.md)
6. [TODO-AR4b-store-hardening.md](TODO-AR4b-store-hardening.md)
7. [TODO-AR5-source-registry.md](TODO-AR5-source-registry.md)

## 並列方針

- 各 TODO は「先行ゲート」を 1 つだけ持つ
- 先行ゲート完了後は、トラックごとの実装・テスト・文書化を並列に進めてよい
- 依存がある TODO でも、fixture 準備・stub 実装・テスト skeleton・設計ノートは先行してよい
- `aggregate.py` 互換性を壊しうる変更は、必ず TODO-AR1a の contract baseline が入ってから着手する

## 依存関係

```text
AR1a (contract baseline)
  -> AR1b (core extraction)
  -> AR2 (store introduction)

AR2
  -> AR3 (derived layers)

AR3
  -> AR4 (skill migration)

AR4
  -> AR4b (store hardening / completeness / fail-soft)

AR2
  -> AR5 (source registry redesign)

AR4
  -> AR5 を必須とはしない

AR4b
  -> AR5 を必須とはしないが、
     AR5 で store-backed source 拡張を進める前に入っていると安全

AR5
  は独立拡張として最後に進めるが、
  source identity / manifest draft のみ AR2 より前に固定する
```

## 並列トラックの見方

- `Track A`: もっとも中心の実装
- `Track B`: 周辺の実装またはテスト
- `Track C`: 文書化・回帰テスト・互換性保護

トラック名は固定ではなく、担当分けしやすいように置いている。

## 運用ルール

- 着手時に、先行ゲートの未完了項目が残っていないか確認する
- 並列着手する場合は、担当者ごとに Track を明示する
- Done Criteria は必ず機械的に確認できる形に寄せる
- 互換性関連の変更では、実装より先にテストまたは文書化を置く
