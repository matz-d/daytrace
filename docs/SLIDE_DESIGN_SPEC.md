# DayTrace スライド デザイン規則

ファイナル発表用スライド (`daytrace-final.pptx`) のデザイン仕様。
追加スライドを作成する際はこの規則に従うこと。

## ツールチェーン

- **生成**: PptxGenJS (`require("pptxgenjs")`)
- **アイコン**: react-icons/fa → sharp で PNG 化 → base64 埋め込み
- **レイアウト**: `LAYOUT_16x9` (10" × 5.625")

## カラーパレット

| トークン | Hex | 用途 |
|---------|-----|------|
| `bg` | `0F172A` | スライド背景（全スライド共通） |
| `bgCard` | `1E293B` | カード・ボックス背景 |
| `bgCard2` | `334155` | カード内の小要素・サブカード |
| `cyan` | `06B6D4` | プライマリアクセント（見出しラベル、矢印、ハイライト） |
| `cyanL` | `22D3EE` | ライトシアン（コマンド文字、サブタイトル） |
| `green` | `10B981` | ポジティブ / Output 系（解決、チェックマーク） |
| `greenL` | `34D399` | ライトグリーン（補助） |
| `purple` | `8B5CF6` | Human-in-the-loop / 承認系 |
| `purpleL` | `A78BFA` | ライトパープル（補助） |
| `amber` | `F59E0B` | 警告 / 注意 / 非決定論系 |
| `white` | `F8FAFC` | 本文テキスト |
| `muted` | `94A3B8` | 補足テキスト・キャプション |
| `mutedDk` | `64748B` | さらに控えめなテキスト |
| `red` | `EF4444` | エラー / 否定（未使用だが予約） |

### 色の使い分けルール

- 背景は **常に `bg`（0F172A）**。明るい背景スライドは作らない
- セクションラベル（「課題」「解決」「設計思想」「展望」）はカテゴリに応じた色:
  - 課題系 → `cyan`
  - 解決系 → `green`
  - 設計系 → `cyan`
  - 展望系 → `amber`
- カードの左端アクセントバー（w: 0.06）でカテゴリカラーを示す
- 承認・Human-in-the-loop 要素は `purple` 系

## タイポグラフィ

| 要素 | フォント | サイズ | ウェイト | 色 |
|------|---------|--------|---------|-----|
| スライドタイトル | Trebuchet MS | 28pt | Bold | `white` |
| セクションラベル | Calibri | 14pt | Bold | カテゴリカラー |
| カード見出し | Calibri | 14-16pt | Bold | `white` or アクセント色 |
| 本文 | Calibri | 12-13pt | Regular | `white` |
| 補足・キャプション | Calibri | 10-11pt | Regular | `muted` |
| コマンド・コード | Consolas | 14-16pt | Bold | `cyanL` |
| 大見出し（タイトルスライド） | Trebuchet MS | 48-54pt | Bold | `white` |

### テキスト配置

- 本文は **左揃え**。中央揃えはタイトルスライドとトランジションスライドのみ
- margin は基本 `0`（位置をピクセル精度で制御するため）
- 行間: `lineSpacingMultiple: 1.15`（長文のみ）

## コンポーネントパターン

### 1. セクションヘッダー

```
y=0.3: セクションラベル（14pt, bold, カテゴリカラー）
y=0.8: タイトル（28pt, bold, white）
```

すべてのコンテンツスライド（スライド2-5, 8）はこのパターンで始まる。

### 2. カード

```javascript
slide.addShape(pres.shapes.RECTANGLE, {
  x, y, w, h,
  fill: { color: "1E293B" },  // bgCard
  shadow: { type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.4 },
});
```

- 角丸なし（RECTANGLE を使用）
- 影は `makeShadow()` で統一（blur: 8, offset: 3, angle: 135, opacity: 0.4）
- **shadow オブジェクトは毎回新しく生成すること**（PptxGenJS が内部で mutate するため）

### 3. アクセントバー付きカード

```javascript
// カード本体
slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: "1E293B" }, shadow: makeShadow() });
// 左端バー
slide.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h, fill: { color: accentColor } });
```

### 4. ナンバーカード（課題スライド等）

```
[01]  見出し（16pt, bold, white）
      説明（13pt, muted）
```

番号は 20pt, Trebuchet MS, cyan, bold。

### 5. アイコン付きリスト

```
[icon 0.22x0.22]  テキスト（12pt, white）
```

アイコンと文字の間隔は 0.15-0.2 インチ。

### 6. 2カラムレイアウト

```
左カード: x=0.8, w=4.0
右カード: x=5.2, w=4.0
間隔: 0.4インチ
```

カード内:
- アイコン（0.35x0.35）+ タイトル を横並び
- 説明テキストはアイコンの下、左端揃え

### 7. トランジションスライド

- 中央揃え
- メインテキスト: 32-44pt
- サブテキスト: 14-16pt, muted or white
- 背景装飾は控えめ（透過シアンのオーバーレイ等）

## レイアウトルール

| ルール | 値 |
|--------|-----|
| スライド端マージン | 0.8インチ（左右） |
| カード間の縦間隔 | 0.2-0.3インチ |
| コンテンツ領域 | x: 0.8 〜 9.2（= 8.4インチ幅） |
| セクションラベル開始 | y: 0.3 |
| タイトル開始 | y: 0.8 |
| コンテンツ開始 | y: 1.7 |

## 避けるべきこと

- 明るい背景スライドは作らない（全スライド暗色統一）
- タイトル下のアクセントライン（AI生成感が出る）
- unicode の箇条書き記号（`•`）→ `bullet: true` を使う
- hex に `#` プレフィックス → PptxGenJS では不要
- shadow オブジェクトの再利用 → 必ず `makeShadow()` で都度生成
- テキストのみのスライド → 必ずカード、アイコン、図形のいずれかを入れる
- 同じレイアウトの連続 → カード、2カラム、フロー図を交互に

## アイコン生成

```javascript
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const { FaXxx } = require("react-icons/fa");

function renderIconSvg(IconComponent, color = "#FFFFFF", size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}
```

- サイズ 256 以上でラスタライズ（crisp に）
- 表示サイズはスライド上で 0.2-0.5 インチ
- react-icons/fa（Font Awesome）を使用

## 既存スライド構成（参考）

1. **タイトル** — 装飾矩形 + 大見出し + サブタイトル + フッターバー
2. **課題** — 3つのナンバーカード（縦並び）
3. **解決** — コマンドカード + フロー図（5アイコン→集約→出力）+ 3つのアクセントバー付きカード
4. **設計思想①** — 2カラム（決定論 vs 非決定論）+ アイコン付きリスト
5. **設計思想②** — 2カラム（SSOT vs 暗黙知→形式知）+ 横フローチャート
6. **デモ動画** — トランジション（再生アイコン中央）
7. **LIVE DEMO** — トランジション（手順カード付き）
8. **展望** — 2カラム + インストールコマンドカード
9. **クロージング** — タイトル回帰 + 装飾矩形
