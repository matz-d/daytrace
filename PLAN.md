# DayTrace Implementation Plan

## Goal

DayTrace を、ハッカソン提出に耐える **統合された体験** として実装する。

コアは **ローカル証跡の集約エンジン**。
出力は用途別のスキル群として多様なシーンをカバーする。

- `daily-report`: その日の証跡から日報ドラフトを作る
- `skill-miner`: Claude / Codex の全セッションを横断して反復作業を抽出し、skill / plugin / agent / CLAUDE.md / hook のどれにすべきかを分類・ドラフト生成まで一気通貫で行う
- `post-draft`: 集約結果からテックブログ・チーム共有・Slack投稿などの下書きを生成する

**Claude Code plugin として install でき、審査員のマシンでもすぐ試せる形** で提出する。

**締切: 2026-03-22（日）23:59**

---

## Product Scope

### MVP（全て必須）

ソース 5 本:

- `git-history`
- `claude-history`
- `codex-history`
- `chrome-history`
- `workspace-file-activity`

出力スキル 3 本:

- `daily-report`
- `skill-miner`
- `post-draft`

### Post-MVP

以下は optional とする。

- `gh-activity`
- `gcal`
- `gdrive`
- `screen-time`
- `healthkit`

---

## Success Criteria

提出時点で、以下をすべて満たす。

1. Claude Code から install できる plugin として成立している
2. **審査員のマシンで install → 実行が通る**（ソース欠損時は graceful degrade）
3. 各 `SKILL.md` を読めば、何を入力すると何が返るかが分かる
4. `daily-report` がローカル証跡を使って全自動で日報ドラフトを出力する
5. `skill-miner` が全セッションを横断し、分類→提案→ドラフト生成まで完走する
6. `post-draft` がテックブログ・チーム共有用の下書きを生成する
7. 壊れたソースがあっても全体が止まらず、skip して動く
8. README に setup / demo flow / limitations が明記されている
9. 3 分デモ動画で全出力スキルの統合体験を見せられる

---

## Architecture

3 層構成。

### 1. Source CLI layer

各ソースから共通 JSON イベントを出す薄い CLI 群。

ソース:

- `git-history`
- `claude-history`
- `codex-history`
- `chrome-history`
- `workspace-file-activity`

責務:

- source-specific な取得処理
- ロック回避やファイル存在確認
- 共通イベント形式への正規化
- 失敗時に機械可読なエラー JSON を返す（`{"status": "error", "source": "...", "message": "..."}`)
- ソースが存在しない場合は `{"status": "skipped", "source": "...", "reason": "not_found"}` を返す

共通イベント形式:

```json
{
  "source": "git-history",
  "timestamp": "2026-03-09T14:30:00+09:00",
  "type": "commit",
  "summary": "...",
  "details": {},
  "confidence": "high"
}
```

拡張性ルール:

- 共通契約は 6 フィールド（`source`, `timestamp`, `type`, `summary`, `details`, `confidence`）。`details` は必須だが自由形式とする
- `details` の中身は各ソースが自由に定義する。aggregator は `details` の中身を解釈せず、そのまま中間 JSON に載せる
- 新しいソースを追加する場合は、スクリプトを `scripts/` に置き、`sources.json` に登録するだけで aggregator が認識する
- 追加フィールドは許可するが、aggregator が依存してよいのは上記 6 フィールドだけとする

実装言語: 各ソースの要件に最適な言語を選ぶ。Python（sqlite3, json 標準ライブラリ）、bash（git 操作）など混在可。

### 2. Core aggregation layer（ハイブリッド方式）

複数 CLI の結果を集約し、DayTrace の中間表現を作る。

**ソース登録:**

- `scripts/sources.json` にソース一覧を定義する
- aggregator はこのファイルを読んで実行対象を決定する
- ソースの追加・削除は `sources.json` の編集だけで完結する

```json
[
  {
    "name": "git-history",
    "command": "bash scripts/git_history.sh",
    "required": false,
    "timeout_sec": 10,
    "platforms": ["darwin", "linux"],
    "supports_date_range": true,
    "supports_all_sessions": false
  },
  {
    "name": "claude-history",
    "command": "python3 scripts/claude_history.py",
    "required": false,
    "timeout_sec": 30,
    "platforms": ["darwin", "linux"],
    "supports_date_range": true,
    "supports_all_sessions": true
  }
]
```

`sources.json` schema の最小契約:

- `name`: source の識別子
- `command`: 実行コマンド
- `required`: 必須 source かどうか
- `timeout_sec`: source ごとのタイムアウト
- `platforms`: 対応 OS 一覧
- `supports_date_range`: 期間指定モードをサポートするか
- `supports_all_sessions`: 全件走査モードをサポートするか

将来フィールドは追加可能とするが、aggregator が必須前提にしてよいのは上記のみ。

**ルールベース前処理:**

- `sources.json` からの利用可能ソース自動検出
- 並列収集
- タイムライン統合（時刻順ソート）
- 近接イベントの関連付け（グルーピング閾値は設定可能、デフォルト ±15分）
- `confidence` と `evidence` の付与
- skip / fallback の記録

**LLM 最終統合:**

- ルールで前処理した中間表現を SKILL.md のプロンプトで Claude に渡す
- 活動の意味的なまとめ・文脈の推定は Claude が担当
- 不確実な点のリストアップも Claude が判断

confidence 判断ルール（`aggregate.py` 内で設定変更可能）:

- `git + AI history` が揃えば `high`
- どちらか一方のみなら `medium`
- browser や file activity だけなら `low`
- ソース 0 本でも動く（`no sources available` を返す）

### 3. Output skill layer

中間表現から用途別の成果物を作る。

スキル:

- `daily-report` — aggregator の中間 JSON を入力に日報ドラフトを生成
- `skill-miner` — aggregator を経由せず、Claude / Codex セッションを直接走査して分析→分類→ドラフト生成（独自データパス）
- `post-draft` — aggregator の中間 JSON を入力にテックブログ・チーム共有・Slack 投稿の下書きを生成

データフローの違い:

- `daily-report` / `post-draft`: SKILL.md → `aggregate.py` 実行 → 中間 JSON → Claude が最終統合・出力
- `skill-miner`: SKILL.md → `claude_history.py` + `codex_history.py` を直接実行（期間制限なし、全セッション対象）→ Claude が分析・分類・ドラフト生成

UX フロー:

- **完全自動で走る** — コマンド一発で収集→集約→出力まで実行
- **不確実な点だけ最後に確認** — 出力完了後、confidence が低い項目や補足が必要な箇所をユーザーに質問
- 確認後、最終版を出力

---

## Repository Workstreams

### A. Marketplace / plugin packaging

対象:

- `.claude-plugin/marketplace.json`
- `plugins/daytrace/.claude-plugin/plugin.json`
- `plugins/daytrace/skills/*/SKILL.md`
- root `README.md`

やること:

- `hackathon-starter` を `daytrace` にリネーム
- marketplace 名、description、tags を DayTrace に合わせる
- install コマンドと demo 導線を README に反映
- starter / terminal-vibes 関連の文言を削除し、提出物として読める状態にする
- **審査員向け install ガイド** を README に記載（依存関係、動作確認手順）

### B. Source CLIs

#### B1. `git-history`

要件:

- 期間指定で commit を取得
- 変更ファイル一覧を付与
- 直近 diff summary を生成

実装:

- `git log --name-only --after --before` ベース
- bash スクリプトで十分。出力は JSON

#### B2. `claude-history`

要件:

- `~/.claude/projects/**/*.jsonl` を走査
- 対象日または期間の user / assistant イベントを抽出
- `cwd`, `timestamp`, `sessionId` を保持
- セッション単位の要約を生成

実装:

- Python。jsonl パース + 期間フィルタ
- thinking 全文ではなく `message.content` を扱う
- セッション数が多い場合はサマリーで圧縮

#### B3. `codex-history`

要件:

- `~/.codex/history.jsonl` を読む
- `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` を読む
- session meta, commentary, tool call をイベント化する

実装:

- Python。`history.jsonl` を索引として sessions を主データにする

#### B4. `chrome-history`

要件:

- Chrome の `History` DB を一時コピーして読む
- URL, title, last visit time, visit count を取得
- 調査行動としてまとめる

実装:

- Python（sqlite3）。`/tmp` にコピーして読む
- 最初は `Default` profile のみ
- query string は除去

#### B5. `workspace-file-activity`

要件:

- `git ls-files --others --exclude-standard` で非 Git（untracked）ファイルを取得
- `stat` で `mtime`, size を取得
- tracked ファイルは `git-history` が担当するため、ここでは扱わない

実装:

- bash or Python。対象は指定ディレクトリ配下に限定

### C. Aggregator

`activity-aggregator` を中核に置く。

要件:

- source CLI を並列で実行
- source ごとの結果を共通 JSON に統合
- 近い時刻のイベントをグルーピング
- 出力イベントごとに `source`, `evidence`, `confidence` を持たせる
- source failure を `skip` として記録（エラーメッセージ付き）
- **ソースが 1 本も取れなくても空のタイムラインとして正常終了する**

実装:

- Python スクリプト。`sources.json` を読み、各 source CLI を subprocess で並列実行し、結果をマージ
- グルーピング閾値などのパラメータはスクリプト冒頭の定数で調整可能
- ルールベースで前処理した JSON を出力
- この JSON を SKILL.md 経由で Claude に渡す

### D. Output skills

#### D1. `daily-report`

要件:

- その日の活動を 3-6 項目でまとめる
- 各項目に根拠ソースを併記する
- 明日やるべきことを提案する
- **完全自動で走り、不確実な点だけ最後に確認する**

出力形式:

- Markdown テキスト（Claude Code 上でそのまま読める）
- 確認後、Slack/メール向けテキストに変換可能

完成条件:

- 1 コマンドで日報ドラフトが出る
- source 欠損時にも graceful degrade する
- 審査員のマシンでも動く（ソース 0 本 = 空の日報が出る）

#### D2. `skill-miner`

要件:

- Claude / Codex の **全セッション** を横断して反復作業を抽出
- 5 分類に振り分ける: `skill` / `plugin` / `agent` / `CLAUDE.md` / `hook`
- 各候補になぜその分類なのか説明を付ける
- **選択した候補の SKILL.md / plugin.json / CLAUDE.md ルール / hook 設定のドラフトを生成する**

フロー:

1. 全セッション走査 → 反復パターン抽出（自動）
2. 分類 + 提案リスト出力（自動）
3. ユーザーに「どれをドラフト化するか」確認
4. 選択された候補のドラフトを生成

完成条件:

- 直近 1 週間または全セッションから候補を 3 件以上出せる
- 提案→選択→ドラフト生成まで一気通貫で完走する

#### D3. `post-draft`

要件:

- 集約結果から用途別の下書きを生成する
- 対応フォーマット: テックブログ / チーム共有サマリー / Slack 投稿
- 送信や公開はしない（下書きまで）

完成条件:

- 用途を指定すると対応する下書きが出る
- source 欠損時にも graceful degrade する

---

## Build Order

残り 13 日。Phase を 3 つに圧縮し、並行作業を最大化する。

### Phase 1: Foundation（3/10 - 3/13）4 日間

目的: plugin 骨格 + 全ソース CLI を一気に立てる

並行タスク:

- **A. Packaging**: `hackathon-starter` → `daytrace` リネーム、marketplace.json / plugin.json / README 更新
- **B. Source CLIs 5 本**: git-history, claude-history, codex-history, chrome-history, workspace-file-activity を全て実装
- **C. Aggregator**: ルールベース前処理の実装

完了条件:

- `plugins/daytrace/` が存在し、install できる
- 各 source CLI が単体で JSON を返す
- aggregator が 5 本の出力をマージした中間 JSON を返す

### Phase 2: Output Skills（3/14 - 3/18）5 日間

目的: 3 つの出力スキルを全て完成させる

並行タスク:

- **D1. daily-report**: SKILL.md + 全自動フロー + 確認ステップ
- **D2. skill-miner**: 全セッション走査 + 5 分類 + ドラフト生成
- **D3. post-draft**: テックブログ / チーム共有 / Slack の 3 フォーマット

完了条件:

- 3 つのスキルが全て 1 コマンドで完走する
- source 欠損時に graceful degrade する
- 不確実点の確認 → 最終出力のフローが動く

### Phase 3: Polish & Submit（3/19 - 3/22）4 日間

目的: 審査員体験を仕上げる

タスク:

- 審査員マシンでの install テスト（ソースが少ない環境での動作確認）
- README 最終整備（setup / demo flow / limitations / install ガイド）
- デモ動画撮影（3 分。全出力スキルの統合体験を見せる）
- エッジケース修正（ソース 0 本、巨大履歴、権限エラーなど）
- デモスクリプト作成（再現可能な手順書）

完了条件:

- クリーンな環境から install → 実行が通る
- README を読めば 5 分で試せる
- 3 分デモ動画が完成している

---

## File Plan

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
      git_history.sh
      claude_history.py
      codex_history.py
      chrome_history.py
      workspace_file_activity.py
      aggregate.py

README.md
```

備考:

- `hackathon-starter` は `daytrace` にリネームする（据え置きにしない）
- `terminal-vibes` は残しても削除してもよい（提出物としては不要）
- `activity-aggregator` は独立スキルにせず、各出力スキルの前処理として `aggregate.py` を呼ぶ形にする

---

## Risk Register

### 1. 審査員環境での動作

リスク: 審査員のマシンに Chrome / Codex / Claude 履歴がない、または構造が異なる

対応:
- 全ソースが `skipped` でも空の結果で正常終了する設計にする
- README に「どのソースがあるとより良い結果が出るか」を明記
- install 時に利用可能ソースを自動検出して表示する

### 2. Chrome DB lock

リスク: 稼働中ブラウザの DB がロックされる

対応: `/tmp` にコピーして読む

### 3. AI history volume

リスク: 会話履歴が長く、コンテキストに入りきらない

対応:
- 期間・cwd・role で絞る
- セッション単位のサマリーに圧縮してから渡す
- skill-miner は段階的に処理（走査→要約→分類）

### 4. Privacy

リスク: URL, prompt, 顧客名, token などが混ざる

対応:
- ローカル完結なのでデータ送信はしない前提
- chrome-history の query string は除去
- README に「ローカルデータのみ使用、外部送信なし」を明記

### 5. 残り時間

リスク: 13 日で 5 ソース + 3 出力スキル + 審査員対応は tight

対応:
- Phase を 3 つに圧縮し並行作業を最大化
- 各スキルの最小動作を先に通し、磨き上げは Phase 3 に回す
- 完璧より完走を優先

---

## Decisions Made

要件確認で決定した事項。

1. plugin 名は `daytrace`
2. `hackathon-starter` は `daytrace` にリネームする
3. 実装言語は要件ごとに最適なものを選ぶ（Python / bash 混在可）
4. デモは全出力スキルの統合体験を見せる（daily-report だけを主役にしない）
5. ソース 5 本すべて MVP 必須
6. 出力スキル 3 本すべて MVP 必須（`post-draft` も phase 2 送りにしない）
7. 集約方式はハイブリッド（ルール前処理 + LLM 最終統合）
8. skill-miner の分類軸は 5 つ: skill / plugin / agent / CLAUDE.md / hook
9. skill-miner は提案→選択→ドラフト生成まで一気通貫
10. UX は完全自動→不確実点だけ最後に確認
11. 審査員のマシンでも install して試せる状態にする
12. Privacy はプライバシー重視方針、ローカル完結前提
