# DayTrace

ローカル証跡を集約して、日報・スキル提案・投稿下書きを自動生成する Claude Code plugin。

Git コミット、Claude / Codex の会話履歴、Chrome 閲覧履歴、ファイル変更などを自動収集し、
用途に応じた成果物をコマンド一発で生成します。

## できること

| スキル | 説明 |
|--------|------|
| `/daily-report` | その日の活動から日報ドラフトを自動生成 |
| `/skill-miner` | AI会話の反復パターンを抽出し、skill/plugin/agent/CLAUDE.md/hook を提案・ドラフト生成 |
| `/post-draft` | 活動ログからテックブログ・チーム共有・Slack投稿の下書きを生成 |

## インストール

```bash
# Claude Code 内で実行
/plugin marketplace add KaishuShito/agi-lab-skills-marketplace
/plugin install daytrace@daytrace
```

## 依存関係

- Python 3.x（sqlite3, json は標準ライブラリ）
- Bash
- Git

外部パッケージのインストールは不要です。

## データソース

DayTrace は以下のローカルデータを読み取ります。**外部へのデータ送信は一切行いません。**

| ソース | 対象 |
|--------|------|
| git-history | カレントリポジトリの Git コミット |
| claude-history | `~/.claude/projects/**/*.jsonl` |
| codex-history | `~/.codex/history.jsonl`, `~/.codex/sessions/` |
| chrome-history | Chrome の History DB（読み取り専用コピー） |
| workspace-file-activity | ワークスペース内の untracked ファイル変更 |

ソースが存在しない環境でも、利用可能なソースだけで動作します（graceful degrade）。
全ソースが無い場合でも空の結果で正常終了します。

## 審査員向け: 最短検証手順

1. 上記のインストールコマンドを実行
2. 任意のリポジトリで `/daily-report` を実行
3. Git 履歴があれば日報ドラフトが生成されます（他のソースは任意）

## リポジトリ構成

```text
.claude-plugin/
  marketplace.json

plugins/
  daytrace/
    .claude-plugin/
      plugin.json
    skills/
      daily-report/
        SKILL.md
      skill-miner/
        SKILL.md
      post-draft/
        SKILL.md
    scripts/
      sources.json
      aggregate.py
      git_history.py
      claude_history.py
      codex_history.py
      chrome_history.py
      workspace_file_activity.py
```

## 制限事項

- Chrome 履歴は Default プロファイルのみ対応
- macOS / Linux のみ対応（Windows は未検証）
- AI 会話履歴が大量の場合、サマリーに圧縮して処理します

## License

MIT
