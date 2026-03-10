# DayTrace 総合レビュー

## 1. 総評（完成度スコアリング）

| 領域 | 評価 | 備考 |
|------|------|------|
| **アーキテクチャ** | ★★★★☆ | 3 層分離が明快。source 追加時の変更は `sources.json` + スクリプト 1 本で完結する設計が良い |
| **コード品質** | ★★★★☆ | 共通契約・エラーハンドリング・graceful degrade が行き届いている。テスト 9 本 all pass |
| **UX / Skill 設計** | ★★★★☆ | SKILL.md の指示精度が高い。plugin-root 解決も明示的。confidence handling が丁寧 |
| **データ品質 / Privacy** | ★★★★☆ | query string 除去を確認済み（URL leak 0 件）。ローカル完結方針が明確 |
| **拡張性** | ★★★★★ | `sources.json` + prerequisites + confidence_category の宣言的設計は MVP として理想的 |
| **審査体験** | ★★★☆☆ | README は合格ラインだが、デモ動画・デモスクリプトが未完成（TODO-E2 が唯一未着手） |
| **テスト** | ★★★☆☆ | aggregator 統合テストは充実しているが、codex/workspace のテストが欠落 |

**全体: Phase 1〜3 の 13 TODO ファイルのうち 12/13 完了。コアは production-ready に近い品質。**

---

## 2. 主要 8 箇所の役割と評価

### ① `sources.json` — ソースレジストリ
**目的:** aggregator がどのソースをどう実行するかを宣言的に定義するカタログ。
**評価:** `prerequisites`（事前チェック条件）と `confidence_category` の追加が秀逸。新 source 追加時の変更範囲は「スクリプト 1 本 + この JSON に 1 エントリ」で完結する。aggregator コード本体の変更が不要なのは拡張性設計として最良。

### ② `common.py` — 共通ユーティリティ (200行)
**目的:** 日時パース、URL サニタイズ、レスポンス構造体、テキスト抽出など全 source が依存する基盤。
**評価:** `sanitize_url`, `sanitize_text`, `extract_text` の多層防御が privacy を支えている。`success_response` / `skipped_response` / `error_response` のファクトリパターンが全 source の出力形式を統一。

### ③ `aggregate.py` — 集約エンジン (549行)
**目的:** source CLI を並列実行し、時系列統合 → グルーピング → confidence 計算 → 中間 JSON 出力。
**評価:** 最大コンポーネント。`ThreadPoolExecutor` による並列実行、preflight summary の stderr 出力、`normalize_event` の堅牢なバリデーション。全て JSON で stdout に出力する設計は SKILL.md から扱いやすい。

### ④ `git_history.py` — Git コミット収集 (159行)
**目的:** `git log --numstat` の出力を DayTrace イベントに変換。
**評価:** `%x1e` / `%x1f` のレコード・フィールド区切りで安全にパース。additions/deletions の統計も含む。workspace がサブディレクトリの場合の pathspec 対応もあり堅実。

### ⑤ `claude_history.py` — Claude 会話履歴 (197行)
**目的:** `~/.claude/projects/**/*.jsonl` を走査し、セッション単位で要約イベントを生成。
**評価:** `isMeta` / `isSidechain` の除外、workspace フィルタ、excerpt の重複排除（最大 3 件）など実践的。`PermissionError` の dedicated handling がある。

### ⑥ `chrome_history.py` — Chrome 閲覧履歴 (167行)
**目的:** Chrome の SQLite DB を一時コピーして読み取り、URL を正規化してイベント化。
**評価:** DB ロック回避のための `/tmp` コピー、複数プロファイル対応、Chrome epoch (1601年) の正しい変換。`collapse_visits` で同一 URL の訪問を集約。

### ⑦ `SKILL.md` (daily-report) — 日報生成スキル定義
**目的:** Claude が aggregate.py の中間 JSON を読んで日報ドラフトを組み立てるための完全な指示書。
**評価:** 最も完成度の高い SKILL.md。Confidence Handling ルール、Graceful Degrade の具体的な空日報テンプレート、Completion Check まで含む。審査員がこれを読めば設計意図が一目で伝わる。

### ⑧ `SKILL.md` (skill-miner) — スキル採掘定義
**目的:** AI 会話履歴から反復パターンを抽出し、5 分類に振り分けてドラフト生成まで行う。
**評価:** aggregator を経由せず直接 source CLI を叩く独自データパスの設計が明文化されている。分類ルール・候補化基準・除外基準が具体的で LLM への指示として高品質。

---

## 3. 発見した問題点（優先度順）

### 🔴 P0: 致命的 / 審査に影響

**a) `--all-sessions` 時の出力が 2.7MB / 推定 70 万トークン**
`skill-miner` は `--all-sessions` で全セッションを投入する設計だが、このサイズは Claude のコンテキストウィンドウを超える。SKILL.md 内に「出力が大きい場合の圧縮戦略」が明示されておらず、実行時にトランケーションやエラーが起きうる。**`--limit` オプションを SKILL.md に組み込むか、aggregate.py 側で段階的要約をかける仕組みが必要。**

**b) `aggregate.py` が正常終了しても exit code 0 で error JSON を返すケース**
`main()` の最外 `except` で `{"status": "error", ...}` を stdout に出力するが `sys.exit(1)` しない。SKILL.md は「aggregate.py を実行して中間 JSON を取得する」としか書いておらず、呼び出し側（Claude）が `status: "error"` を見落とす可能性がある。

**c) `codex_history.py` が `load_history_index` を 2 回呼ぶ（フィルタなし + フィルタあり）**
103〜104 行で同じファイルを 2 回パースしている。大量の Codex 履歴がある場合、不要な二重読み込みが timeout_sec: 30 に引っかかるリスク。

### 🟡 P1: 改善推奨

**d) テストカバレッジの偏り**
`codex_history.py` と `workspace_file_activity.py` のテストが存在しない。特に codex の複雑なセッション結合ロジック（rollout マッピング + history index の突合）がテストなしなのは不安。`git_history.py` の `parse_numstat` もユニットテストがない。

**e) `chrome_history.py` の一時ファイル削除が `finally` 外で漏れうる**
108 行で `tempfile.NamedTemporaryFile(delete=False)` を使い 131 行の `finally` で `unlink` しているが、`shutil.copy2` が失敗した場合（ディスク容量不足等）に空の一時ファイルが残る。実害は小さいが `/tmp` 汚染。

**f) `workspace_file_activity.py` の untracked ファイルが 0 件の場合 `skipped` を返す**
107-117 行: events が空なら `skipped(reason="no_untracked_files")` を返す。`success` で空 events を返すほうが aggregate 側の `source_status_counts` で整合性が取れる（「動いたが結果がなかった」vs「動かせなかった」の区別）。

**g) `PLAN.md` の git_history.sh と実際の git_history.py の不一致**
PLAN.md の File Plan では `scripts/git_history.sh` とあるが、実装は `git_history.py`。審査員が PLAN.md を読んで実装と照らし合わせると混乱する。

### 🟢 P2: あると良い

**h) `.gitignore` が `.DS_Store` のみ**
`__pycache__/`, `*.pyc`, `/tmp/daytrace-*` 等を追加すべき。審査員が clone した際に不要ファイルが見える可能性。

**i) README に英語版がない**
Claude Code Plugin のエコシステムは国際的。審査員が英語話者の場合のリーチが狭い。最低限 description は英語を併記すると良い。

**j) `sources.json` の `codex-history` の prerequisites が `all_paths_exist` で history.jsonl + sessions の両方を要求**
片方しかない環境（例: Codex をインストールしたが一度も使っていない場合 sessions/ だけ空）で unnecessary skip になる。`any_path_exists` 的な柔軟性があるとより graceful。

---

## 4. 提出戦略

### 押し出すべき強み
- **宣言的な source レジストリ (`sources.json`)**: source 追加がコード変更なしで可能な拡張性設計
- **Graceful degrade の徹底度**: source 0 本でも空 JSON で正常終了し、SKILL.md に空日報テンプレートまで用意
- **Preflight summary**: install 直後に何が使えるか一目で分かる stderr 出力
- **Privacy-by-design**: ローカル完結 + URL query string 自動除去（テストで検証済み）
- **3 つの skill が 1 つの集約エンジンを共有する統合体験**: daily-report / post-draft は aggregate.py 経由、skill-miner は直接パスと使い分けが明確

### 素直に limitation として伝えるべきこと
- macOS/Linux のみ（Windows 未検証）
- shell history は未収集（明記済み）
- `--all-sessions` 時の出力サイズがコンテキスト上限に近づく可能性
- skill-miner の「提案→選択→ドラフト」フローは対話的で、完全自動ではない
- デモ動画が未完成

---

## 5. 結論

### 🔥 今このプロジェクトで一番危ない点

**`--all-sessions` 時の出力サイズ（2.7MB / ~70 万トークン）がコンテキストウィンドウを超過する問題。** skill-miner が実際に全セッションを投入すると、Claude が処理できずに truncation やエラーになるリスクが高い。SKILL.md に `--limit` の使用指示を入れるか、source CLI 側で段階的要約を返す仕組みが提出前に必要。

### ✨ 今このプロジェクトで一番光っている点

**`sources.json` を中心とした宣言的 source レジストリ設計。** prerequisites による事前チェック、confidence_category によるグルーピング戦略、platforms によるクロスプラットフォーム制御が全て JSON 宣言だけで完結する。aggregator のコードに source 固有の条件分岐が一切なく、新 source 追加時の変更範囲が最小化されている。ハッカソン作品としてこの拡張性設計は審査員に強い印象を与える。
