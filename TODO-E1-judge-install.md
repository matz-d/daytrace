# TODO E1. Judge Install / Environment Validation

Phase: Polish & Submit
Depends on: E3（hardening で致命的バグを潰してから）

## Checklist

- [ ] ソースが少ないマシンを想定した検証ケースを定義する
- [ ] install 直後の利用可能ソース検出表示を確認する
- [ ] source 0 本、1 本、複数本のケースで実行確認する
- [ ] 権限不足、履歴不在、DB lock の挙動を確認する
- [ ] graceful degrade の実例をスクリーンショットまたはログで残す

## Done Criteria

- [ ] クリーン環境相当で install → 実行が再現できる
- [ ] source 欠損があっても審査で説明可能な状態になっている
