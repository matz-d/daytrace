# 実際の出力例（記事参照用）

## チャット上の表示イメージ

```
Git: 3 commits  Claude: 12 sessions  Chrome: 47 tabs
日報: report-private.md ✓  report-share.md ✓
投稿下書き: post-draft.md ✓（今日のテーマ: DayTrace スキル設計）
パターン提案: 候補内訳 適用 2 / 追加観測 0 / 観測ノート 1（合計 3）

## 提案（アクション候補）

1. git commit 前に lint を自動実行
   種類: 自動チェック（hook）
   確度: 高い — 複数セッション・複数ソースで繰り返し観測
2. daily-report の出力先を固定化
   種類: プロジェクト設定（CLAUDE.md）
   確度: 中程度 — 複数セッションで出現、もう少し定着を見たい

→ 続けて /skill-applier で適用できます
```

---

## 実際の日報出力（2026-03-25 の例）

**report-private.md より抜粋**:

```markdown
## 日報 2026-03-25

### 今日の流れ

1. **FX分析（POG2）**
   1dタイムフレームのperfect_order比較データを読み込み、6通貨ペアの前日サマリを確認。
   根拠: Claudeの会話ログでの read×6 ツール使用

2. **daytrace skill-miner 改善コミット**
   クラスタリング精度向上と提案品質改善のPRを取り込み。VSCode設定も追加。
   根拠: Gitの変更履歴「Enhance skill-miner proposal quality...」

3. **Obsidian Vault 整理・メタ情報更新**
   Vaultのフォルダ構成に合わせてmetaを更新。sed/find/python3を多用した大規模リファクタリング。
   根拠: Codexの会話ログ「最新のフォルダ構成に従って、meta情報を更新してください」
```

**注目ポイント**: 各項目に「根拠」が明示されている。何のログから読み取ったかが分かる。

---

## 実際の投稿下書き出力（2026-03-25 の例）

**post-draft.md より抜粋**:

```markdown
# AI ツールと手作業が交差する一日 ── 分析・整備・調査を横断して

今日は「ツールを使いながら考える」という日だった。

## 朝：FXのルーティンと開発の進捗確認

朝一番の習慣である FX 分析から始めた。Claude に 6 通貨ペアの前日サマリファイルを一括で
読み込ませ、パーフェクトオーダーの状態と RSI・移動平均を確認する。毎朝のルーティンでも、
AI がデータを整理してくれると見落としが減る実感がある。

その後、GitHub で自分のリポジトリを確認すると、DayTrace の skill-miner の改善コミットが
入っていた。クラスタリング精度の向上と提案品質の改善が入り、徐々に実用的なラインに近づいてきた。
```

**注目ポイント**: 日報と違い、読者向けの narrative スタイル。「なぜそれをしたか」の文脈が入る。

---

## 出力ファイル構造

```
~/.daytrace/output/
  2026-03-25/
    report-private.md   # 自分用日報（根拠付き箇条書き）
    report-share.md     # 共有用日報（公開しても良い形式）
    post-draft.md       # 投稿下書き（narrative スタイル）
    proposal.md         # パターン提案詳細
    proposal.json       # 提案の機械可読形式
```
