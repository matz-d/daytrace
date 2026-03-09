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
| chrome-history | Chrome の History DB（読み取り専用コピー、Default / Profile * を探索） |
| workspace-file-activity | ワークスペース内の untracked ファイル変更 |

ソースが存在しない環境でも、利用可能なソースだけで動作します（graceful degrade）。
全ソースが無い場合でも空の結果で正常終了します。

## 審査員向け: 最短検証手順

1. 上記のインストールコマンドを実行
2. このリポジトリを開いた状態で `python3 plugins/daytrace/scripts/aggregate.py --workspace . --all-sessions >/tmp/daytrace-aggregate.json` を実行
3. `stderr` の `Source preflight:` に `available=` / `unavailable=` / `skipped=` が出て、install 直後に使える source が一目で分かることを確認
4. `/tmp/daytrace-aggregate.json` の `sources[]` に source ごとの `status` と `reason` が入り、source 0 本でも空結果で正常終了することを確認
5. 任意のリポジトリで `/daily-report` を実行し、利用可能な source だけでドラフトが生成されることを確認

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

- macOS / Linux のみ対応（Windows は未検証）
- AI 会話履歴が大量の場合、サマリーに圧縮して処理します
- browser URL は query string / fragment を落とした正規化済み URL として扱います
- 利用できない source や権限不足の source は graceful degrade の対象として skip / 短縮出力になります
- install 直後の source 検出サマリーは `aggregate.py` の `stderr` に `Source preflight:` として表示され、machine-readable な詳細は `stdout` JSON の `sources[]` に出ます
- `skill-miner` など対話で候補選択するフローの最終確認は、現状手動確認ベースです
- `sources.json` の欠損や破損は設定エラーとして扱い、明示的に失敗させます
- 個別 source script が欠損している場合は preflight で `command_missing` を表示し、aggregate 全体は他 source の処理を継続します
- shell history は MVP では未収集です

## License

MIT
