# TODO D2. Output Skill / skill-miner

Phase: Output Skills
Depends on: B2（claude-history）, B3（codex-history）— aggregator は経由しない

## データフロー

skill-miner は aggregator を経由せず、`claude_history.py` と `codex_history.py` を直接呼び出す（期間制限なし、全セッション対象）。daily-report / post-draft とはデータパスが異なる。

## Checklist

- [x] `plugins/daytrace/skills/skill-miner/SKILL.md` のゴール・入力・出力・確認フローを書く
- [x] SKILL.md 内で `claude_history.py` + `codex_history.py` を直接呼び出す導線を作る（全セッションモード）
- [x] 反復作業パターン抽出ロジックを SKILL.md のプロンプトとして定義する
- [x] `skill` / `plugin` / `agent` / `CLAUDE.md` / `hook` の 5 分類ルールを定義する
- [x] 各候補に「なぜその分類か」の説明を出せるようにする
- [x] 提案リスト出力フォーマットを作る
- [x] ユーザーが候補を選択する確認フローを作る
- [x] 選択候補に対するドラフト生成フローを実装する（SKILL.md / plugin.json / CLAUDE.md ルール / hook 設定）
- [x] 3 件以上の候補を安定して出せることを確認する

## Done Criteria

- [x] 提案→選択→ドラフト生成まで一気通貫で完走する
- [x] 候補ごとに分類理由が明示される
