# demo/fixtures — サンプル出力一覧

DayTrace の 3 skill が生成する出力のサンプルを置くディレクトリ。

## 用途

- **審査員向け fallback**: source が取れない環境でも、期待する出力の形を確認できる
- **3 分デモの素材**: ライブ実行が難しい場合に、このファイルを表示しながら説明する
- **出力品質の基準**: skill の期待出力形式を示す reference として使う

## ファイル一覧

| ファイル | 対応スキル | 内容 |
|----------|-----------|------|
| `daily-report-shared.md` | `/daily-report`（共有用） | Fact & Action — date-first で生成した共有用日報のサンプル |
| `post-draft.md` | `/post-draft` | Context & Narrative — date-first で生成した narrative draft のサンプル |
| `skill-miner-proposal.md` | `/skill-miner` | Pattern Extraction — scope-first で生成した 3 区分 proposal のサンプル |

## fallback 手順

実環境で source が取れない場合は、以下の手順でサンプル出力を使って動作を説明する。

1. `daily-report-shared.md` を開き、「共有用日報」の構造（概要 / 実装 / 調査 / 設計 / 明日のアクション）を示す
2. `post-draft.md` を開き、「narrative draft」の構造（タイトル / 背景 / 何を進めたか / 詰まり・判断 / 次の一手）を示す
3. `skill-miner-proposal.md` を開き、「提案成立 / 追加調査待ち / 今回は見送り」の 3 区分を示す

## スキルの役割差（デモ説明用）

```
daily-report  ── Fact & Action      ── その日に何をした／何が残っているかを整理する（date-first）
post-draft    ── Context & Narrative ── その日の一次情報を外に出せる文章に変換する（date-first）
skill-miner   ── Pattern Extraction  ── 蓄積履歴から反復パターンを読み出し、固定化を提案する（scope-first）
```
