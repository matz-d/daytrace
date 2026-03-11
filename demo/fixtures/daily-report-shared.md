<!-- sample output: /daily-report 共有用 (date-first / Fact & Action) -->

## 日報 2026-03-11

### 今日の概要
- DayTrace の 3 skill を v2.3 framing（date-first / scope-first）に再整理し、README と SKILL.md の整合を取った。

> 注記: Claude/Codex/Chrome はその日全体の証跡、Git とファイル変更は current workspace に限定された証跡です。

### 実装
- `daily-report` / `post-draft` の SKILL.md を `date-first default + optional workspace filter` に更新した。
  - 成果: workspace 未指定でも全日活動が対象になり、workspace は補助フィルタとして機能するようになった。
  - 残課題: 実データでの mixed-scope 注記 wording の最終確認は別途必要。
  - 根拠: git-history のコミット差分, codex-history の編集ログ
  - Confidence: high

### 設計 / 判断
- 3 skill の役割を `Fact & Action` / `Context & Narrative` / `Pattern Extraction` の 3 層として再定義した。
  - 成果: 各 skill の対象スコープと UX の違いが自然に説明できるようになった。
  - 残課題: README の product copy と SKILL.md の整合確認が残っている。
  - 根拠: PLAN_update.v2.md の Cross-Skill Framing, workspace-file-activity の編集痕跡
  - Confidence: high

### 調査
- mixed-scope の説明方針を `sources[].scope` ベースで一意に決定した。
  - 成果: all-day source と workspace source の区別を coverage 誤認なく伝える注記ルールを策定した。
  - 残課題: fixture ベースの review で注記文面を微調整する余地がある。
  - 根拠: aggregate.py の sources[].scope フィールド, chrome-history の調査痕跡
  - Confidence: medium
  - 注記: Chrome 履歴由来の補助情報で、着手の確度は高くない部分を含む。

### 明日のアクション
- demo fixture の wording を実データと突き合わせてレビューする
- README の product copy が 3 分デモのシナリオと一致しているか確認する
- skill-miner の `--all-sessions` と workspace モードの UX 差を審査員向けに整理する
