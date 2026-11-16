# DayTrace

AI との作業ログを、ローカルに毎日ためる Claude Code plugin の開発リポジトリです。配布用の説明は **`plugins/daytrace/README.md`** を見てください。

## 方針の変更（v0.2.0）

v0.1.x（AIエージェント ハッカソン 2026 提出版）は、ローカルの記録から日報・投稿下書き・パターン提案まで自動で作るものでした。2026-11-12 に実際の 1 日へ当てたところ、出力の前に記録そのものが欠けていることが分かりました。

- Codex の依頼文が取れていなかった（Codex の記録形式の変更に追従していなかった）
- 朝 9 時より前のイベントが、全ソースで時系列から落ちていた（UTC と日本時間の文字列比較）
- Claude の会話は、ツール回数と冒頭の一文しか残っていなかった
- 会話の引き継ぎ要約が、繰り返しのパターンとして数えられていた

そこで v0.2.0 では出力の生成をやめ、ログ収集だけを残して上の欠けを直しました。1 週間分ためて、次の 4 項目が読み取れるかを確かめてから、振り返りの出力を決め直します。

1. 何を頼んだか
2. 何を決めたか・見送ったか
3. どこで手戻りしたか
4. どれくらい時間を使ったか

v0.1.x の実装は git の履歴に残っています。

## 開発

```bash
git clone --recurse-submodules https://github.com/matz-d/daytrace.git
python3 -m pytest tests/ -v
```

追加パッケージは不要です（Python 標準ライブラリのみ）。

```text
plugins/daytrace/      plugin 本体（submodule: daytrace-plugin）
ops/launchd/           毎日の自動収集の launchd 設定
tests/                 テストスイート
docs/                  v0.1.x の設計メモ
```

## License

MIT
