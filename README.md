# DayTrace

ローカル証跡を集約して、日報・スキル提案・投稿下書きを自動生成する Claude Code plugin。

Git コミット、Claude / Codex の会話履歴、Chrome 閲覧履歴、ファイル変更などを自動収集し、
用途に応じた成果物をコマンド一発で生成します。

## できること

| スキル | 役割 | 主軸 | 概要 |
|--------|------|------|------|
| `/daily-report` | **Fact & Action** | date-first | その日全体の活動を「自分用」または「共有用」の日報ドラフトに再構成する。workspace は主軸ではなく補助フィルタ |
| `/post-draft` | **Context & Narrative** | date-first | その日の一次情報から、外部に出せる narrative draft を 1 本組み立てる。reader に合わせてトーンと粒度を自動調整する |
| `/skill-miner` | **Pattern Extraction** | scope-first | Claude / Codex 履歴から反復パターンを抽出し、`CLAUDE.md` / `skill` / `hook` / `agent` への固定化を提案する。workspace か all-sessions かの観測スコープが UX 上の主要な選択肢 |

### 3 skill の関係

```
daily-report  ── Fact & Action    ── その日に何をしたか・何が残っているかを整理する
post-draft    ── Context & Narrative ── その日の一次情報を外に出せる文章に変換する
skill-miner   ── Pattern Extraction  ── 蓄積履歴から反復パターンを読み出し、作法として固定化を提案する
```

`daily-report` と `post-draft` は **date-first**（対象日が主軸）、`skill-miner` は **scope-first**（どの範囲の履歴を読むかが主軸）。

### workspace の意味はスキルごとに異なる

| スキル | workspace の意味 |
|--------|-----------------|
| `daily-report` | 補助フィルタ。未指定でも date-first で動く。指定すると git / ファイル変更を絞り込む |
| `post-draft` | 補助フィルタ。未指定でも date-first で動く。指定すると git / ファイル変更を絞り込む |
| `skill-miner` | 観測スコープ。デフォルトは current workspace の 7 日窓。`--all-sessions` で workspace 制限を外す |

補足:

- `workspace` を省略した場合は、そのコマンドを実行した時点の **current working directory (`cwd`)** を使う
- `git-history` は `cwd` から repo root を見つけた上で、workspace 配下の pathspec に絞って commit を読む
- `daily-report` / `post-draft` で workspace を指定しても、`claude-history` / `codex-history` / `chrome-history` まで repo 限定にはならない

### mixed-scope について

`daily-report` / `post-draft` は source によってスコープが異なる。

- **all-day source**（`claude-history`, `codex-history`, `chrome-history`）: その日全体の証跡
- **workspace source**（`git-history`, `workspace-file-activity`）: current workspace に限定された証跡

workspace を指定しない場合でも、この 2 種類が混在した mixed-scope 出力になりえる。
workspace を指定した場合も、主に `git-history` / `workspace-file-activity` の根拠が絞られるだけで、AI 履歴や Chrome 履歴はその日全体の証跡として残りうる。
出力の冒頭に mixed-scope 注記が入る場合があるが、これは coverage の誤認を防ぐための事実説明であり、日報や narrative の価値を弱めるものではない。

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

このリポジトリには固定の `demo/` fixture や canned output は含めません。
検証はその場のローカル証跡を使って行い、source が足りない場合も graceful degrade で完走すること自体を確認対象とします。

### 1. インストール直後の source 確認

```bash
python3 plugins/daytrace/scripts/aggregate.py --date today --all-sessions >/tmp/daytrace-aggregate.json
```

- `stderr` の `Source preflight:` に `available=` / `unavailable=` / `skipped=` が出る
- `/tmp/daytrace-aggregate.json` の `sources[]` に source ごとの `status` / `scope` が入る
- source が 0 本でも空結果で正常終了する（graceful degrade）

### 2. daily-report の確認（Fact & Action / date-first）

```
/daily-report
```

- 今日全体の活動が日報ドラフトとして生成されること
- 引数なしの場合は「自分用ですか？共有用ですか？」の 1 問だけ確認して完走する
- mixed-scope 注記（all-day source / workspace source の区別）が冒頭に入ることがある
- source が欠けていても空日報または簡易日報で完走すること

### 3. post-draft の確認（Context & Narrative / date-first）

```
/post-draft
```

- 今日の一次情報から narrative draft が 1 本生成されること
- ask 0 回で自動完走すること

### 4. skill-miner の確認（Pattern Extraction / scope-first）

```
/skill-miner
```

- 候補が「提案成立 / 追加調査待ち / 今回は見送り」の 3 区分で返ること
- 0 件でも失敗扱いにならないこと
- `--all-sessions` で workspace 制限を外した広域観測ができること

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
      skill_miner_prepare.py
      skill_miner_detail.py
      chrome_history.py
      workspace_file_activity.py
```

## 制限事項

- macOS / Linux のみ対応（Windows は未検証）
- AI 会話履歴が大量の場合、サマリーに圧縮して処理します
- `skill-miner` は提案時に compressed candidate view を使い、選択後だけ detail を再取得します
- browser URL は query string / fragment を落とした正規化済み URL として扱います
- 利用できない source や権限不足の source は graceful degrade の対象として skip / 短縮出力になります
- install 直後の source 検出サマリーは `aggregate.py` の `stderr` に `Source preflight:` として表示され、machine-readable な詳細は `stdout` JSON の `sources[]` に出ます
- `skill-miner` など対話で候補選択するフローの最終確認は、現状手動確認ベースです
- `sources.json` の欠損や破損は設定エラーとして扱い、明示的に失敗させます
- 個別 source script が欠損している場合は preflight で `command_missing` を表示し、aggregate 全体は他 source の処理を継続します
- shell history は MVP では未収集です

## License

MIT
