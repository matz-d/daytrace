### 観測範囲
観測範囲: current workspace / 直近 ?日間 / source 不明

## 提案（アクション候補）
1. review changes (review, code)
   種類: プロジェクト設定（CLAUDE.md）
   確度: 高い — 複数セッション・複数ソースで繰り返し観測
   根拠:
   - 2026-03-10T09:00:00+09:00 codex-history: Review the fake API diff and report findings by severity.
   - 2026-03-11T13:15:00+09:00 claude-history: Keep file-line references in the fake review summary.
   効果: プロジェクト設定に追加すれば、毎回の指示が不要になります
   → すぐに CLAUDE.md に追加できます
2. prepare report (report, markdown)
   種類: 再利用スキル
   確度: 中程度 — 複数セッションで出現、もう少し定着を見たい
   根拠:
   - 3 packets / recurring fake daily-brief draft flow
   scaffold goal: prepare report (report, markdown) を再利用可能なスキルとして保存する
   公式 handoff: /skill-creator prepare-report-report-markdown をスキルにしてください
   効果: 再利用コマンドとして保存すれば、同じ作業を素早く再現できます
   → /skill-creator で生成できます

## 有望候補（もう少し観測が必要）
1. edit config (config)
   確度: まだ弱い — 出現回数が少なく、今後の観測次第
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