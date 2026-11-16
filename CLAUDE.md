# DayTrace

Claude Code / Codex の会話ログ、Git、未コミットファイルの変更を、ローカルの SQLite（`~/.daytrace/daytrace.sqlite3`）に毎日ためる Claude Code plugin。利用者向け説明は `plugins/daytrace/README.md`。

## 現在の方針（v0.2.0〜）

日報・投稿下書き・パターン提案の生成はやめた。まず「きちんとログを取る」ことに絞っている。

最初に取るログ:

1. 何を頼んだか（Claude の `user_requests[]`、Codex の `turns[].request`）
2. 何を決めたか・見送ったか（会話から読み取る。未実装）
3. どこで手戻りしたか（言い直し、「なんか違う」など。会話から読み取る。未実装）
4. どれくらい時間を使ったか（Codex の `turns[].started_at` / `completed_at`、Claude の依頼時刻）

1週間分ためて 4 項目が実際に読み取れるかを確かめてから、振り返りの出力の形を決める。それまで出力生成を戻さない。

## テスト

```bash
python3 -m pytest tests/ -v
```

外部パッケージ依存なし（Python 3 stdlib のみ）。

## リポジトリ構成

- `plugins/daytrace/` — 配布単位（git submodule → [daytrace-plugin](https://github.com/matz-d/daytrace-plugin)）
- `plugins/daytrace/.claude-plugin/plugin.json` — plugin manifest
- `plugins/daytrace/skills/daytrace-log/` — 集める・読み出すだけの skill
- `plugins/daytrace/scripts/` — 収集 CLI（`collect_daily.py` / `read_log.py` / source CLI / store / `session_packets.py` / `grouping.py`）
- `ops/launchd/` — 毎日の自動収集の launchd 設定（このマシン用）
- `tests/` — テストスイート（開発リポジトリのみ）。共通の準備用関数は `tests/helpers.py`

## Scripts 規約

- 全 source CLI は Source CLI Contract（`plugins/daytrace/scripts/README.md`）に従う
- source CLI の出力 shape: `{ status, source, events[] }` or `{ status, source, reason/message, events[] }`
- store の `observations.occurred_at` は固定幅の UTC（schema v4 以降）。時刻を比べる値は `common.to_storage_timestamp()` を通す
- 依頼文は `request_text.clean_request_text()` を通し、ツールが差し込んだ文（system-reminder、引き継ぎ要約、AGENTS.md など）を除く
- 外部ネットワーク通信なし

## 日付と保存の規則

- 1日は暦日（ローカル時刻の 0:00〜23:59）。`--date today` / `yesterday`、収集範囲、store の `requested_date` のすべてで同じ
- `collect_daily.py` は今日を集め、前日は「その日が終わった後の file-activity 収集」が保存されるまで取り直す
- store は schema v5。旧パターン提案用の packet（`ai_observation` など）は保存しない
- source が壊れた出力を返しても、その source だけ `error` になり、収集全体は止めない

## リファクタリングの状況

`docs/refactoring-candidates-2026-11-16.md`（Codex の調査）の候補 1〜8 と、外部仕様の変更 3 点は 2026-11-16 にすべて対応済み。
