# TODO D1. Output Skill / daily-report

Phase: Output Skills
Depends on: C（aggregator の中間 JSON が入力）

## Checklist

- [x] `plugins/daytrace/skills/daily-report/SKILL.md` のゴール・入力・出力・確認フローを書く
- [x] SKILL.md 内で `aggregate.py` を呼び出し、中間 JSON を取得する導線を作る
- [x] 3-6 項目の日報ドラフト生成ルールを SKILL.md のプロンプトとして定義する
- [x] 各項目に根拠ソースを添えるフォーマットを定義する
- [x] 明日のアクション提案を含める
- [x] confidence が低い項目だけ確認質問に回す流れを作る
- [x] source 欠損時の空日報 / 簡易日報の挙動を定義する
- [x] 1 コマンドで収集→集約→日報出力まで通ることを確認する

## Done Criteria

- [x] 完全自動で日報ドラフトが出る
- [x] 不確実点だけ最後に確認できる

## Verification Notes

- [x] 2026-03-09 に `python3 plugins/daytrace/scripts/aggregate.py --workspace /Users/makotomatuda/projects/lab/daytrace --date today` を実行し、中間 JSON を取得した（`success=5`, `events=86`, `groups=10`）
- [x] 上記 JSON から SKILL.md のルールに沿って 5 項目の日報ドラフトを組み立て、`low` confidence 項目だけを `確認したい点` に分離できることを確認した
- [x] `chrome-history` 単独では `success=1` かつ全 group が `low` になること、擬似 0 source ケースでは `summary.no_sources_available=true` と `sources[].status=skipped` になることを確認した
