### 観測範囲
観測範囲: current workspace / 直近 ?日間 / source 不明

## 提案（固定化を推奨）
1. review changes (review, code)
   固定先: CLAUDE.md
   confidence: strong
   根拠:
   - 2026-03-10T09:00:00+09:00 codex-history: Review the fake API diff and report findings by severity.
   - 2026-03-11T13:15:00+09:00 claude-history: Keep file-line references in the fake review summary.
   期待効果: review changes (review, code) の再利用フローを安定化できる
   → この作法を固定すれば、毎回の指示が不要になります
2. prepare report (report, markdown)
   固定先: skill
   confidence: medium
   根拠:
   - 3 packets / recurring fake daily-brief draft flow
   期待効果: prepare report (report, markdown) の再利用フローを安定化できる
   → この作法を固定すれば、毎回の指示が不要になります

## 有望候補（もう少し観測が必要）
1. edit config (config)
   confidence: weak
   根拠:
   - 2026-03-12T08:30:00+09:00 codex-history: Update fake config sync before commit for the sample project.
   現状: 巨大クラスタで fake deploy sync と fake lint sync が混在している可能性がある
   次のステップ: 1-2 週間ほど運用してから再観測し、意味のまとまりを確認する

## 観測ノート
1. write markdown (note)
   理由: single occurrence in a fake note-only session
2. Investigate a one-off fake import warning.
   理由: single observed packet only; keep as reference, not as a proposal candidate

どの候補をドラフト化しますか？番号か候補名で指定してください。
