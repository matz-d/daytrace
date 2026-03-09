# TODO A. Packaging / Plugin Packaging

Phase: Foundation
Depends on: なし（他と並行可）

## Checklist

- [x] `plugins/hackathon-starter/` を `plugins/daytrace/` にリネームする
- [x] `terminal-vibes` を残すか削除するか決め、不要なら削除する
- [x] `hackathon-starter` 由来の命名・文言・参照先を洗い出す
- [x] `plugins/daytrace/` 配下の plugin 構成を最終形に合わせる
- [x] `.claude-plugin/marketplace.json` の name / description / tags を DayTrace 用に更新する
- [x] `plugins/daytrace/.claude-plugin/plugin.json` の plugin 名・説明・導線を更新する
- [x] `plugins/daytrace/skills/` 配下に `daily-report` / `skill-miner` / `post-draft` の空ディレクトリ + stub SKILL.md を配置する
- [x] root `README.md` から starter / terminal-vibes 系の不要説明を除去する
- [x] README に install 手順、依存関係、初回セットアップ、demo 導線を記載する
- [x] README に審査員向けの最短検証手順を記載する
- [x] packaging 単体で install 可能な状態を確認する

## Done Criteria

- [x] plugin 名がすべて `daytrace` に統一されている
- [x] README だけで install と demo 開始まで辿れる
