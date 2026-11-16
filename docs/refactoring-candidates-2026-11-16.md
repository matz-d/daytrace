最優先は、**`skill_miner_common.py` の未到達関数 135 個の削除**です。ただし、現在の収集は旧 packet 生成にも依存しており、同ファイル全体の削除や packet の生成停止は、振る舞いを維持するリファクタリングには含められません。

ファイルは変更していません。`CLAUDE.md`、scripts の README・全 Python モジュール・`sources.json`、tests、および workspace-agent 側の呼び出しを確認しました。

指定のテストコマンドは、`PYTHONDONTWRITEBYTECODE=1` を付けて実行しましたが、サンドボックス内に書き込み可能な一時ディレクトリがなく、**テスト開始前に停止**しました。105 個のテスト定義は確認しましたが、今回の調査で成功を再確認できたわけではありません。

**優先順位付きリスト**

評価の「安全性」は、既存の振る舞いを維持して変更できる見込みです。

| 順位 | 候補 | 保守性の改善 | バグリスク低減 | 安全性 |
|---|---|---|---|---|
| 1 | 未到達の旧 skill-miner コードを削除 | 高 | 中 | 高 |
| 2 | テスト fixture の重複整理と互換性の保護 | 高 | 高 | 高 |
| 3 | Claude/Codex 収集の責務分離・命名整理 | 高 | 高 | 中 |
| 4 | aggregate の実行制御とグループ生成を分離 | 高 | 高 | 中 |
| 5 | store の packet 互換処理と永続化処理を分離 | 中 | 高 | 中 |
| 6 | Git workspace 解決処理を共通化 | 中 | 中 | 高 |
| 7 | 日次収集の実行計画と結果整形を分離 | 中 | 中 | 高 |
| 8 | Chrome の DB 読み取りとイベント構築を分離 | 中 | 中 | 高 |

1. **未到達の旧 skill-miner コードを削除**

   **対象:** [skill_miner_common.py](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/skill_miner_common.py:2273) の後掲 135 関数。

   **現状・改善方針:** 収集から使われない候補評価、分類、提案 Markdown、skill 作成引き継ぎ、CLAUDE.md 適用処理が残っています。2273 行目以降の 124 関数と、それ以前に散在する 11 関数を削除対象にできます。専用の定数、`SkillScaffoldContext`、不要になる import も参照確認のうえ整理します。

   **優先理由:** 大きなコード量を減らせ、現在の収集処理との境界も明確です。一方、到達する 65 関数と、その定数・正規表現は保持が必要です。特に `build_packet()` に使われる特徴量推定を「旧機能だから」と削除すると、イベント内容が変わります。

   **テスト:** 未到達 135 関数への直接参照は tests にもありません。残す処理は Claude/Codex の CLI テストで部分的に保護されていますが、packet 全体の値・配列順序を固定する比較が不足しています。

2. **テスト fixture の重複整理と互換性の保護**

   **対象:** [test_aggregate.py](/Users/makotomatuda/projects/lab/daytrace/tests/test_aggregate.py:23)、`test_aggregate_contracts.py`、`test_store.py`、`test_derived_store.py` の `write_file()`・`make_source_entry()`・CLI 実行補助、各 fixture。

   **現状・改善方針:** 同じ manifest 作成関数が 4 ファイルに複製され、source stub の長い文字列も繰り返されています。小さなテスト補助モジュールに、manifest 作成・JSONL 書き込み・CLI 実行だけをまとめます。期待する JSON はテスト側に残し、本番の出力生成関数から期待値を作らない構成が適切です。

   **優先理由:** 後続のリファクタリングで fixture の修正漏れを減らせます。実施時は、順位 1・3・5 の変更前に不足する互換テストを補う順番を推奨します。

   **テスト:** aggregate の CLI 引数・主要 JSON 契約は比較的充実しています。不足は、実際の Claude/Codex 名を使った packet 保存、packet 全体の比較、`read_log --format text`・source フィルター・同一イベントの読み出し重複排除です。`test_cli_reads_user_message_items_and_turns_without_history_file` は、実際には**空の history ファイルを作成**しており、名前の修正も必要です。

3. **Claude/Codex 収集の責務分離・命名整理**

   **対象:** [claude_history.main()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/claude_history.py:116)、[codex_history.main()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/codex_history.py:195)、`build_claude_logical_packets()`、`build_codex_logical_packets()`、`build_packet()`。

   **現状・改善方針:** `main()` はそれぞれ 253 行・318 行あり、ファイル探索、JSONL 読み取り、範囲判定、packet 集約、イベント構築を担当しています。「読み取り」「会話分割」「packet の直列化」「イベント構築」に関数を分けます。会話分割と旧 packet 互換生成は、少数の用途別モジュールへ移せます。Codex の同じ packet 初期化辞書 3 箇所も、小さな生成関数にまとめられます。

   **命名上の注意:** `claude_history.py` は import した `claude_message_text()` を同名のローカル関数で上書きしています。両者は同一ではなく、ローカル版は text を優先し、共有版は thinking や tool call も連結します。依頼文用・packet 用と分かる名前に変更し、既存の差を保持する必要があります。`clean_request_text()` と `clean_user_message_text()` も目的が異なるため、単純統合には向きません。

   **優先理由:** 日常の収集に直結し、新しいログ形式への対応時に影響範囲を限定できます。ただし Claude はレコード段階、Codex は主に packet 段階で日付を絞るなどの違いがあり、安全性は中としました。

   **テスト:** workspace 切り替え、pivot、注入文除去、Codex の新旧 UserMessage、明示的な tool result、日付絞り込みは保護されています。不足は 8 時間境界、sidechain 境界、text/thinking/tool 混在、call ID がない結果の対応付け、packet 全体の同値比較です。

4. **aggregate の実行制御とグループ生成を分離**

   **対象:** [aggregate.main()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/aggregate.py:51)、`aggregate_core.py` の `run_source()`、preflight 関数群、[build_groups()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/aggregate_core.py:697)。

   **現状・改善方針:** `aggregate_core.py` に日付、コマンド構築、preflight、並列実行、正規化、グループ生成が集まっています。source 実行とグループ生成を分離し、137 行の `build_groups()` は「範囲を区切る」「グループ情報を構築する」に分けます。`browser_context` はグループ構築と share policy 内で二重計算されており、一度の計算結果を渡せます。

   **優先理由:** 外部利用される中心処理なので、責務分離の効果が大きい一方、変更を小刻みに進める必要があります。`timeline` のイベントに `group_id` を付与する副作用、evidence の順位、`share_policy` も現在の出力として保持します。

   **テスト:** [test_aggregate_contracts.py](/Users/makotomatuda/projects/lab/daytrace/tests/test_aggregate_contracts.py:314) が引数転送・主要 shape・group ID・summary を、`test_aggregate_core.py` が max span・scope・evidence・共有判定を保護しています。文脈による分割、イベント confidence による上限制御、イベントオブジェクトの共有を明示するテストが不足しています。`…are_pure` というテスト名も、入力への `group_id` 付与を表していません。

5. **store の packet 互換処理と永続化処理を分離**

   **対象:** [store._packet_observation_events()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/store.py:220)、`_replace_observations()`、`persist_source_result()`、[derived_store.get_observations()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/derived_store.py:395)。

   **現状・改善方針:** 旧・新 packet フィールドの選択、packet イベントへの変換、重複排除、JSON 化、SQL 書き込みが近接しています。packet 互換変換と observation 行の構築を、小さな純粋関数として分離します。読み出しも、条件構築と SQL 実行・行復元の境界を明確にします。

   **優先理由:** 容量削減とは分けて、既存データ互換を守る境界を作れます。fingerprint の入力・canonical JSON・schema v4・UTC 固定幅・読み出しの選択順序は維持が必要です。また、aggregate を既存の `persist_source_results()` に単純置換すると、現在の source ごとの保存失敗への耐性を変える可能性があります。

   **テスト:** 保存・再実行時の件数・v2→v4 移行・壊れた JSON・UTC 日付境界は保護されています。一方、store fixture の AI source 名は主に `ai-source` で、`AI_HISTORY_SOURCES` の packet 展開分岐を通りません。packet の別名・重複・Claude/Codex の fallback 差、保存途中失敗時の rollback、v1/v3 からの移行が不足しています。

6. **Git workspace 解決処理を共通化**

   **対象:** [git_history.repo_context()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/git_history.py:62)、[workspace_file_activity.repo_context()](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/workspace_file_activity.py:37)。

   **現状・改善方針:** この 2 関数は AST 比較でも同一です。小さな Git 共通関数にまとめ、返却する `(repo_root, pathspec)`、10 秒 timeout、例外の伝わり方を維持します。preflight の `git_repo_available()` は必要な結果が異なるため、共通化するならコマンド実行部分までが適切です。

   **優先理由:** 改善範囲は小さいものの、差分が小さく安全に重複を解消できます。

   **テスト:** 非 Git ディレクトリ、workspace 内の commit・未追跡ファイル、Git timeout は既存テストがあります。repo 直下・入れ子 workspace・解決失敗の共通関数テストが不足しています。

7. **日次収集の実行計画と結果整形を分離**

   **対象:** [collect_daily.py](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/collect_daily.py:34) の `has_stored_snapshot()`・`collect()`・`main()`、`read_log.py` の `read_timeline()`・`text_lines()`。

   **現状・改善方針:** `collect()` が subprocess 実行、JSON 解釈、source 結果の縮約、store error 判定を担当しています。コマンド構築と結果解釈を分け、収集対象日の決定も「現在時刻と昨日の保存状況→日付一覧」の関数にします。`read_log.py` 自体は 82 行で責務も比較的明確なので、主眼はテスト補強です。

   **優先理由:** launchd 入口の判断を読みやすくでき、時刻依存テストも安定します。6 時境界など現在の日付規則は、そのまま保持できます。

   **テスト:** 現在は「昨日を初回だけ収集し、その後は今日だけ」という統合テスト 1 件が中心です。source の skipped/error、保存失敗、JSON 解釈失敗、6 時前後、text 出力の保護が不足しています。timeout を JSON エラーへ変更する修正は、後述の仕様判断に分けます。

8. **Chrome の DB 読み取りとイベント構築を分離**

   **対象:** [chrome_history.py](/Users/makotomatuda/projects/lab/daytrace/plugins/daytrace/scripts/chrome_history.py:205) の `main()`・`compress_visit_flows()`。

   **現状・改善方針:** `main()` が一時 DB コピー、接続、SQL、期間判定、圧縮、イベント構築を担当しています。profile ごとの読み取りを関数化し、例外時にも接続を閉じる構造にします。圧縮ロジックは独立したまま、イベント構築だけを取り出せます。

   **優先理由:** 資源管理と加工処理を分ける効果がありますが、既に主要変換が関数化されているため順位は下げました。

   **テスト:** 複数 profile、URL 正規化、同一 URL 集約、login flow 圧縮は保護されています。DB 読み取り失敗時の close・一時ファイル削除、圧縮の時間境界、空データが不足しています。`normalize_url()` と `common.sanitize_url()` は不正 URL 時の例外方針が異なり、そのまま置換すると振る舞いが変わります。

**`skill_miner_common.py` の到達性と削除候補一覧**

入口からの主な経路は次のとおりです。

```text
collect_daily.main
  → collect
  → aggregate.py（subprocess）
      → collect_source_results → run_source
          → sources.json の5 source CLI

read_log.main
  → read_timeline → derived_store.get_observations

claude_history.main
  → build_claude_logical_packets
  → build_claude_session_ref / build_packet / head_tail_excerpts
  → collect_user_requests → claude_message_is_tool_result_only

codex_history.main
  → build_codex_logical_packets
  → build_codex_session_ref / build_packet / head_tail_excerpts
  → earliest_iso_timestamp
  → extract_codex_turns → codex_user_message_text
```

関数呼び出しだけでなく、`key=compare_iso_timestamps` のような関数参照やネスト関数内の呼び出しも辿りました。対象は現在の入口と bundled source CLI であり、将来の任意の drop-in source まで未使用を保証するものではありません。

結果は、**トップレベル関数 200 個中、到達 65 個・未到達 135 個**です。以下は未到達の全件です。各群に呼び出し元の根拠を付記します。

**A. 前半に散在する 11 関数**

```text
_candidate_text_list
jaccard_score
overlap_score
normalize_primary_intent
packet_user_repeated_rules
packet_user_rule_hints
packet_assistant_repeated_rules
packet_assistant_rule_hints
skill_miner_packet_is_v2
parse_session_ref
load_jsonl
```

呼び出し元は、`_candidate_text_list ← build_research_brief 等`、`jaccard_score ← build_candidate_quality / judge_research_candidate 等`、`packet_user_rule_hints ← stable_block_keys`。いずれも未到達側です。残る 8 関数には、調査対象の Python コード内に呼び出し元がありません。

**B. 候補作成・評価・調査の 18 関数（2273–2865 行）**

```text
candidate_label
candidate_sort_key
packet_sort_key
stable_block_key
stable_block_keys
candidate_score
build_candidate_quality
infer_suggested_kind
annotate_unclustered_packet
build_research_targets
build_research_brief
build_detail_signal
_dominant_value_share
_split_shape_groups
_average_token_overlap
_build_subcluster_triage
_candidate_detail_refs
judge_research_candidate
```

呼び出し関係の根拠は、`_materialize_split_candidates → candidate_label`、`stable_block_key → stable_block_keys`、`judge_research_candidate → build_detail_signal / _split_shape_groups / _build_subcluster_triage` などです。候補評価・調査の入口自身に収集側からの呼び出しがありません。

**C. ルール・分類処理の 31 関数（2868–3267 行）**

```text
_normalize_rule_line
_split_section_lines
_find_daytrace_section
_extract_existing_rule_lines
_rule_polarity
_is_conflicting_rule
_is_duplicate_rule
_normalize_proposed_rules
infer_suggested_kind_details
_candidate_task_shapes
_candidate_artifact_hints
_candidate_rule_hints
_candidate_tool_signatures
_candidate_total_packets
_candidate_intent_lines_for_role
_line_matches_agent_role_signal
_candidate_has_agent_role_consistency_signal
_declarative_weight_for_claude_md
_workflow_weight_for_claude_md
_claude_md_declarative_ratio
_candidate_qualifies_for_claude_md_kind
_build_classification_guardrail_signals
_valid_suggested_kind
_candidate_has_claude_md_signal
_candidate_has_skill_signal
_candidate_meets_hook_guardrail
_candidate_meets_agent_guardrail
_classification_trace_entry
_apply_classification_guardrail
_normalize_candidate_kind
merge_classification_into_candidate
```

呼び出し元は、ルール処理が `build_claude_md_immediate_apply_preview`、分類処理が `build_proposal_sections`・`build_classification_target_candidates` から辿る経路です。例えば `build_proposal_sections → _normalize_candidate_kind → _apply_classification_guardrail`。これらの入口はすべて未到達です。

**D. 引き継ぎ・候補分割・適用処理の 22 関数（3270–4143 行）**

```text
_skill_slug
_coerce_context_int
build_skill_creator_handoff
_resolved_workspace_path
build_candidate_apply_scope_metadata
build_cross_repo_handoff_metadata
merge_cross_repo_into_skill_handoff
candidate_split_suggestions
_top_signal_values
_split_child_candidate_id
_source_name_from_session_ref
_build_split_child_evidence_items
_materialize_split_candidates
build_next_step_stub
_candidate_stable_identity_parts
_hash_stable_identity
build_candidate_content_key
build_candidate_decision_key
build_candidate_decision_stub
build_learning_feedback
build_claude_md_immediate_apply_preview
apply_claude_md_immediate_rules
```

主な呼び出し元は `build_proposal_sections` と `build_proposal_input_candidates`。例は `build_proposal_sections → build_skill_creator_handoff`、`build_proposal_input_candidates → _materialize_split_candidates` です。`apply_claude_md_immediate_rules → build_claude_md_immediate_apply_preview` は独立した未使用経路で、前者への呼び出し元はありません。

**E. 判定統合・分類対象作成の 11 関数（4146–4520 行）**

```text
merge_judgment_into_candidate
_is_oversized_and_unresolved
_resolved_ready_blocking_flags
_ready_state_guard_reasons
_candidate_alignment_guard_reason
_apply_ready_state_guard
build_proposal_input_candidates
_classification_target_priority
build_classification_prompt_candidate
build_classification_target_decision
build_classification_target_candidates
```

`build_classification_target_candidates → build_proposal_input_candidates → merge_judgment_into_candidate / _apply_ready_state_guard` という経路です。`build_classification_target_candidates` と `_is_oversized_and_unresolved` には呼び出し元がありません。もう一つの利用元 `build_proposal_sections` も未到達です。

**F. 提案の組み立て・Markdown 生成の 15 関数（4523–4969 行）**

```text
_ready_candidate_sort_key
_candidate_apply_scope_bucket
_partition_ready_candidates
_other_repo_heading
build_proposal_sections
_observation_scope_line
_triaged_candidate_count
_no_ready_reason_summary
_no_ready_next_step
build_observation_contract
_observation_stats_lines
_growth_signal_lines
_degraded_mode_lines
build_proposal_markdown
build_skill_scaffold_summary_lines
```

中心の `build_proposal_sections` に呼び出し元がありません。そこから `build_proposal_markdown`、`_partition_ready_candidates`、`build_observation_contract` などへ進む旧出力生成経路です。

**G. 表示・重複候補統合の 22 関数（5089–5624 行）**

```text
_display_label_for_candidate
_candidate_support_total
_candidate_display_corpus
_heuristic_display_label
_compact_focus_label
_compact_effect_for_candidate
_compact_action_for_candidate
_compact_scope_for_candidate
build_compact_ready_rows
_build_compact_ready_table
build_compact_ready_markdown
_candidate_identity_merge_key
_candidate_rank
_record_candidate_variant
_merge_candidate_variants
_dedupe_candidate_sections
_summarize_candidate_detail
_detail_lines
_variant_summary_line
proposal_item_lines
rejected_item_lines
build_evidence_chain_lines
```

呼び出し元は F 群です。具体的には `build_proposal_sections → build_compact_ready_rows / build_compact_ready_markdown / _dedupe_candidate_sections`、`build_proposal_markdown → proposal_item_lines / rejected_item_lines`。収集側からの参照はありません。

**H. scaffold・補助処理の 5 関数（5627–5837 行）**

```text
_infer_skill_operation_mode
_build_observed_history_summary
recent_packet_count
build_skill_scaffold_context
workspace_matches
```

`build_proposal_sections → build_skill_scaffold_context → _infer_skill_operation_mode / _build_observed_history_summary` が呼び出し経路です。`recent_packet_count` と `workspace_matches` に呼び出し元はありません。

2273 行目以降の定数にも、到達する 65 関数から必要とされるものは見つかりませんでした。一方、前半の task shape・rule・workflow 用定数は `build_packet()` から使われるため、削除対象と混同できません。

また、`derived_store.get_slice_source_runs()`・`evaluate_slice_completeness()`、`aggregate_core.load_expected_sources()` なども今回の CLI 入口からは未到達です。ただし前者は tests が直接利用しています。**CLI から未到達という理由だけで、上記 135 関数と一緒に削除する判断は避けるべきです。**

**外部仕様・振る舞いの変更を伴うため、別変更として扱う候補**

| 候補 | 現状と必要な判断 | 影響範囲・不足テスト |
|---|---|---|
| 日付境界の統一 | `today/yesterday` の日付選択は 6 時境界、指定日の収集範囲は暦日。暦日に統一するか、収集範囲を 6 時〜翌 6 時にするかの判断が必要 | collect・aggregate・read_log・source の範囲、store の日付キーと fingerprint。workspace-agent の `resolve_report_date()` も 6 時規則を複製している。現在の 6 時規則を固定する既存テストの変更と、再収集・旧データとの併存テストが必要 |
| packet の生成停止・容量削減 | `skill_miner_packet` だけでなく、`ai_observation`、packet 配列、logical packet、複数イベント、store の packet observation に重複がある。フィールド削除や新規 packet 行の保存停止は出力・保存内容を変える | source の `details`、aggregate の timeline/groups、store と既存データの読み出し。新旧形式の互換方針、fingerprint と再収集時の扱いが必要。未到達コード削除だけでは既存 DB は小さくならない |
| Codex の history ファイルを任意化 | 現在は history ファイルが存在しないと、sessions があっても `skipped/not_found`。空ファイルで成功するケースとは異なる | `codex_history` の収集対象と status が変わる。実際に history ファイルが存在しないテストが必要 |
| エラー回復範囲の変更 | 非 object JSON、`events: null`、不正 timestamp などを source 単位の error に隔離する修正や、collect の timeout を JSON 化する修正 | 現在の aggregate 全体の失敗・例外出力・終了コードが変わる。正常 source を残すか、収集全体を失敗させるかを定義したテストが必要 |

なお、README の `report_date_context` とトップレベル `scope_mode` は、現在の `aggregate.py` では出力されていません。リファクタリング時は実装へのフィールド追加と混ぜず、まずドキュメントとテストの記述を実際の契約に合わせる候補です。