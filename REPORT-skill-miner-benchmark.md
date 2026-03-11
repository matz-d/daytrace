# Skill Miner Benchmark

Date: 2026-03-11
Workspace: `/Users/makotomatuda/projects/lab/daytrace`

## Context

- B0 の優先順位は `REPORT-skill-miner-primary-intent.md` に合わせて `C: clustering / similarity` を先行
- proposal / docs / tests は `evidence_items[]` 前提を維持
- benchmark は v2 quality fixture に対して、legacy block key + legacy similarity と current 実装を比較

Scenario:

- 10 packets
- 5 packets: `review_changes + search_code + artifact=review + rule=findings-first`
- 5 packets: `review_changes + search_code + artifact=markdown + rule=findings-first`
- legacy は generic task/tool/rule に引っ張られて 1 giant cluster 化
- current は composite block key と similarity rebalance で 2 candidate に分離

## Metrics

| Metric | Before | After |
| --- | ---: | ---: |
| `oversized_cluster` 発生率 | `1.0` | `0.0` |
| `proposal_ready` 件数 | `0` | `2` |
| `0件` 率 | `1.0` | `0.0` |

補足:

- before candidate count: `1`
- after candidate count: `2`
- unclustered count: before `0`, after `0`

## Interpretation

- giant cluster の入口は `tool + generic task + repeated rule` 共有だけでは成立しにくくなった
- `oversized_cluster -> split/re-triage` の導線が quality gate と judge の両方で説明しやすくなった
- `proposal_ready 0件` は正常系のまま残しつつ、merge しすぎが原因の 0 件は減らせている

## Reproduction

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest plugins/daytrace/scripts/tests/test_skill_miner_quality_v2.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest plugins/daytrace/scripts/tests/test_skill_miner.py
```
