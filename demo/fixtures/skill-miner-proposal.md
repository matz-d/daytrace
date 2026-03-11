<!-- sample output: /skill-miner (scope-first / Pattern Extraction) -->
<!-- 観測条件: --all-sessions, 7日窓, candidate 3件 -->

## 提案成立

1. **findings-first コードレビュー**
   分類: skill
   confidence: medium
   根拠:
   - 2026-03-08T10:00:00+09:00 claude-history: PR レビュー前に「まず主要な発見を列挙してから詳細に入る」よう繰り返し指示
   - 2026-03-10T09:00:00+09:00 codex-history: 同系の review 指示を再確認し、出力構造を指定
   - 2026-03-11T14:00:00+09:00 claude-history: レビュー依頼時に毎回 findings-first フォーマットを明示
   期待効果: レビュー依頼時の前置き指示を省略でき、毎回一貫した findings-first フォーマットで出力される

2. **テスト実行前の lint チェック**
   分類: hook
   confidence: strong
   根拠:
   - 2026-03-07T11:30:00+09:00 codex-history: `pytest` 実行前に `ruff check` を手動で実行する手順を毎回踏む
   - 2026-03-09T16:00:00+09:00 claude-history: lint エラーでテストが失敗した後、「先に lint を通してから」と指示
   - 2026-03-11T10:00:00+09:00 codex-history: 同じパターンを再確認
   期待効果: テスト実行前に自動で lint が走り、lint エラーによるテスト失敗を事前に防げる

## 追加調査待ち

1. **aggregate.py の引数パターン**
   confidence: weak
   根拠:
   - 2026-03-08T09:00:00+09:00 codex-history: `--date today --all-sessions` の組み合わせを複数回使用
   - 2026-03-10T15:00:00+09:00 claude-history: 同系の引数を使って動作確認
   保留理由: 巨大クラスタで、デバッグ用途と定常運用用途が混在している可能性がある。意味の異なる呼び出しが同一候補に含まれているか確認が必要

## 今回は見送り

1. **ファイルパス入力の補完指示**
   理由: 単発の発生で、特定のタスク文脈に限定されており一般化の根拠が不足している

2. **出力を `/tmp` に書き出す慣習**
   理由: パス指定の都度 `/tmp` を使っているが、`/tmp` 以外への書き出し指示も混在しており、統一パターンとして確立されていない
