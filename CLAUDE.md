# DayTrace

ローカル証跡を集約し、日報・スキル提案・投稿下書きを自動生成する Claude Code plugin。

## テスト

```bash
python3 -m pytest tests/ -v
```

外部パッケージ依存なし（Python 3 stdlib のみ）。

## リポジトリ構成

- `plugins/daytrace/` — 配布単位（git submodule → [daytrace-plugin](https://github.com/matz-d/daytrace-plugin)）
- `plugins/daytrace/.claude-plugin/plugin.json` — plugin manifest
- `plugins/daytrace/skills/` — 5 skill（daily-report, daytrace-session, skill-miner, skill-applier, post-draft）
- `plugins/daytrace/scripts/` — 共通 CLI + skill-miner 専用 CLI
- `tests/` — テストスイート（開発リポジトリのみ）
- `design-notes/` — 設計メモ（開発リポジトリのみ）

## Skill 設計規約

- SKILL.md は 500 行以内に収める
- 詳細仕様・出力例・判定ルールは `references/` に分離し、SKILL.md からポインタで参照する
- description にはトリガーフレーズ（ユーザーが実際に使う言い回し）を含める

## Scripts 規約

- 全 CLI は Source CLI Contract（`plugins/daytrace/scripts/README.md`）に従う
- source CLI の出力 shape: `{ status, source, events[] }` or `{ status, source, reason/message, events[] }`
- aggregate.py の出力 shape: `{ sources[], timeline[], groups[], summary }`
- 外部ネットワーク通信なし
