# DayTrace プロジェクト概要（記事参照用）

## 一言で言うと

> **証跡は、すでにそこにある。**
> Git のコミット、Claude のセッション、Chrome の閲覧履歴——
> あなたが毎日残しているローカルログを束ね、日報・投稿下書き・環境改善提案へと自動再構成する Claude Code plugin。

## ハッカソン情報

- **大会**: AIエージェント ハッカソン 2026
- **テーマ**: 「一度命じたら、あとは任せろ」
- **結果**: ファイナリスト選出（入賞ならず）
- **公開リポジトリ**: github.com/matz-d/daytrace-plugin

## インストール方法

```bash
claude plugin marketplace add matz-d/daytrace-plugin
claude plugin install daytrace
```

設定不要。外部へのデータ送信なし。

## 使い方（ユーザー視点）

Claude Code で一言：

```
/daytrace-session
```

または自然言語：
- 「今日の振り返りをお願い」
- 「1日のまとめをして」

## やること（4フェーズ）

1. **収集** — Git / Claude / Codex / Chrome / ファイル変更の 5 ソースから当日の証跡を取得
2. **日報生成** — 自分用・共有用の 2 バリアントを作成し `~/.daytrace/output/<date>/` に保存
3. **投稿下書き** — 条件を満たす日は、1 日の中心テーマを narrative draft に再構成
4. **パターン提案** — AI 履歴の反復パターンを抽出し、`CLAUDE.md` / `skill` / `hook` / `agent` への適用候補を提案

提案が気に入ったら、続けて `/skill-applier` で実ファイルに適用できる（diff 確認・承認フロー付き）。

## 5 つのスキル

| スキル | 役割 |
|--------|------|
| `/daytrace-session` | 全フェーズを一言で自律完走する統合入口 |
| `/daily-report` | その日の活動を日報に再構成 |
| `/post-draft` | 1 日の中心テーマを投稿下書きに再構成 |
| `/skill-miner` | AI 履歴から反復パターンを抽出し適用候補を提案 |
| `/skill-applier` | 提案を `CLAUDE.md` / `skill` / `hook` / `agent` に適用 |

## 5 つのデータソース

| ソース | 対象 |
|--------|------|
| `git-history` | Git コミット + worktree snapshot |
| `claude-history` | `~/.claude/projects/**/*.jsonl` |
| `codex-history` | `~/.codex/history.jsonl` |
| `chrome-history` | Chrome History DB（読み取り専用コピー） |
| `workspace-file-activity` | untracked ファイル変更 |

## 動作要件

- Python 3.9+（標準ライブラリのみ。追加パッケージ不要）
- Git
- macOS または Linux
