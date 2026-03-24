調査結果を整理します。

  現状サマリー

  ┌────────────────────────────────────────┬────────────┐
  │                フェーズ                │    状態    │
  ├────────────────────────────────────────┼────────────┤
  │ hook/agent 分類判定                    │ ✅         │
  │                                        │ 実装済み   │
  ├────────────────────────────────────────┼────────────┤
  │ next_step_stub 生成                    │ ✅         │
  │                                        │ 実装済み   │
  ├────────────────────────────────────────┼────────────┤
  │ proposal.json への埋め込み・提示       │ ✅         │
  │                                        │ 実装済み   │
  ├────────────────────────────────────────┼────────────┤
  │ Hook ファイル生成（.sh +               │ ❌ 欠落    │
  │ settings.json）                        │            │
  ├────────────────────────────────────────┼────────────┤
  │ Agent ファイル生成（.md）              │ ❌ 欠落    │
  ├────────────────────────────────────────┼────────────┤
  │ Decision Writeback（生成後の状態記録） │ ⚠️ 部分    │
  └────────────────────────────────────────┴────────────┘

  設計仕様（hook-creation-guide.md, agent-creation-guide.md,
   hook-agent-nextstep.md）は既に完備。**「仕様はある、実装
  がない」**という状態です。

  ---
  P17 実装プラン（案）

  Step 1: skill-applier/SKILL.md — hook/agent 生成フロー追記

  kind: hook / kind: agent
  を受け取ったときの実行ステップを、既存の CLAUDE.md apply
  パスに倣って明文化。

  Step 2: Python スクリプト新規実装（2本）

  scripts/hook_generator.py    next_step_stub → .sh +
  settings.json マージ
  scripts/agent_generator.py   next_step_stub → .md（YAML
  frontmatter + system prompt）
  LLM 直接生成ではなく Python にする理由：settings.json
  マージは edge case が多く、deterministic に扱いたいため。

  Step 3: Decision Writeback 補完

  hook/agent 生成完了後に decision_log へ completion_state:
  completed を書き戻す処理を追加。

  Step 4: テスト追加

  tests/test_hook_generator.py
  tests/test_agent_generator.py
  settings.json の既存キー保護・上書き確認フロー・YAML
  フロントマター検証など。

  ---
  変更ファイル数: SKILL.md 1本 + Python 2本 + テスト 2本 =
  合計 5ファイル（新規2、変更1、テスト2）

  このプランで進めますか？あるいは実装方式（Python vs
  LLM直接）など変えたい点があれば先に合わせます。

このプランで問題がないか要チェック