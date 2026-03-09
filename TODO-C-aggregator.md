# TODO C. Aggregator / activity-aggregator

Phase: Foundation
Depends on: なし（最初の 1 項目は B1-B5 より先に着手する）

## Checklist

### 先行タスク（B1-B5 より前に完了させる）

- [ ] source CLI 共通の入出力契約を文書化する（共通フィールド: source, timestamp, type, summary, details, confidence。`details` は必須の自由形式）
- [ ] `scripts/sources.json` にソース一覧を定義する（最低限: name, command, required, timeout_sec, platforms, supports_date_range, supports_all_sessions）

### 本体タスク（B1-B5 と並行 or 後で進める）

- [ ] `sources.json` を読んで実行対象を決定するランナーを実装する
- [ ] source CLI を並列実行する仕組みを実装する
- [ ] `success` / `skipped` / `error` を正規化して統合する
- [ ] 共通イベント形式へのマージ処理を実装する
- [ ] タイムスタンプ順ソートを実装する
- [ ] 近接イベントグルーピングを実装する（閾値はスクリプト冒頭の定数で調整可能にする）
- [ ] `evidence` と `confidence` の付与ルールを実装する（ルールもスクリプト冒頭で調整可能）
- [ ] source 0 本でも空タイムラインで正常終了するようにする
- [ ] 中間 JSON を output skill から再利用できる形式に固定する
- [ ] CLI stub を使った結合テストを作る

## Done Criteria

- [ ] 5 source の結果を 1 つの中間 JSON に統合できる
- [ ] source 欠損や失敗があっても全体が止まらない
- [ ] 新しいソースを `sources.json` に追加するだけで aggregator が認識する
- [ ] `sources.json` の最小 schema だけで実行モード判定とタイムアウト制御ができる
