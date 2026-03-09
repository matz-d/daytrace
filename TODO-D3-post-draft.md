# TODO D3. Output Skill / post-draft

Phase: Output Skills
Depends on: C（aggregator の中間 JSON が入力）

## Checklist

- [ ] `plugins/daytrace/skills/post-draft/SKILL.md` のゴール・入力・出力・確認フローを書く
- [ ] SKILL.md 内で `aggregate.py` を呼び出し、中間 JSON を取得する導線を作る
- [ ] テックブログ / チーム共有 / Slack 投稿の 3 出力形式を定義する
- [ ] 各形式のトーンと情報粒度を決める
- [ ] 集約結果から用途別に要点を再構成するプロンプトを作る
- [ ] source 欠損時の短縮出力ルールを定義する
- [ ] 用途指定のインターフェースを決める（引数 or 対話で選択）
- [ ] 3 形式それぞれでサンプル出力を確認する

## Done Criteria

- [ ] 用途指定だけで下書きが返る
- [ ] 欠損ソースがあっても出力が破綻しない
