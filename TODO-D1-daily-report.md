# TODO D1. Output Skill / daily-report

Phase: Output Skills
Depends on: C（aggregator の中間 JSON が入力）

## Checklist

- [ ] `plugins/daytrace/skills/daily-report/SKILL.md` のゴール・入力・出力・確認フローを書く
- [ ] SKILL.md 内で `aggregate.py` を呼び出し、中間 JSON を取得する導線を作る
- [ ] 3-6 項目の日報ドラフト生成ルールを SKILL.md のプロンプトとして定義する
- [ ] 各項目に根拠ソースを添えるフォーマットを定義する
- [ ] 明日のアクション提案を含める
- [ ] confidence が低い項目だけ確認質問に回す流れを作る
- [ ] source 欠損時の空日報 / 簡易日報の挙動を定義する
- [ ] 1 コマンドで収集→集約→日報出力まで通ることを確認する

## Done Criteria

- [ ] 完全自動で日報ドラフトが出る
- [ ] 不確実点だけ最後に確認できる
