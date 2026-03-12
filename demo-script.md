# DayTrace 3-Minute Demo Script

## 主メッセージ

「同じローカル証跡から複数成果物を自律的に生成する agent workflow」

## 開始前の準備

### 端末状態

- ターミナル: フォントサイズを大きめ（16pt+）に設定し、画面録画時に判読可能にする
- cwd: DayTrace をインストール済みの作業リポジトリ（当日に Git コミットがあるもの）
- Claude Code が起動済みであること
- 不要な通知・ポップアップを OFF にする

### source の事前確認

```bash
python3 plugins/daytrace/scripts/aggregate.py --date today --all-sessions 2>&1 | head -5
```

`Source preflight:` で `available=` に 2 つ以上表示されていることを確認する。
理想は git-history + claude-history + 1 つ以上。

---

## 台本（3 パート構成）

### Part 1: 観測 — aggregate（〜40 秒）

**話す要点:**
- 「DayTrace はまずローカルの証跡を自動収集します」
- 「Git, Claude/Codex の会話履歴, Chrome, ファイル変更 — 最大 5 ソースを並列で読みます」
- 「外部通信は一切ありません。ローカル完結です」

**実行:**
```bash
python3 plugins/daytrace/scripts/aggregate.py --date today
```

**見せるポイント:**
- stderr の `Source preflight:` 行 — available / unavailable / skipped が出る
- stdout JSON の `summary.total_events` と `sources[]` の status

**詰まった時の言い換え:**
- source が少ない場合: 「利用可能な証跡だけで進みます。これが graceful degrade です」

---

### Part 2: 3 つの成果物 — 同じ観測から分岐（〜1 分 30 秒）

**話す要点（つなぎ）:**
- 「この同じ観測結果から、用途に応じて 3 つの成果物に分岐します」

#### 2a. daily-report — Fact & Action（〜30 秒）

**実行:**
```
/daily-report
```

（「自分用ですか？共有用ですか？」→「自分用」と答える）

**見せるポイント:**
- 1 問だけ聞いて自動完走すること
- 今日の活動が時系列で再構成されていること
- mixed-scope 注記が入る場合はそのまま見せる（「ソースごとにスコープが違うことを明示しています」）

#### 2b. post-draft — Context & Narrative（〜30 秒）

**実行:**
```
/post-draft
```

**見せるポイント:**
- 質問 0 回で自動完走すること
- 同じ証跡から narrative draft が生成されること
- daily-report とはトーンと構造が異なることを指摘する

**話す要点:**
- 「同じデータですが、こちらは外部に出せる記事ドラフトとして再構成します」
- 「質問なしで自動完走します」

#### 2c. skill-miner — Pattern Extraction（〜30 秒）

**実行:**
```
/skill-miner
```

**見せるポイント:**
- 候補が「提案成立 / 追加調査待ち / 今回は見送り」の 3 区分で出ること
- 0 件でも失敗ではないことを補足する（「観測期間が短いと候補が出ないこともあります」）

**話す要点:**
- 「skill-miner は過去の作業パターンから、CLAUDE.md やスキルとして固定化できるものを提案します」

---

### Part 3: 差別化 — CLAUDE.md immediate apply（〜40 秒）

**話す要点:**
- 「skill-miner で `CLAUDE.md` に分類された提案は、そのまま現在のリポジトリの CLAUDE.md に適用できます」
- 「観測 → 分析 → 提案 → 適用まで、一連の流れで自律的に完結します」

**見せるポイント:**
- skill-miner の出力で `CLAUDE.md` 分類の候補がある場合、apply の流れを見せる
- `CLAUDE.md` の diff が表示されること

**詰まった時の言い換え:**
- CLAUDE.md 候補が無い場合: 「今回の観測期間では CLAUDE.md 候補は出ませんでしたが、蓄積が増えると提案が出てきます。仕組みとしてはこういう流れです」と口頭で補足

---

## 締めの一言（〜10 秒）

「DayTrace は、ローカルの作業証跡を自動で読み取り、同じ観測から日報・記事・スキル提案という 3 つの用途に自律的に展開します。設定不要、外部通信なし、source が欠けても縮退動作で完走します。」

---

## タイムライン目安

| パート | 内容 | 目安 |
|--------|------|------|
| Part 1 | aggregate（観測） | 〜40 秒 |
| Part 2a | daily-report | 〜30 秒 |
| Part 2b | post-draft | 〜30 秒 |
| Part 2c | skill-miner | 〜30 秒 |
| Part 3 | CLAUDE.md immediate apply | 〜40 秒 |
| 締め | まとめ | 〜10 秒 |
| **合計** | | **〜3 分** |

---

## リハーサルチェックリスト

- [ ] 3 分以内に収まるか（タイマーで計測）
- [ ] `Source preflight:` の行が画面上で判読可能か
- [ ] 3 つの skill の出力が画面上で判読可能か
- [ ] `CLAUDE.md` diff が画面上で判読可能か
- [ ] 各パートのつなぎが「同じ観測 → 分岐」の流れとして聞こえるか
- [ ] source が減った場合のフォールバック台詞を確認したか
