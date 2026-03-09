# TODO D2. Output Skill / skill-miner

Phase: Output Skills
Depends on: B2（claude-history）, B3（codex-history）— aggregator は経由しない

## データフロー

skill-miner は aggregator を経由せず、`claude_history.py` と `codex_history.py` を直接呼び出す（期間制限なし、全セッション対象）。daily-report / post-draft とはデータパスが異なる。

## Checklist

- [ ] `plugins/daytrace/skills/skill-miner/SKILL.md` のゴール・入力・出力・確認フローを書く
- [ ] SKILL.md 内で `claude_history.py` + `codex_history.py` を直接呼び出す導線を作る（全セッションモード）
- [ ] 反復作業パターン抽出ロジックを SKILL.md のプロンプトとして定義する
- [ ] `skill` / `plugin` / `agent` / `CLAUDE.md` / `hook` の 5 分類ルールを定義する
- [ ] 各候補に「なぜその分類か」の説明を出せるようにする
- [ ] 提案リスト出力フォーマットを作る
- [ ] ユーザーが候補を選択する確認フローを作る
- [ ] 選択候補に対するドラフト生成フローを実装する（SKILL.md / plugin.json / CLAUDE.md ルール / hook 設定）
- [ ] 3 件以上の候補を安定して出せることを確認する

## Done Criteria

- [ ] 提案→選択→ドラフト生成まで一気通貫で完走する
- [ ] 候補ごとに分類理由が明示される
