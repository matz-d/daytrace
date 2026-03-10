# Classification & Triage Rules

## Classification Rules

正式提案に進める候補だけ、次の 5 分類のどれか 1 つにする。

### `skill`

使う条件:

- 1 つの目的に対して複数ステップの定型フローがある
- 専用の入出力ルールや判断基準がある
- 将来も繰り返し使う価値がある

### `plugin`

使う条件:

- 複数 skill を束ねて初めて価値が出る
- install 可能なまとまりとして扱いたい
- marketplace / plugin 導線を含む配布単位にしたい

### `agent`

使う条件:

- 長めの役割定義や意思決定方針が必要
- 複数タスクを横断する一貫した振る舞いが価値の中心

### `CLAUDE.md`

使う条件:

- repo ローカルの常設ルールとして常に読ませたい
- 毎回同じ作法、禁則、出力方針を最初から共有したい
- 手順よりも原則の固定化が目的

### `hook`

使う条件:

- あるタイミングで自動実行したい
- 人が毎回明示的に呼ばなくてもよい
- lint, format, validation, logging のような機械的処理に向く

## Triage Rules

prepare の出力を読んだら、まず候補を 3 区分に分ける。

### `ready`

- `proposal_ready=true`
- `confidence` が `strong` または `medium`
- そのまま提案してよい

### `needs_research`

- 巨大クラスタ
- 汎用 task shape / 汎用 tool に偏る
- `quality_flags` に注意信号がある
- そのまま 5 分類へ押し込まない

### `rejected`

- `unclustered`
- `confidence=insufficient`
- 単発に近い、または一般化が弱い

ルール:

- 正式提案は **0-5 件** を許容する
- 強い候補が 0 件なら「今回は有力候補なし」と返してよい
- `unclustered` は参考情報にとどめ、件数合わせで提案に混ぜない
- `needs_research` 候補は、必要な場合だけ限定的に detail を取りに行く
