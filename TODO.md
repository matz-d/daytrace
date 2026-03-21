**実装タスクリスト**

**Phase 1: 即修正**
- [x] `proposal.md` の header count bug を修正する
- [x] `ready / total / needs_research / rejected` の件数算出元を確認する
- [x] `候補合計: 0 | ready: 7件` のような不整合を再現テストで固定する
- [x] `report-private` 用の根拠ルールに negative example を追加する
- [x] `Codex session in /Users/...` のような実パス混じり根拠を禁止する
- [x] `daytrace-session` の completion check に「英語の内部思考・shell log が chat に出ていない」を追加する
- [x] internal reasoning / shell trace が chat に出ないことを確認する

**Phase 1 完了条件**
- [x] header count の不整合が直っている
- [x] private report に実パス混じり根拠が出ない
- [x] chat に `Continuing autonomously` や shell 実行ログが出ない

**Phase 2: Label 設計**
- [x] `candidate_label()` の現状生成ルールを整理する
- [x] action-oriented label の仕様を決める
- [x] raw 発話断片ではなく「適用すると何ができるか」ベースの命名規則を定義する
- [x] label 変更が `decision_key` に与える影響を整理する
- [x] label 変更が `content_key` に与える影響を整理する
- [x] carry-forward を壊さない migration 方針を決める（Python `label` を identity key として固定し、LLM が表示専用の `display_label` を生成する方針に決定）
- [x] compact 表と proposal 本文で同じ label を使うか分けるか決める（両方 `display_label` を使う）
- [ ] selection prompt の文言も新 label 前提で見直す（Phase 6 で対応）

**Phase 2 完了条件**
- [x] label 生成ルールが文章で明文化されている（`skill-miner/SKILL.md` Display Label Rules セクション）
- [x] `decision_key/content_key` への影響が説明できる（`proposal-json-contract.md` 補足に追記）
- [x] proposal / compact 表 / handoff の label 方針が一致している

**Phase 3: Chat 境界の確立**
- [x] chat output policy を明文化する（`daytrace-session/SKILL.md` の `## Chat Output Policy` セクション）
- [x] chat は semi-final summary のみを出す方針を固定する
- [x] final artifact 本文を chat にそのまま流さないルールを入れる（禁止リストに明記）
- [x] source 収集結果、ダイジェスト、提案要約、選択 prompt、完了要約だけを chat に残す（positive list）
- [x] internal trace を完全に非表示にする（禁止リストに `Continuing autonomously`・shell ログ・英語内部推理を明記、Completion Check に追加）
- [x] source 名正規化の mapping table を作る（Chat Output Policy「Source 名の正規化」テーブル）
- [x] `codex-history`, `claude-history`, `chrome-history`, `git-history`, `workspace-file-activity` の表示名を決める

**Phase 3 完了条件**
- [x] chat に出すもの / 出さないものが固定されている
- [x] source 名の表示が揺れない
- [x] chat と file の責務分離が説明できる

**Phase 4: Formatter Contract**
- [x] final formatter の責務を定義する
- [x] 機械的変換と意味変換を分離する
- [x] 機械的変換を Python 側でやる項目を決める
- [x] path sanitize の仕様を決める
- [x] source 名正規化の適用位置を決める
- [x] 禁止語置換の適用位置を決める
- [x] Mixed-Scope 注記の挿入位置を決める
- [x] footer の挿入位置を決める
- [x] 意味変換を SKILL.md 側でやる項目を決める
- [x] 事実/推測の監査ルールを定義する
- [x] formatter の入出力 shape を定義する

**Phase 4 完了条件**
- [x] formatter contract が文書化されている
- [x] Python でやることと LLM でやることが分かれている
- [x] report / post-draft / proposal に同じ contract を適用できる

**Phase 5: Cross-Repo Handoff**
- [x] handoff schema v2 を定義する
- [x] `cross_repo` フィールドを追加する
- [x] `target_workspace_hint` フィールドを追加する
- [x] `target_repo_kind` または同等のヒント項目を追加する（`handoff_scope` + `target_repo_display_name` で代替）
- [x] `run /skill-creator in target repo` の指示項目を追加する（`execution_instruction` / `presentation_block`）
- [x] proposal 上で cross-repo 候補と分かる表示を追加する
- [x] handoff JSON の重複書き込み対策を決める
- [x] 同一 candidate の handoff を dedup する方針を決める
- [x] cross-repo skill 候補の UX 文言を作る

**Phase 5 完了条件**
- [x] 別 repo 用 skill 候補を proposal 上で見分けられる
- [x] handoff JSON だけ見て実行場所が分かる
- [x] 同一 handoff の重複生成が抑制される

**Phase 6: Proposal UX**
- [x] proposal の候補名を新 label 仕様に切り替える
- [x] raw 発話断片ベースの候補表示をやめる
- [x] `何を / なぜ / 適用後どうなるか` が分かる概要にする
- [x] 確度説明を候補固有にする
- [x] selection prompt を即適用ベースに変える
- [x] 「選ばなかった候補も保持される」を prompt に含める
- [x] 将来の複数選択対応を見据えた wording にする

**Phase 6 完了条件**
- [x] proposal 一覧だけ見て候補の違いが分かる
- [x] 選択 prompt が弱くない
- [x] carry-forward の安心感が prompt に出ている

**Phase 7: Wording Polish**
- [x] `report-share` の内部用語を意味ベースへ置換する
- [x] `classification refresh plan` を共有向け表現へ変換する
- [x] `output-polish` を共有向け表現へ変換する
- [x] `post-draft` の背景を短縮する
- [x] 投稿下書きの冒頭を「今日何を変えて何が分かったか」から始める
- [x] 禁止語リストを追加する
- [x] 禁止語に対するテストを追加する

**Phase 7 完了条件**
- [x] 共有用日報に内部開発用語が残らない
- [x] post-draft が本題に早く入る
- [x] 禁止語が再発しにくい

**最終確認**
- [ ] chat output が semi-final summary に収まっている
- [ ] final artifact が保存物として読める品質になっている
- [x] proposal / handoff / report / post-draft の責務分離ができている
- [x] cross-repo skill 候補の運用がユーザーに伝わる
- [x] carry-forward を壊していない
- [x] 回帰テストを通している

必要なら次に、これをそのまま issue 化しやすいように **1チケット1タスク単位** に分解します。
