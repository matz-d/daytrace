# DayTrace Skill-Miner Refactor Plan Review Aide

## Executive Summary
The proposed refactor affects a complex, multi-stage skill-miner pipeline with **tight integration points** across packet schema, clustering/similarity, store persistence, and LLM decision logic. Key architectural decision points are already established but need careful surface management during refactor.

---

## 1. Current Implementation Topology

### 1.1 Packet Schema & Primary Intent Extraction
**Files:**
- `skill_miner_common.py` (1,438 lines) — Core definitions
- `skill_miner_prepare.py` (1,510+ lines) — Packet aggregation

**Key Components:**
```
Packet Schema (build_packet):
  - packet_id: f"{source}:{session_ref}:{packet_index}"
  - source: "claude-history" | "codex-history"
  - session_ref: str (f"claude:{path}:{timestamp}" or f"codex:{session_id}:{timestamp}")
  - primary_intent: str (normalized from user_messages)
  - repeated_rules: list[dict] — normalized automation patterns
  - task_shape: list[str] — inferred from texts + tools
  - artifact_hints: list[str] — output artifact predictions
  - tool_signature: list[str] — tools used in the packet
  - representative_snippets: list[str] — evidence text (max 2, RAW_SNIPPET_LIMIT=100 chars)
  - support: dict — message_count, tool_call_count
  - timestamp, workspace, session_id, source
```

**Primary Intent Extraction** (`normalize_primary_intent` @ line 372):
- Takes user_messages or fallback texts
- Masks workspace paths, normalizes URLs
- Returns single string (compact, workspace-redacted)
- **No versioning explicitly tracked** — potential fragility point

**Repeated Rules Inference** (`infer_repeated_rules` @ line 349):
- Pattern matching against `REPEATED_RULE_PATTERNS` (4 known rules)
- Returns list of dicts: `{"normalized": str, "raw_snippet": str, "match_text": str}`
- Normalization via `normalize_match_text()` applies `MATCH_TEXT_NORMALIZATIONS` (17 mappings)
- **No version tracking** — aliases are implicit in code

---

### 1.2 Packet Generation: Two Data Paths

**Raw History Path** (`collect_raw_packets`):
```
Claude History → build_claude_logical_packets (gap-based grouping, DEFAULT_GAP_HOURS=8)
                 ↓ _tag_fidelity("original")
                 → build_packet (via claude_message_text extraction)
                 ↓
Codex History  → _packet_from_codex_session (session aggregation)
                 ↓ _tag_fidelity("original")
                 → build_packet (via codex_command_names, codex_message_text)
```

**Store-Backed Path** (`read_store_packets`):
```
SQLite Store → get_observations (derived_store.py @ line 434)
               ↓ _packet_from_claude_observation or _packet_from_codex_observations
               ↓ _tag_fidelity("approximate")
               → build_packet (fallback to summary if highlights missing)
```

**Fidelity Flags:** `"original"`, `"approximate"`, `"canonical"` (lines 75-77)
- Packet carries fidelity marker but **no schema version field**
- If primary_intent normalization changes, old packets are silently re-processed

---

### 1.3 Clustering & Similarity Scoring

**Files:**
- `skill_miner_prepare.py::cluster_packets` (line 1042, ~130 lines)
- `skill_miner_prepare.py::_build_similarity_features` (line 756)
- `skill_miner_prepare.py::_similarity_score_from_features` (line 783)

**Constants:**
```python
CLUSTER_MERGE_THRESHOLD = 0.60         # Merge if score >= this
CLUSTER_NEAR_MATCH_THRESHOLD = 0.45    # Track near-misses if in [0.45, 0.60)
SIMILARITY_WEIGHT_BUDGET = {
    "task_shapes": 0.22,
    "specific_shape_bonus": 0.08,
    "intent": 0.15,
    "snippet": 0.10,
    "artifacts": 0.20,
    "rules": 0.20,
    "tools": 0.05,
}                                      # Total = 1.0
SIMILARITY_GENERIC_ONLY_PENALTY = 0.08 # Penalize generic-only combos
OVERSIZED_CLUSTER_MIN_PACKETS = 8      # Flag if cluster >= 8 packets
OVERSIZED_CLUSTER_MIN_SHARE = 0.5      # AND cluster represents >= 50% of all packets
```

**Algorithm:**
1. **Blocking:** `stable_block_keys()` groups packets by (first repeated_rule, first task_shape, first artifact_hint)
2. **Pairwise Comparison:** Within block, compute similarity via Jaccard + overlap metrics
3. **Merge:** Union-Find (line 1054) unifies pairs with score >= 0.60
4. **Near-Match Tracking:** Pairs in [0.45, 0.60) stored for research phase
5. **Deduplication:** `_dedupe_matches()` removes duplicate packet references

**Similarity Features** (line 770-780):
```python
{
  "snippet_tokens": set,               # Tokenized representative snippets
  "intent_tokens": set,                # Tokenized primary_intent
  "task_shape_set": set,
  "tool_set": set,
  "artifact_set": set,
  "rule_names": set,                   # Normalized rule names
  "primary_non_generic_shape": str,    # First non-GENERIC task shape or ""
  "generic_task_only": bool,
  "generic_tool_only": bool,
}
```

**Tokenization** (`tokenize` @ line 201):
- Uses `WORD_PATTERN` regex (line 144): `r"[A-Za-z0-9_./+-]+|[一-龥ぁ-んァ-ン]+"`
- Applies `TOKEN_SYNONYMS` (19 mappings) for stemming
- **No explicit version** — regex changes silently affect all scored pairs

---

### 1.4 Candidate Labeling & Scoring

**Files:**
- `skill_miner_common.py::candidate_label` (line 544)
- `skill_miner_common.py::candidate_score` (line 611)
- `skill_miner_common.py::build_candidate_quality` (line 624)

**Labels** (`candidate_label`):
- Rule-based heuristic combining task_shapes, artifact_hints, rule_hints, primary_intent
- Returns string label (e.g., "Review findings in findings-first format")
- **No scoring** — just string synthesis for display

**Scoring** (`candidate_score`):
```python
score = (
    total_packets * 0.3 +
    recent_packets_7d * 0.5 +              # Recency weight
    (unique_workspaces > 1 ? 0.2 : 0) +
    (claude_packets > 0 AND codex_packets > 0 ? 0.05 : 0)
)
return max(0.0, min(score, 1.0))
```
- **Observation:** Heavy recency weighting (0.5 for packets in 7d window)
- Quality flags: "oversized_cluster", "generic_tools", "weak_semantic_cohesion", "low_message_fidelity"

---

### 1.5 Deep Research Judge (judge_research_candidate)

**Files:**
- `skill_miner_common.py::judge_research_candidate` (line 916, ~110 lines)
- `skill_miner_detail.py` — Collects sampled session details

**Algorithm** (line 916-1027):
1. **Ref Sampling:** Uses `build_research_targets()` to select 5 representative session refs
2. **Detail Extraction:** `skill_miner_detail.py` fetches Claude session messages + Codex command details
3. **Signal Building:** `build_detail_signal()` extracts task_shapes, artifact_hints, primary_intent, repeated_rules from each detail
4. **Decision Logic:**
   - If avg_overlap < 0.08 AND no repeated_rules → **reject**
   - If avg_overlap < 0.22 AND multiple non-generic shapes → **split_candidate**
   - If shape_count >= 2 AND avg_overlap >= 0.12 AND (rules OR non-generic) → **promote_ready**
   - If dominant_artifact >= 2 AND share >= 0.6 AND overlap >= 0.14 → **promote_ready**
   - Else → **reject** or **split_candidate**

**Output Schema:**
```python
{
  "recommendation": "promote_ready" | "split_candidate" | "reject_candidate",
  "proposed_triage_status": "ready" | "needs_research" | "rejected",
  "proposed_confidence": "strong" | "medium" | "weak" | "insufficient",
  "summary": str,
  "reasons": list[str],
  "split_suggestions": list[str],
  "subcluster_triage": list[dict],
  "detail_signals": list[dict],
}
```

**Constants:**
```python
DEFAULT_RESEARCH_REF_LIMIT = 5    # Sampled refs for deep research
```

---

### 1.6 Store-Backed Prepare & Pattern Persistence

**Files:**
- `skill_miner_prepare.py::read_store_packets` (line 571)
- `derived_store.py::get_observations` (line 434)
- `derived_store.py::persist_patterns_from_prepare` (line 813)
- `derived_store.py::evaluate_slice_completeness` (line 355)

**Constants:**
```python
SLICE_COMPLETE = "complete"           # All expected sources succeeded
SLICE_DEGRADED = "degraded"           # Some expected sources skipped/failed
PATTERN_DERIVATION_VERSION = "skill-miner-candidate-v1"
ACTIVITY_DERIVATION_VERSION = "activities-v1"
STORE_HYDRATE_TIMEOUT_SEC = 90
```

**Data Flow:**
```
aggregate.py [raw sources] → store.py [persist_source_result]
                             ↓
                      SQLite Store
                             ↓
skill_miner_prepare.py [--input-source store]
    ↓
read_store_packets (hydrate if incomplete)
    ↓
_packet_from_claude_observation / _packet_from_codex_observations
    ↓
cluster_packets
    ↓
persist_patterns_from_prepare (if SLICE_COMPLETE AND success statuses)
    ↓
SQLite patterns table
```

**Persist Logic** (`_should_persist_patterns`, line 733):
```python
Can persist IF:
  - top_candidates is not empty
  - No source status != "success"
  - If store input: store_slice_completeness["status"] == SLICE_COMPLETE
```

**Completeness Evaluation** (`evaluate_slice_completeness`, line 355):
- Checks if all `expected_source_names` have corresponding `source_runs` in the store
- Returns `{"status": "complete" | "degraded", "success_sources": [...], "missing_sources": [...]}`

---

## 2. Data Flow Map: History → Skill-Miner → Storage

```
┌─────────────────────────────────────────────────────────────────┐
│                    Daily Aggregation (aggregate.py)             │
│  sources.json → [claude_history, codex_history, git_history...] │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                         ┌─────────────┐
                         │ SQLite Store│ (optional)
                         └─────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Skill-Miner Prepare (skill_miner_prepare.py)        │
│  Input: raw history OR store-backed observations                 │
│  --input-source [raw|store|auto]                                │
│  --days 7 (default) or --all-sessions                           │
└─────────────────────────────────────────────────────────────────┘
   ↓                          ↓
collect_raw_packets    read_store_packets
   ↓                          ↓
[Packet: claude, codex]  [Packet: claude-store, codex-store]
   ↓                          ↓
   └──────────────┬──────────────┘
                  ↓
         filter_packets_by_days (7 or 30)
                  ↓
         cluster_packets
                  ↓
     ┌───────────┬──────────────┬─────────────┐
     ↓           ↓              ↓             ↓
  candidates  unclustered   statistics   metadata
     ↓           ↓              ↓             ↓
     └───────────┴──────────────┴─────────────┘
                  ↓
         prepare JSON output
                  ↓
         (optional) persist_patterns_from_prepare
                  ↓
         SQLite patterns table

Detail Phase:
  skill_miner_detail.py [candidate]
    → Fetch sampled session refs from original sources
    → Build detail_signals
    → Output JSON

Judge Phase:
  skill_miner_research_judge.py [candidate, details]
    → judge_research_candidate
    → Output judgment JSON

Proposal Phase:
  skill_miner_proposal.py [prepare, judgments (optional)]
    → build_proposal_sections
    → Output proposal markdown + sections
```

---

## 3. Alignment Assessment: Proposed Refactor ↔ Current Architecture

### 3.1 ✅ Well-Aligned Areas

**1. Store-backed data flow already exists**
- `read_store_packets()` (line 571) already implements store→packets translation
- `derive_store` + `evaluate_slice_completeness()` infrastructure in place
- Risk: **LOW** — Refactor can build on this foundation

**2. Packet schema stable at this layer**
- Core fields (primary_intent, repeated_rules, task_shape, artifact_hints) are well-scoped
- Similarity scoring is deterministic given packet features
- Risk: **LOW** — Schema is testable and versioned via fidelity markers

**3. Clustering algorithm is isolated**
- `cluster_packets()` is a pure function (no I/O, no side effects)
- Similarity weights are externalized constants (lines 85-93)
- Can be refactored separately without affecting data persistence
- Risk: **LOW** — Good unit-test coverage already exists (`test_skill_miner_quality_v2.py`)

---

### 3.2 ⚠️  Medium-Risk Areas

**1. Primary Intent & Repeated Rules versioning is implicit**
- Normalization logic (lines 147-150, 372) has **no schema version field**
- If `MATCH_TEXT_NORMALIZATIONS` or `TOKEN_SYNONYMS` change, old packets silently re-process with new rules
- **Current State:** Packets carry `fidelity` but not `normalization_version`
- **Refactor Risk:** If moving to derived layers, need explicit version field in packet schema
  ```python
  # Currently absent:
  # "primary_intent_version": "v1.0",
  # "rule_inference_version": "v1.0",
  ```

**2. Session Ref Contract is fragile**
- Session refs (line 419, 423) are human-readable strings: `f"claude:{path}:{timestamp}"` or `f"codex:{session_id}:{timestamp}"`
- `parse_session_ref()` (line 423) is the inversion function
- **Problem:** If workspace paths contain colons or timestamps are ambiguous, parsing fails silently
- **Refactor Risk:** Moving session_refs through store requires careful validation
  ```python
  def parse_session_ref(value: str) -> tuple[str, str, int]:
      # Fragile split-on-colon logic
  ```

**3. Store Completeness Check is strict**
- `_should_persist_patterns()` (line 733) requires `SLICE_COMPLETE` status
- If any source fails, patterns are not persisted (line 751-752)
- **Risk:** All-or-nothing semantics could reject valid partial data
- **Refactor Opportunity:** Consider `SLICE_DEGRADED` patterns with confidence downgrade

---

### 3.3 🔴 High-Risk Areas

**1. Packet Deduplication Across Store & Raw Paths**
- `read_store_packets()` calls `_dedupe_observations()` (line 588)
- `_dedupe_observations()` uses fingerprint matching to collapse duplicates
- **Problem:** If raw history and store have different timestamps or details, deduplication might fail
- **Example:** Session aggregation gap (DEFAULT_GAP_HOURS=8) might group differently in store vs. raw
- **Refactor Risk:** Store migration without careful re-validation could lose or duplicate data
  - **Recommendation:** Add fingerprint/hash validation tests before + after store refactor

**2. Adaptive Window Logic couples input source to windowing**
- Lines 843-852: `adaptive_window_decision()` only applies to workspace mode (not `--all-sessions`)
- If moving to store-only input, logic needs re-evaluation
- **Problem:** Store may not have fresh 7-day data; fallback to 30-day is hardcoded
- **Refactor Risk:** If store hydration is slow, expanding to 30 days silently increases cost
  - **Recommendation:** Separate adaptive window decision from input source selection

**3. Quality Flags & Research Judge Thresholds are tightly coupled**
- Lines 1003-1012 in `judge_research_candidate()` reference `candidate.get("quality_flags")`
- Quality flags are computed in `build_candidate_quality()` (line 624, ~14 lines)
- **Problem:** If quality flag calculation changes, judge thresholds are stale
- **Example:** "oversized_cluster" flag affects judge logic (line 1003-1007)
- **Refactor Risk:** Moving judge to LLM or external service requires exporting these flags correctly
  - **Recommendation:** Explicit schema for quality_flags enum + version

---

## 4. Compatibility Surfaces to Protect

### 4.1 Packet Versioning & Aliases

| Component | Current | Refactor Risk | Recommendation |
|-----------|---------|---------------|-----------------|
| `primary_intent` | Implicit normalization (v1) | Silent re-norm if rules change | Add `primary_intent_version` field |
| `repeated_rules` | Pattern matching (4 known rules) | New rules → old packets outdated | Version `REPEATED_RULE_PATTERNS` |
| `task_shape` | `infer_task_shapes()` heuristic | Text patterns might drift | Track pattern dictionary hash |
| `tokenize()` | WORD_PATTERN regex + TOKEN_SYNONYMS | Regex change breaks similarity | Version both separately |
| `fidelity` | "original" / "approximate" / "canonical" | Only 3 values; no extensibility | Consider enum in schema |

**Action Items:**
- [ ] Add `schema_version: "packet-v1"` to all emitted packets
- [ ] Add `normalization_versions: {primary_intent: "v1", rules: "v1"}` to packet
- [ ] Version `REPEATED_RULE_PATTERNS`, `MATCH_TEXT_NORMALIZATIONS`, `TOKEN_SYNONYMS` independently
- [ ] Add hash/checksum of pattern dictionaries to prepare payload metadata

### 4.2 Store/Raw Parity

| Concern | Current | Risk | Mitigation |
|---------|---------|------|-----------|
| Observation deduplication | `_dedupe_observations()` by fingerprint | Store may dedupe differently | Add cross-validation test suite |
| Session ref parsing | `parse_session_ref()` split on colons | Fragile if paths have colons | Validate all refs before store insert |
| Timestamp canonicalization | `ensure_datetime()` + `LOCAL_TZ` | Timezone mismatches possible | Add explicit tz checks in store schema |
| Tool extraction | `codex_command_names()` heuristic | Different in store vs. raw | Compare tool sets across sources |

**Action Items:**
- [ ] Add parity test: raw vs. store packet count, similarity scores
- [ ] Add validation: session_ref parsing always succeeds
- [ ] Add fixture: test packets from both store and raw paths

### 4.3 Test Contracts & Docs

**Existing Test Coverage:**
- `test_skill_miner_contracts.py` (22.8 KB) — Schema validation
- `test_skill_miner_quality_v2.py` (33.0 KB) — Clustering & judge logic
- `test_skill_miner.py` (91.1 KB) — E2E integration

**Critical Tests:**
```python
test_prepare_candidate_includes_evidence_items_schema  # Line 418
test_read_claude_packets_splits_when_workspace_switches # Line 452
test_prepare_dump_intents_includes_summary_and_anonymized_items  # Line 434
```

**Gaps to fill during refactor:**
- [ ] Store hydration timeout behavior under slow I/O
- [ ] Packet parity between raw and store input (same candidates?)
- [ ] Session ref escaping/unescaping round-trip tests
- [ ] Adaptive window expansion logic with sparse data

---

## 5. Constants & Helper Boundaries

### 5.1 Key Constants (By Impact)

| Constant | File | Value | Impact | Change Safety |
|----------|------|-------|--------|----------------|
| `CLUSTER_MERGE_THRESHOLD` | prepare.py:70 | 0.60 | Clustering sensitivity | **Medium** — Changes all clusters |
| `DEFAULT_OBSERVATION_DAYS` | prepare.py:66 | 7 | Default window | **Low** — User-overridable |
| `WORKSPACE_ADAPTIVE_EXPANDED_DAYS` | prepare.py:67 | 30 | Fallback window | **Low** — Only for sparse workspaces |
| `OVERSIZED_CLUSTER_MIN_PACKETS` | common.py:28 | 8 | Quality flag threshold | **High** — Affects judge logic |
| `OVERSIZED_CLUSTER_MIN_SHARE` | common.py:29 | 0.5 | Cluster percentage check | **High** — Affects judge logic |
| `GENERIC_TASK_SHAPES` set | common.py:31-36 | 4 shapes | Penalizes generic-only clusters | **High** — Similarity scoring |
| `GENERIC_TOOL_SIGNATURES` set | common.py:38-46 | 7 tools | Penalizes generic tool clusters | **High** — Similarity scoring |
| `DEFAULT_TOP_N` | common.py:24 | 10 | Candidates returned | **Low** — User CLI arg |
| `DEFAULT_RESEARCH_REF_LIMIT` | common.py:27 | 5 | Judge sample size | **Medium** — Affects judge accuracy |
| `SIMILARITY_WEIGHT_BUDGET` dict | prepare.py:85 | 7 weights summing to 1.0 | Similarity computation | **Critical** — Any change shifts all scores |

### 5.2 Boundary Functions (Stable vs. Unstable)

#### Stable (Internal, low churn):
```python
tokenize()                          # Line 201 — Regex + synonym map
jaccard_score()                     # Line 207 — Pure metric
overlap_score()                     # Line 216 — Pure metric
ensure_datetime()                   # common.py — Parse utility
```

#### Moderately Stable (Public interface, but evolved):
```python
build_packet()                      # Line 504 — Schema definition
candidate_label()                   # Line 544 — Display logic
candidate_score()                   # Line 611 — Heuristic
```

#### Unstable (Fragile, coupled):
```python
parse_session_ref()                 # Line 423 — String parsing
_dedupe_observations()              # derived_store — Fingerprint logic
build_detail_signal()               # Line 828 — Fidelity-dependent
judge_research_candidate()          # Line 916 — Multi-threshold decision
```

---

## 6. Proposed Refactor: Risk Summary & Recommendations

### Likely Safe ✅
- Extracting `clustering` to derived layer (pure function, isolated)
- Moving `similarity scoring` to separate module (constants-driven)
- Adding `derived_patterns` table in store
- Refactoring `cluster_packets()` into smaller units

### Moderate Risk ⚠️
- Changing `SIMILARITY_WEIGHT_BUDGET` — All re-clustering needed
- Adding new `GENERIC_TASK_SHAPES` or rules — Old packets need re-processing
- Modifying `judge_research_candidate()` logic — Research judges invalid
- Adjusting `CLUSTER_MERGE_THRESHOLD` — All clusters change

### High Risk 🔴
- Removing `fidelity` field from packets — Breaks store compatibility
- Changing `session_ref` format — Parse function breaks retroactively
- Rewriting `primary_intent` extraction — Inference is non-deterministic
- Changing `workspace` masking logic — Privacy semantics change
- Storing `candidates` directly in store without `packet_id` trace — Audit trail lost

### Must-Have Before Refactor
1. **Explicit versioning fields** in packet schema
2. **Comprehensive parity tests** (raw vs. store)
3. **Session ref escaping/validation** layer
4. **Quality flag enum** with explicit compatibility contract
5. **Adaptive window** decoupling from input source

---

## 7. Recommended Refactor Sequencing

### Phase 1: Foundation (Low Risk)
- [ ] Add schema version fields to packets
- [ ] Extract pure similarity scoring to `similarity.py`
- [ ] Create `SkillMinerSchemaV1` dataclass with all fields + docstrings
- [ ] Add comprehensive parity tests

### Phase 2: Clustering Improvements (Medium Risk)
- [ ] Refactor `cluster_packets()` into smaller units
- [ ] Parameterize `SIMILARITY_WEIGHT_BUDGET` via config object
- [ ] Add explicit quality flag enum
- [ ] Decouple adaptive window logic

### Phase 3: Store Integration (Medium Risk)
- [ ] Validate all session refs before store insert
- [ ] Add `packet_id` trace to patterns table
- [ ] Implement store-to-raw parity test suite
- [ ] Add explicit completeness contract

### Phase 4: Judge & Proposal Layers (High Risk, End-of-Sequence)
- [ ] Export quality flags, clusters, confidence with full context
- [ ] Version judge decision logic
- [ ] Add judge result schemas to store
- [ ] Test E2E with both raw and store input paths

---

## 8. Files to Watch During Refactor

### Core Skill-Miner Logic
```
plugins/daytrace/scripts/
├── skill_miner_common.py            [1438 lines] — SCHEMA + CONSTANTS — HIGH IMPACT
├── skill_miner_prepare.py          [1510+ lines] — MAIN PIPELINE — HIGH IMPACT
├── skill_miner_detail.py            [~200 lines] — Research sampling
├── skill_miner_research_judge.py    [~70 lines] — Judge CLI wrapper
└── skill_miner_proposal.py          [~80 lines] — Proposal output
```

### Store & Derived Layers
```
├── store.py                         [15.1 KB] — SQLite schema
├── derived_store.py                 [34.0 KB] — Observations, patterns
└── projection_adapters.py           [9.6 KB] — Aggregate ↔ store bridge
```

### Tests (Must Pass Throughout Refactor)
```
└── tests/
    ├── test_skill_miner_contracts.py    [SCHEMA VALIDATION]
    ├── test_skill_miner_quality_v2.py   [CLUSTERING + JUDGE]
    └── test_skill_miner.py              [E2E INTEGRATION]
```

### Configuration & Docs
```
└── plugins/daytrace/skills/skill-miner/SKILL.md
```

---

## 9. Key Risks & Failure Modes

| Risk | Symptom | Mitigation |
|------|---------|-----------|
| Silent normalization drift | Old packets score differently after rule change | Version normalization, add re-processing flag |
| Store hydration hangs | Adaptive window expansion never completes | Add explicit timeout monitoring, decouple from window logic |
| Deduplication losses | Raw and store have different packet counts | Implement bijective cross-validation test |
| Quality flags become stale | Judge references flags from old packet version | Explicit enum + version tracking |
| Session ref parsing fails | Invalid refs silently dropped during judge phase | Add validation layer + error propagation |
| Clustering non-determinism | Different packet orderings → different clusters | Ensure stable_sort() used throughout |

---

## Summary Checklist for Review

- [ ] **Versioning:** Explicit schema + normalization version fields added
- [ ] **Parity:** Raw vs. store input produces identical candidates (test suite confirms)
- [ ] **Session Refs:** Escaping/validation layer in place before store insert
- [ ] **Adaptive Window:** Decoupled from input source, has explicit timeout
- [ ] **Quality Flags:** Enum-based, versioned, exported to store
- [ ] **Judge Logic:** References explicit quality flag version, not implicit heuristics
- [ ] **Store Completeness:** Contracts explicit (SLICE_COMPLETE, SLICE_DEGRADED, fallback scenarios)
- [ ] **Test Coverage:** E2E tests cover both raw and store input paths
- [ ] **Backward Compat:** Old packets/fingerprints still parse without error
- [ ] **Docs:** SKILL.md and inline comments updated with new layer boundaries

---

**Document Version:** 1.0 (Review Aide)  
**Scope:** Skill-Miner Refactor Pre-Flight Assessment  
**Last Updated:** 2025-03-17

---

## Quick Navigation Index

| Section | Line Range | Key Topics |
|---------|-----------|-----------|
| Executive Summary | 1–20 | High-level overview, critical risks |
| Implementation Topology | 21–180 | Packet schema, packet generation (raw vs. store), clustering, judge logic |
| Data Flow Map | 181–250 | Visual pipeline from history to storage |
| Alignment Assessment | 251–350 | Well-aligned, medium-risk, high-risk areas |
| Compatibility Surfaces | 351–420 | Versioning, store/raw parity, test contracts |
| Constants & Boundaries | 421–520 | Key thresholds, stable vs. unstable helpers |
| Refactor Sequencing | 521–550 | 4-phase approach with dependencies |
| Risk Summary | 551–600 | Safe vs. high-risk changes, failure modes |

## For Plan Reviewers: Key Questions

1. **Versioning:**
   - Does your plan add explicit `schema_version` and `normalization_version` fields to packets?
   - How do you handle old packets when normalization rules change?

2. **Parity:**
   - Do you have test coverage proving raw vs. store input produce identical candidates?
   - What's your plan for validating deduplication consistency?

3. **Session Refs:**
   - How do you escape/validate session refs before store insertion?
   - What happens if a workspace path contains colons?

4. **Quality Flags:**
   - Are quality flags explicitly enum-based in your design?
   - How do you version them if judge logic changes?

5. **Adaptive Window:**
   - Is adaptive window decoupled from input source selection?
   - How do you prevent store hydration timeouts?

6. **Store Completeness:**
   - Do you handle SLICE_DEGRADED scenarios, or keep all-or-nothing?
   - How does partial source failure affect pattern persistence?

## For Implementation: Pre-Checklist

Before starting Phase 1:
- [ ] Read sections 1–3 (topology + data flow)
- [ ] Audit skill_miner_common.py for all versioning gaps
- [ ] Create SkillMinerSchemaV1 dataclass
- [ ] Draft parity test cases (raw vs. store)
- [ ] Identify all MATCH_TEXT_NORMALIZATIONS dependencies

Before Phase 2:
- [ ] All Phase 1 items complete + merged
- [ ] Parity tests passing
- [ ] Quality flag enum drafted

Before Phase 3:
- [ ] All Phase 2 items + tests passing
- [ ] Session ref validation layer in place
- [ ] Store completeness contract reviewed

Before Phase 4:
- [ ] All Phase 3 items + tests passing
- [ ] Judge logic versioned
- [ ] E2E tests cover both raw and store paths

---

**Document Generated:** 2025-03-17  
**Status:** Review Aide for Skill-Miner Refactor Planning  
**Scope:** Architecture assessment, risk analysis, implementation guidance  
**Audience:** Project leads, refactor implementers, code reviewers  

**Related Documents in Repository:**
- PLAN_skill-miner.md — High-level product vision
- PLAN_architecture-refresh.md — Parent architecture plan
- ISSUE-skill-miner-proposal-quality.md — Quality problem statement
- TODO-D2b-skill-miner-proposal-quality.md — Quality improvement roadmap
- plugins/daytrace/skills/skill-miner/SKILL.md — User-facing specification
