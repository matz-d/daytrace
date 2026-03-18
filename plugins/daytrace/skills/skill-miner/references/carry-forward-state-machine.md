# Carry-Forward State Machine

候補の lifecycle を形式化し、次回 prepare / proposal での挙動を決定論的にする。

## 状態遷移表

```
              ┌─────────────────────────────────────────────┐
              │                                             │
  [new_packet]─→ unclustered ──→ rejected (insufficient)   │
              │     │                                       │
              │     ▼                                       │
              │  clustered ──→ ready (proposal_ready=true)  │
              │     │              │                        │
              │     │              ▼                        │
              │     │         user_decision?                │
              │     │          ├─ adopt ──→ adopted         │
              │     │          ├─ defer ──→ deferred ──────→│ (次回 prepare)
              │     │          └─ reject ─→ user_rejected ─→│ (次回 prepare)
              │     │                                       │
              │     ▼                                       │
              │  needs_research ──→ promote_ready ──→ ready │
              │     │              ├─ split_candidate ──→ needs_research
              │     │              └─ reject_candidate ──→ rejected
              │     ▼                                       │
              │  rejected (weak/singleton) ────────────────→│ (次回 prepare)
              └─────────────────────────────────────────────┘
```

## 状態定義

| 状態 | 意味 | carry_forward | 次回出現条件 |
|------|------|---------------|-------------|
| `unclustered` | 単独パケット、クラスタに未所属 | — | 次回 prepare で再クラスタされれば出現 |
| `ready` | 提案可能。`proposal_ready=true` | `true` | user_decision が設定されるまで |
| `needs_research` | 追加調査が必要 | `true` | 調査結果または次回 prepare で解消 |
| `rejected` | 品質不足で見送り | `true` | パターン変化で再浮上可能（下記参照） |
| `adopted` | ユーザーが adopt 選択済み | `false` | CLAUDE.md: Suggested Rules と照合し重複 skip。skill/hook/agent: 生成済み想定で次回 suppress。将来 store の adopted フラグで代替 |
| `deferred` | ユーザーが defer 選択済み | `true` | 常に再出現。`observation_count` が前回より増えていれば confidence 上昇 |
| `user_rejected` | ユーザーが reject 選択済み | `true` | 再浮上条件を満たした場合のみ（下記参照） |

## 再浮上条件（resurface rules）

`user_rejected` の候補が次回 prepare で再度候補化された場合:

1. **evidence_changed**: 前回 reject 時の `intent_trace` と今回の `intent_trace` の Jaccard 距離 > 0.3 → 再浮上
2. **support_grew**: 前回 reject 時の `support.packets` より今回が 2 倍以上 → 再浮上
3. **time_elapsed**: `user_decision_timestamp` から 30 日以上経過 → 再浮上
4. いずれも満たさない → suppress（`carry_forward=false` と同等に扱う）

## adopt 後の重複検出

| suggested_kind | 検出方法 | skip 条件 |
|----------------|----------|-----------|
| `CLAUDE.md` | `cwd/CLAUDE.md` の `## DayTrace Suggested Rules` を読む | 既存ルールと intent_trace の類似度 > 0.7 |
| `skill` | 生成済みスキルファイルの存在（将来: store の adopted フラグ） | ファイル存在 or store フラグ |
| `hook` | 同上 | 同上 |
| `agent` | 同上 | 同上 |

## observation_count の追跡

decision_log_stub に `observation_count` フィールドを追加:

```json
{
  "observation_count": 3,
  "prior_observation_count": 2,
  "observation_delta": 1
}
```

- `observation_count`: 今回の prepare で計算された support.packets
- `prior_observation_count`: 前回 decision_log の observation_count（初回は 0）
- `observation_delta`: 差分。defer 候補の confidence 変化を判断する材料
