# TODO AR4. Skill Migration / shared derived data adoption

Phase: Architecture Refresh
Depends on: AR3
Parent Plan Mapping: TODO 5

## Goal

3 つの skill を shared derived data に移行し、source の再実行コストを下げつつ、既存 UX と mixed-scope の説明責務を維持する。

## 先行ゲート

- [x] projection 向け query API が安定している
- [x] `activities` / `patterns` の import path が固定されている
- [x] `aggregate.py` compatibility path を残す移行方針を確認する

## Parallel Tracks

### Track A. daily-report migration

- [x] `daily-report` が `activities` を読む adapter を作る
- [x] mixed-scope の説明が維持されることを確認する
- [x] 既存 aggregate 経由の挙動との差分を確認する

### Track B. post-draft migration

- [x] `post-draft` が `activities` と必要に応じて `patterns` を読む adapter を作る
- [x] narrative selection に必要な field が維持されることを確認する
- [x] 既存 aggregate 経由の挙動との差分を確認する

### Track C. skill-miner migration and regression

- [x] `skill-miner` を store-backed `observations` / `patterns` へ段階移行する
- [x] current candidate / proposal behavior を回帰テストで守る
- [x] store-backed path と旧 path を比較できる期間を設ける

Scope note:

- `skill_miner_detail.py` の raw history 依存は AR4 スコープ外
- `session_ref -> raw conversation detail` の解決は current `observations` 粒度では再構成できない
- AR4 では `prepare` の store-backed path と `patterns` persistence までを移行対象にする

## Deliverables

- skill ごとの projection adapter
- shared derived data 経由の読み取り path
- skill-level regression tests

## Done Criteria

- [x] `daily-report` が query API 経由で derived data を読み取り、互換な出力を返せる
- [x] `post-draft` が query API 経由で derived data を読み取り、互換な出力を返せる
- [x] `skill-miner` が store-backed path へ移行できる
- [x] current skill entrypoint が維持される
- [x] mixed-scope の説明責務が失われていない

## Verification Notes

- skill ごとの snapshot / smoke test
- aggregate 経由出力と store-backed 出力の比較
- source 再実行回数の削減確認
