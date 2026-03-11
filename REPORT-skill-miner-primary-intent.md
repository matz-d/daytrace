# Skill Miner Primary Intent Observation

Date: 2026-03-11
Scope: full-history observation
Command:

```bash
python3 plugins/daytrace/scripts/skill_miner_prepare.py --all-sessions --top-n 5 --max-unclustered 5 --dump-intents
```

## B0 Summary

- total_packets: `112`
- generic_rate: `0.161`
- synonym_split_rate: `0.014`
- specificity_distribution:
  - `high`: `77`
  - `medium`: `34`
  - `low`: `1`

## Observation Notes

- このレポートは `--all-sessions` 前提で、workspace 制限なしの full-history を観測対象にしている
- `generic_rate` は 16.1% で、full-history に広げても `primary_intent` が generic へ大きく崩れている状態ではない
- `synonym_split_rate` は 1.4% と低く、同義語割れが優先課題とは言いにくい
- `specificity_distribution` は `high=77 / medium=34 / low=1` で、intent 自体はかなり具体的に取れている
- 一方で full-history では `56 packets` 規模の oversized cluster が残っており、`generic_tools` と `weak_semantic_cohesion` が同時に出ている
- したがって、B0 の論点は intent 抽出よりも clustering / similarity 側の merge しすぎ抑制にある

## Priority Decision

最優先は `C: clustering / similarity`。

理由:

- B を最優先にする閾値だった `generic intent > 60%` を大きく下回っている
- synonym split も 1.4% と低く、intent normalization を先に厚くする根拠は弱い
- full-history でも specific intent は十分に取れている一方、`write markdown` 系に異なる目的の作業が吸われる giant cluster が残る
- したがって、Track 4 は最小限の normalization に留め、Track 5 の block key / similarity rebalance を先に進めるのが妥当
- その後に Track 6 の split-first / re-triage を合わせると、`proposal_ready 0件` のうち merge 起因のものを減らしやすい

推奨順:

1. `C: clustering / similarity`
2. `D: quality gate rebalance`
3. `B: feature extraction / primary_intent normalization`

## Sample Notes

- `intent-004` の「ステータスラインにサブスクの残使用量が見れない原因を探ってください。」は generic 判定で、観測結果とも整合する
- `intent-005` のような具体的 config / status line 修正依頼は high specificity で取れている
- full-history の最大 cluster は daytrace 以外の履歴も含めて広く集約されており、優先課題は intent 生成より cluster 分離のほうが説明しやすい
