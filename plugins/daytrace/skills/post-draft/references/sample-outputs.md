# Sample Outputs

各フォーマットの出力例。下書き生成時の粒度・トーンの参考として使う。

## Sample: `tech-blog`

```markdown
# DayTrace の source CLI をまとめる aggregator を実装した話

## 導入
今日は DayTrace の集約レイヤーを実装し、複数のローカル証跡を 1 つの中間 JSON に統合できる状態まで進めた。

## 今日やったこと
`sources.json` を起点に source CLI を並列実行する `aggregate.py` を追加した。`git-history`、`claude-history`、`codex-history`、`chrome-history`、`workspace-file-activity` の結果を正規化して、時系列の `timeline` と近接イベントの `groups` にまとめるようにした。

## 詰まった点 / 工夫した点
source ごとの成功・スキップ・エラーの shape が違うため、aggregator 側で統一した。Chrome や履歴系 source が欠けても全体が止まらないようにしている。

## 学び
実際の出力スキルを作る前に、中間 JSON の shape を固定したのが効いた。後段の daily-report や post-draft は `groups` と `sources` を読むだけで済む。

## 次にやること
daily-report と post-draft の SKILL.md を仕上げて、出力層をつなぐ。
```

## Sample: `team-summary`

```markdown
## Team Summary

- 今日の進捗: aggregator 本体を追加し、5 source の統合 JSON を返せるようにした
- 主な証拠: `aggregate.py`、stub 結合テスト、5 source 実行確認
- 未解決: Chrome 起動中ロック状態での読取確認は未完了
- 次のアクション: daily-report と post-draft の出力設計を固める
```

## Sample: `slack`

```markdown
今日の進捗メモです。
- DayTrace の aggregator を実装して、5 source を 1 つの JSON に統合できるようにしました
- `success / skipped / error` の正規化と近接イベントのグルーピングまで入っています
- 次は daily-report / post-draft の出力層を仕上げます
```
