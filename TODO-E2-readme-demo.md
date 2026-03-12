# TODO E2. Demo-Centered Submission Assets

Phase: Polish & Submit
Depends on: E1（judge install で動作確認が取れてから最終化）

## 役割分担（TODO-E2b との関係）

- **TODO-E2b**（完了）: README の product copy（3 skill framing, workspace semantics, mixed-scope 説明）と live 検証導線の整備
- **TODO-E2**（このファイル）: 提出用デモを主役に据えた見せ方、README の最終トーン調整、撮影素材の整備

## Goal

README を「審査員専用 LP」に寄せすぎず、配布物として自然な使い方の説明を維持する。
一方で、価値訴求の主戦場は 3 分以内の提出デモに置き、DayTrace を「ローカル証跡から複数成果物を自律的に作る agent workflow」として見せる。

## Non Goals

- README 全体を審査員向け landing page に作り替えること
- 英語説明を全面的に増やすこと
- 固定 `demo/` fixture や canned output を追加すること
- graceful-degrade の失敗パターンを本編デモの主役にすること

## Checklist

- [x] README は配布物としての説明を維持しつつ、冒頭 3-6 行だけ価値がすぐ伝わる形に整える
  - local-first / zero-config / graceful-degrade / 3-in-1 の主価値は冒頭で触れる
  - 本文は引き続き通常利用者向けの使い方・制限事項・検証導線を中心にする
  - 審査員専用の長い売り文句や過剰な演出は足さない
- [x] README の英語は最小限に留める
  - 追加する場合も冒頭の短い summary だけに限定する
  - 本編の日本語ドキュメント構成は崩さない
- [x] 提出デモの主メッセージを「同じローカル証跡から複数成果物を自律的に生成する」に固定する
  - 3 つの skill をただ順番に流すのではなく、同じ観測結果から分岐する流れとして見せる
  - `aggregate.py` を観測の入口として置く
  - 最後は `skill-miner` の `CLAUDE.md` immediate apply を差別化ポイントとして締める
- [x] デモシナリオを 3 分以内に固定する
  - 自分のパソコン上の実データで撮る
  - source が十分ある成功版を正式提出素材にする
  - 1 セッション内で aggregate と 3 skill の流れがつながって見える台本にする
- [x] 「一括実行で自律的に動いている」印象を出す撮り方を整える
  - 必要なら 1 つの依頼文から複数成果物に展開する流れに寄せる
  - 単なる 3 コマンドの羅列に見えないよう、観測→再構成→提案のつながりを字幕またはナレーションで補う
- [x] graceful-degrade / source 欠損パターンは補助素材として別管理する
  - 本編では 1 カット以内に留めるか、参考資料に回す
  - 「できなかった時の挙動」は録画メモまたは補足スライド相当の素材として残す
- [x] デモスクリプトを手順書として残す
  - 開始前の端末状態、実行コマンド、話す要点、詰まった時の言い換えを含める
- [ ] 動画撮影または録画手順のリハーサルを行う
  - 3 分以内に収まるか確認する
  - 画面上で source preflight、3 outputs、`CLAUDE.md` diff/apply が判読可能か確認する

## Done Criteria

- [x] README は配布物として自然な説明を保ちつつ、冒頭だけで主価値が伝わる
- [x] 3 分デモ動画の台本・撮影素材・補助メモが揃っている
- [x] 本編デモが「自律的エージェントとしての一連の流れ」に見える
- [x] graceful-degrade / source 欠損時の補助素材が別途参照できる
