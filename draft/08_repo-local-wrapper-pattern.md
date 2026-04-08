# 自分用 DayTrace を repo-local wrapper で作るパターン

記事で「私がどうやって自分用 DayTrace を作ったか」を説明する時の参照メモ。

---

## まず結論

私が `workspace-agent` 用に作った `daytrace-bizflow` は、**DayTrace 本体を fork して改造したものではない**。

やったことはシンプルで、以下の 2 層に分けただけだった。

- **upstream**: 公開版 DayTrace plugin の共通コア
- **repo-local**: そのリポジトリ専用の source / flow / wording を足す wrapper

つまり、「DayTrace を自分用に作り直した」というより、**共通の DayTrace を、自分の作業環境に合わせて薄くラップした**という感覚に近い。

---

## この説明で合っているか

概ね合っている。記事では次のように書くと誤解が少ない。

- DayTrace 本体はそのまま使う
- 自分のリポジトリには `sources.json` と wrapper script だけを置く
- repo 固有の source や close-day フローだけを local 側で追加する
- upstream の projection / skill-miner はそのまま呼び出す
- だから upstream が改善された時、**wrapper 互換が保たれる範囲では**その恩恵を取り込みやすい

ただし 1 点だけ補足が必要。

`~/.claude/plugins/` を固定パスとして断言するのは少し危ない。実際の install 先は plugin manager の実装や version に依存するから、記事では **「インストール済み DayTrace plugin の scripts ディレクトリ」** と書く方が安全。

私の環境では、Claude plugin 版 DayTrace の scripts は次の場所に入っていた。

```bash
~/.claude/plugins/cache/daytrace-plugin/daytrace/0.1.0/scripts
```

なので記事では、例えば次のように書ける。

> 他のユーザーなら、自分の repo から DayTrace 本体を fork する代わりに、インストール済み plugin の `scripts/` を upstream として参照し、そこに repo-local wrapper をかぶせればよい。

---

## 私が実際にやった構成

`workspace-agent` では、共通コアの上に repo 固有の層だけを足した。

### upstream 側に任せたもの

- 日報 projection
- 投稿下書き projection
- skill-miner prepare
- 既存 5 source を使った集約ロジック

### repo-local 側で足したもの

- BizFlow 専用の `sources.bizflow.json`
- Google Calendar source
- Google Drive activity source
- Obsidian new-actions source
- `events` シートの TODO を先読みする close-day packet
- `actual_daily` 候補と 3 行日誌を組み立てる対話フロー

要するに、**コアは upstream、文脈は local** という分担にした。

---

## Before / After

### Before

公開版 DayTrace は、誰でもそのまま使えるようにしてある分、責務を絞っていた。

- ローカル完結
- OAuth なし
- 共通 5 source
- 日報 / 投稿下書き / 改善提案が主

### After

`workspace-agent` では、そこに「自分の運用文脈」を重ねた。

- 5 source を 8 source に拡張
- Google Workspace の予定・Drive 更新を観測に入れる
- Obsidian を進捗の正本ではなく、収集と気づきの入口として扱う
- `events` シートの `plan_daily` を読み、最後に `actual_daily` 候補まで作る
- journal と `events` 追記承認まで含めた close-day flow にする

この変化は大きく見えるが、実装の考え方としては「本体改造」ではなく「薄い adapter 層の追加」だった。

---

## 他のユーザー向けの再現パターン

他のユーザーが自分用 DayTrace を作る時も、考え方は同じでよい。

### 1. DayTrace 本体は fork しない

まずは marketplace 版や install 済み plugin を upstream として使う。

### 2. 自分の repo に local wrapper を置く

自分の repo 側に例えば次を置く。

- `config/daytrace/sources.<repo>.json`
- `scripts/daytrace/daily_report_projection.py`
- `scripts/daytrace/post_draft_projection.py`
- `scripts/daytrace/session.py`
- 必要なら `scripts/daytrace/close_day.py`

### 3. wrapper から upstream を呼ぶ

wrapper は upstream の script を直接呼び、`--sources-file` や repo 固有の設定だけ差し込む。

### 4. repo 固有の source だけ local で追加する

例えば以下は repo-local にしやすい。

- Google Calendar
- Google Drive
- Notion / Obsidian / ローカルメモ
- 自分の運用中の Sheets や journal
- 特定 workspace の artifact 抽出

---

## Codex に依頼する時のプロンプト例

他の人が Codex に頼むなら、こんな依頼で十分通るはず。

```text
このリポジトリ専用の DayTrace wrapper を作ってください。

条件:
- DayTrace 本体は変更しない
- install 済みの DayTrace plugin scripts を upstream として参照する
- この repo には repo-local wrapper だけを追加する
- upstream の daily_report_projection.py / post_draft_projection.py / skill_miner_prepare.py はそのまま使う
- local の sources file を渡して、repo 固有 source を追加する
- 必要なら close-day 用の packet script を作る
- upstream update に追従しやすいように、core logic の copy は避ける
- 追加するファイル、upstream に依存する点、壊れうる境界を README に明記する
```

もう少し具体的に書くならこうなる。

```text
Installed DayTrace plugin の scripts ディレクトリを upstream として使い、
この repo には repo-local adapter を作ってください。

やってほしいこと:
- local sources file を追加
- daily_report / post_draft / session wrapper を追加
- repo 固有 source を 2〜3 個追加
- close-day packet を追加
- upstream の core 処理は copy しない
- 依存 path は環境変数で差し替え可能にする
```

---

## 記事で強調するとよいポイント

### 1. 「自分用」と「fork」は同義ではない

多くの人は「自分用にする = 本体を改造する」と考えがちだが、実際には **adapter を 1 枚かぶせるだけで十分** なことが多い。

### 2. 共有コアと個別文脈を分けると、育てやすい

共通の改善は upstream に寄せ、自分の運用は local に閉じ込めると、両方が壊れにくい。

### 3. 「追従しやすい」は「完全自動で壊れない」とは違う

wrapper 方式は強いが、upstream の CLI 契約や JSON schema が大きく変われば直す必要はある。なので記事では **「追従しやすい」** と書くのが適切で、**「何もせず必ず追従できる」** とまでは言わない方がよい。

---

## 記事にそのまま使いやすい一文

- 私は DayTrace 本体を自分用に作り直したのではなく、公開版の上に repo 専用 wrapper を一枚かぶせた。
- 共通コアは upstream に残し、Google Workspace や Obsidian のような私固有の文脈だけを local 側に寄せた。
- この分け方にしたことで、本体の改善を取り込みやすいまま、自分の運用だけを深く最適化できた。
- 自分用ツールを作る時に、最初から fork する必要はない。まずは adapter に切り出せるかを考えた方が長持ちする。

---

## 補足メモ

`workspace-agent` で使った upstream path は開発中 repo の scripts だったが、記事では一般化してよい。

- 開発中: `~/projects/lab/daytrace/plugins/daytrace/scripts`
- 一般ユーザー向けの説明: `インストール済み DayTrace plugin の scripts ディレクトリ`

この言い換えを入れておくと、私の制作過程を語りつつ、読者が自分の環境へ置き換えやすくなる。
