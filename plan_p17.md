## P17 実装完了

### 現状サマリー

┌────────────────────────────────────────┬────────────────────────┐
│                フェーズ                │          状態          │
├────────────────────────────────────────┼────────────────────────┤
│ hook/agent 分類判定                    │ ✅ 実装済み            │
├────────────────────────────────────────┼────────────────────────┤
│ next_step_stub 生成                    │ ✅ 実装済み            │
├────────────────────────────────────────┼────────────────────────┤
│ proposal.json への埋め込み・提示       │ ✅ 実装済み            │
├────────────────────────────────────────┼────────────────────────┤
│ Hook ファイル生成（.sh + settings.json）│ ✅ 仕様明文化済み      │
├────────────────────────────────────────┼────────────────────────┤
│ Agent ファイル生成（.md）              │ ✅ 仕様明文化済み      │
├────────────────────────────────────────┼────────────────────────┤
│ Decision Writeback（生成後の状態記録） │ ✅ 完了タイミング明記  │
└────────────────────────────────────────┴────────────────────────┘

---

### 実装方針（当初プランからの変更点）

当初案（Python スクリプト 2本 + テスト 2本）は採用せず。

**理由:**
- hook/agent の生成は Claude が Write/Bash ツールで直接行う（references がその手順書）
- cross-repo の場合は handoff JSON を Write で生成してユーザーに案内する
- Python スクリプト化は設計の一貫性を損なう（hook-creation-guide.md はスクリプト経由を前提にしていない）

---

### 変更ファイル（2本）

**変更: `skills/skill-applier/references/hook-agent-nextstep.md`**
- Workspace チェックと生成パスを追加
  - 同一 repo → Claude が Bash/Write で直接生成する手順（mkdir, Write .sh, chmod, merge settings.json / Write .md）
  - cross-repo → handoff JSON を Write で生成し、ユーザーに対象 repo での実行を案内

**変更: `skills/skill-applier/SKILL.md`**
- Detail/Draft Rules に workspace チェックの一行を追加
- Decision Writeback の完了タイミングを明記（同一 repo: ファイル書き込み完了時 / cross-repo: handoff JSON 生成完了時）
- Completion Check を cross-repo ケースに対応した記述に更新
