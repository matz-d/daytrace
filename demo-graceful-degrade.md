# DayTrace Graceful Degrade — 補助素材

本編デモでは source が揃った成功版を使用する。
このドキュメントは、source 欠損時の挙動を別途参照するための補助素材。

## source 欠損パターン一覧

| パターン | 利用可能 source | aggregate の挙動 | skill への影響 |
|----------|---------------|-----------------|---------------|
| フル | git + claude + codex + chrome + file | 全 source 成功 | 全 skill フル出力 |
| AI 履歴なし | git + chrome + file | claude/codex が `skipped` | daily-report/post-draft は Git + Chrome 中心に縮退 |
| Git なし | claude + codex + chrome | git-history/file-activity が `error` | daily-report は AI 履歴中心、skill-miner は通常動作 |
| Chrome なし | git + claude + codex + file | chrome が `skipped` | ほぼ影響なし（Chrome は補助ソース） |
| 全 source なし | なし | `no_sources_available: true` | 空結果で正常終了 |

## 確認手順

### 1. preflight で状態を確認

```bash
python3 plugins/daytrace/scripts/aggregate.py --date today 2>&1 | grep "Source preflight"
```

出力例:
```
Source preflight: available=[git-history, claude-history] unavailable=[codex-history, chrome-history] skipped=[workspace-file-activity]
```

### 2. 欠損時の aggregate 出力

```bash
python3 plugins/daytrace/scripts/aggregate.py --date today 2>/dev/null | python3 -m json.tool | head -30
```

確認ポイント:
- `sources[]` の各エントリに `status` が入っている（`success` / `skipped` / `error`）
- `summary.no_sources_available` が `true` の場合、`timeline` と `groups` は空配列
- エラーで中断せず JSON が正常出力される

### 3. skill ごとの縮退挙動

| skill | 全 source 欠損時 | 一部欠損時 |
|-------|----------------|-----------|
| daily-report | 「本日の証跡は見つかりませんでした」相当の空日報 | 利用可能な source の証跡だけで日報を生成。coverage note あり |
| post-draft | 最小構成の narrative（「本日は記録された活動がありませんでした」等） | 利用可能な証跡から topic を選び draft 生成 |
| skill-miner | 候補 0 件で正常完了 | 利用可能な履歴から候補を抽出 |

## 録画メモ（本編デモへの組み込み方）

- 本編デモでは source 欠損パターンを主役にしない
- 本編中に 1 カット以内で触れる場合の台詞例:
  - 「source が足りない環境でも、利用可能な証跡だけで動作します」
  - preflight の `unavailable=` 行を一瞬見せて次に進む
- 詳細な欠損パターンの紹介が必要な場合は、このドキュメントを参考資料として提示する
