# 開発タイムライン（記事参照用）

## 全体像

開発期間: 約 3 週間（2026-03-04 〜 2026-03-25）
総コミット数: 97+
主言語: Python（stdlib のみ）

---

## Week 1：着想・初期構造（3/4〜3/9）

- `2026-03-04`: marketplace への初期 plugin 追加（terminal-vibes など）でインフラ整備
- `2026-03-06`: ハッカソンスターターテンプレート追加
- `2026-03-09`: **DayTrace として rename・初期構造実装**
  - ソース CLI 契約、出力スキル、パッケージング計画を一気に立案
  - workspace サポートとプリフライト source 可用性チェックを追加
  - README に詳細な使用説明を記述

## Week 2：コア機能・品質設計（3/10〜3/14）

- `2026-03-10`: **skill-miner の基盤構築**
  - `skill_miner_prepare.py` と `skill_miner_detail.py` の 2-phase CLI 設計
  - 候補品質評価と提案生成を実装
  - **提案品質問題（ISSUE）を発見**：根拠の弱い候補が正式提案に混ざる問題
  - quality flags（`proposal_ready` / `triage_status`）導入
- `2026-03-11`: skill-miner v2 ドキュメント整備、`evidence_items[]` 導入

## Week 3：品質改善・仕上げ・提出（3/21〜3/25）

- `2026-03-21`: チャット境界・クロスリポ handoff チェックリスト追加、テスト整備
- `2026-03-22`: **marketplace 公開**（`marketplace.json` 追加）
  - `claude plugin marketplace add matz-d/daytrace-plugin` でインストール可能に
  - 旧ドキュメント整理、サブモジュール構造安定化
- `2026-03-24`: P17（hook / agent 自動生成パス）実装完了
- `2026-03-25`: **クラスタリング精度向上（最終品質改善）**
  - `INTENT_STOP_WORDS`（汎用語彙を intent トークンから除外）
  - `GENERIC_SHAPE_DISCOUNT=0.7`（汎用 task shape のマッチに 30% 減衰）
  - `subdivide_oversized_cluster`（巨大クラスタの自動再分割）
  - generic-only penalty の段階化

---

## 苦労した点：skill-miner の提案品質問題

ISSUE に記録した問題（`ISSUE-skill-miner-proposal-quality.md`）：

**症状**: 75 packets 中 63 packets が 1 つのクラスタに集約されてしまう

**原因**:
- `review_changes` / `search_code` などの汎用語彙を使うと多くのセッションが同一クラスタに吸い込まれる
- 「提案件数を埋める」圧力で根拠の弱い候補が混入してしまう

**解決策**（最終的に実装したもの）:
1. 提案件数を固定しない（0 件でも正常系）
2. `unclustered` は `rejected` 扱いに（件数合わせに使わない）
3. 巨大クラスタは `needs_research` に回す（そのまま提案しない）
4. intent ストップワード除去で偽陽性を低減
5. 巨大クラスタの自動再分割ロジック

---

## テストスイート

- Python 3 stdlib のみ（外部パッケージ不要）
- `python3 -m pytest tests/ -v` で全テスト実行
- テスト対象：classifier、formatter、proposal golden fixture、carry-forward state machine など

---

## 最終監査（提出前）

**強度: 8.8/10**

> carry-forward loop は閉じており、test suite は green。
> コア設計（clustering → quality gate → triage → scaffold）は全フェーズ実装済み。

**デモで見せれば強いもの**:
- 同じ作業パターンが複数セッションで cluster として浮かび上がり、CLAUDE.md に即適用できる diff preview まで自動生成されるシーン
- source が 1–2 本しかなくても graceful degrade で形になった日報が出るシーン
- 0 候補時の enriched output（「空振りでも価値がある」設計思想）
