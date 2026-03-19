# DayTrace Source Manifest Draft

`AR2` の store 導入より前に固定するための、source-agnostic manifest note。

## Purpose

- built-in source と将来の user drop-in source が同じ logical manifest shape を共有できるようにする
- `source_runs` に保存する source identity / manifest fingerprint の定義を先に固定する
- registry redesign を後置しても store schema が built-in 専用にならないようにする

## Current Shapes

### Built-in registry

- `plugins/daytrace/scripts/sources.json`
- JSON array of source manifest objects

### Future drop-in registry draft

- `~/.config/daytrace/sources.d/*.json`
- 1 file = 1 JSON object
- object shape is the same as each built-in manifest entry

`source_registry.load_sources()` は array と single-object の両方を受け付ける。
`source_registry.load_registry()` は built-in registry と user drop-in registry を同じ validation / identity ルールで束ねる。

## Logical Manifest Fields

`manifest_fingerprint` の対象として固定する logical fields:

- `name`
- `command`
- `scope_mode`
- `supports_date_range`
- `supports_all_sessions`
- `confidence_category`
- `prerequisites`

補足:

- manifest 入力 field 名は `confidence_category` とする
- `confidence_category` は string または list of string を受け付ける
- `manifest_fingerprint` 用の canonical payload では、これを正規化して `confidence_categories` という list field に変換する

runtime-only orchestration fields として扱い、fingerprint から外す fields:

- `required`
- `timeout_sec`
- `platforms`

理由:

- これらは source の論理的な収集 identity よりも、実行環境や orchestrator policy に近い
- timeout や platform 対応の変更だけで store identity を変えると再 ingest 判定が不必要に揺れる

## Source Identity

`source_identity` は以下で固定する:

- `source_id`: manifest の `name`
- `scope_mode`: manifest の `scope_mode`
- `identity_version`: `daytrace-source-identity/v1`

補足:

- registry 全体で `name` は一意でなければならない
- built-in / user drop-in 間で同名 collision があれば validation error にする
- source path や registry location は identity に含めない

## Manifest Fingerprint

`manifest_fingerprint` は以下で固定する:

- hash algorithm: `sha256`
- serialization: JSON with sorted keys
- manifest kind: `daytrace-source-manifest/v1`

canonical payload:

```json
{
  "manifest_kind": "daytrace-source-manifest/v1",
  "name": "git-history",
  "command": "python3 scripts/git_history.py",
  "scope_mode": "workspace",
  "supports_date_range": true,
  "supports_all_sessions": false,
  "confidence_categories": ["git"],
  "prerequisites": [{"type": "git_repo"}]
}
```

補足:

- これは raw manifest の例ではなく、fingerprint 計算に使う canonical payload の例
- raw manifest では `confidence_category`
- canonical payload では正規化後の `confidence_categories`

## Validation Policy

built-in source 互換を崩さないため、validation は次の方針にする。

- core contract fields の欠落は reject する
- core field type mismatch は reject する
- unknown extra keys は reject せず、そのまま保持する
- `prerequisites` は list of object + non-empty `type` までを共通 validation とする
- prerequisite subtype ごとの厳密 validation は registry loader ではなく preflight evaluator 側で扱う

この方針なら、既存 `sources.json` を壊さずに AR2 用の identity/fingerprint を固定できる。
