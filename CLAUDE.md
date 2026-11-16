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
- `plugins/daytrace/scripts/` — 収集 CLI（`collect_daily.py` / `read_log.py` / source CLI / store）
- `ops/launchd/` — 毎日の自動収集の launchd 設定（このマシン用）
- `tests/` — テストスイート（開発リポジトリのみ）

## Scripts 規約

- 全 source CLI は Source CLI Contract（`plugins/daytrace/scripts/README.md`）に従う
- source CLI の出力 shape: `{ status, source, events[] }` or `{ status, source, reason/message, events[] }`
- store の `observations.occurred_at` は固定幅の UTC（schema v4）。時刻を比べる値は `common.to_storage_timestamp()` を通す
- 依頼文は `request_text.clean_request_text()` を通し、ツールが差し込んだ文（system-reminder、引き継ぎ要約、AGENTS.md など）を除く
- 外部ネットワーク通信なし

## 既知の残課題

- `skill_miner_common.py` は旧パターン提案の共有部品で、収集（会話のまとまり分け）が一部を使っている。収集に要る部分だけに切り出す
- store のイベントには旧パターン提案用の `skill_miner_packet` が入ったままで、容量が大きい（約 1GB）
- 収集の日付範囲は暦日（0:00〜23:59）、「今日」の判定は朝 6 時区切りで、境界がずれている
