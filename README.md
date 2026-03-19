# DayTrace

> **AIエージェント ハッカソン 2026 提出作品**  
> テーマ: **「一度命じたら、あとは任せろ」**

**一度頼めば、観測から提案まで自律完走。**  
DayTrace は、ローカル証跡を集めて 1 日を再構成し、反復パターンを抽出し、次の改善候補まで返す Claude Code plugin です。

![DayTrace overview](docs/daytrace-hero.svg)

## 何ができるか

`/daytrace-session` と一度頼むと、DayTrace は次を順に実行します。

1. Git / Claude / Codex / Chrome / file activity から、その日の証跡を収集
2. 日報を生成
3. AI 履歴から反復パターンを抽出し、固定化候補を提案
4. 必要条件を満たす日は、投稿下書きまで生成

返ってくるのは、単なるログ一覧ではありません。

- **自分用日報**: 後で振り返れる形に再構成
- **共有用日報**: 第三者に見せやすい進捗報告
- **パターン提案**: `CLAUDE.md` / `skill` / `hook` / `agent` の固定化候補
- **投稿下書き**: その日の中心テーマを 1 本の narrative として整理

## ハッカソン審査基準へのアプローチ

### 自律性

DayTrace の自律性は、単に「質問しない」ことではなく、**最後まで進めること** にあります。

- 一度頼むと、収集から日報・提案・下書きまで自律完走
- source が欠けても止まらず、利用可能な証跡だけで継続
- 人に返すのは、共有境界や固定化判断など、責任のある場面だけ

つまり DayTrace は、**放っておいても進むが、勝手に越えてはいけない境界では止まる** ように作っています。

### クオリティ

DayTrace は、同じローカル証跡を 2 つのルートで使い分けます。

- **date-first**: 日報 / 投稿下書き向け
- **scope-first**: スキル抽出向け

この分離により、1 本のログから全部を無理に決めず、用途ごとに必要な粒度で再構成します。  
また、各提案には evidence と confidence を付け、LLM の暴走を抑えながら人が読める出力へ整えます。

### インパクト

DayTrace は「その場で出して終わり」の提案器ではありません。

- 採用された提案は固定化へ進む
- 見送られた提案も decision log に残る
- 同じパターンに証跡が蓄積すれば、次回あらためて再浮上できる

つまり、**ユーザーの作業履歴そのものを、次に任せられる自動化へ変えていく** ところにインパクトがあります。

## 試し方

### 1. インストール

```bash
claude plugin add github:matz-d/daytrace-plugin
```

設定は不要です。外部へのデータ送信は一切ありません。  
Git リポジトリではない、Chrome 履歴に権限がない、といった環境でも利用可能な source だけで縮退動作します。

### 2. 実行

Claude Code 上で次を実行してください。

```bash
/daytrace-session
```

あるいは自然言語で、

- `今日の振り返りをお願い`
- `1日のまとめをして`
- `全部やって`

のように頼むだけでも開始できます。

### 3. 実行すると返るもの

典型的には、次の流れで返ってきます。

1. **DayTrace ダイジェスト**
2. **日報**: 自分用、条件を満たせば共有用も生成
3. **パターン提案**: 固定化を推奨する候補と、追加観測が必要な候補
4. **投稿下書き**: AI + Git 共起など条件を満たす日に生成
5. **セッション要約**

## どう動くか

```text
observe ──→ project ──→ extract ──→ propose ──→ apply
  │            │            │           │          │
  │        date-first   scope-first  decision    CLAUDE.md
  │        ┌─────┐     ┌─────┐       log        skill / hook
  │        │daily │     │skill│                    agent
  │        │report│     │miner│
  │        │post  │     └─────┘
  │        │draft │
  │        └─────┘
  │
5 local sources
(git, claude, codex, chrome, file-activity)
```

### 5つのスキル

| スキル | 主軸 | 役割 |
|--------|------|------|
| `/daytrace-session` | orchestration | 一言で全フェーズを自律完走する統合入口 |
| `/daily-report` | date-first | その日の活動を日報ドラフトに再構成 |
| `/post-draft` | date-first | 1 日の中心テーマを narrative draft に再構成 |
| `/skill-miner` | scope-first | AI 履歴から反復パターンを抽出し固定化候補を提案 |
| `/skill-applier` | fixation | 提案を `CLAUDE.md` / `skill` / `hook` / `agent` に固定化 |

### 自律性の境界

DayTrace は何でも勝手に決めるのではなく、次の境界を持ちます。

- **自動でやること**: 収集、縮退判断、日報生成、候補抽出、追加調査、投稿下書き
- **必要時だけ確認すること**: 共有境界、提案の固定化、`CLAUDE.md` 適用

このため、README 上の約束としては **「0-Ask」より「bounded autonomy」** が近いです。

## データソース

収集対象は **ローカルデータのみ** です。外部サービスへデータは送信しません。

| ソース | 対象 | スコープ |
|--------|------|----------|
| `git-history` | Git コミット + worktree snapshot | workspace |
| `claude-history` | `~/.claude/projects/**/*.jsonl` | all-day |
| `codex-history` | `~/.codex/history.jsonl` | all-day |
| `chrome-history` | Chrome History DB の読み取り専用コピー | all-day |
| `workspace-file-activity` | untracked ファイル変更 | workspace |

### `shared` / `workspace` / `all-day` について

- `workspace` source: 現在の repo に閉じた証跡
- `all-day` source: その日全体の証跡
- `shared` 出力: 第三者向けに再構成した日報

DayTrace は source ごとの scope を保持したまま出力を組み立てるため、  
repo ローカルの証跡と 1 日全体の証跡を混同しない設計になっています。

## サンプル出力の要点

実際のセッションでは、たとえば次のような結果が返ります。

- その日の主要活動を 3-6 項目の日報として再構成
- `skill_miner_prepare.py` 修正や observation contract 統合作業のような中心テーマを抽出
- `CLAUDE.md` 固定化候補や skill 候補を evidence 付きで提示
- AI + Git 共起が強い日は、そのテーマをもとに投稿下書きを生成

言い換えると DayTrace は、**「今日は何が起きたか」と「次に何を固定化すべきか」を同じ証跡から返す** plugin です。

## 動作要件

- Python 3.x
- Git
- macOS または Linux

追加パッケージ不要。Python 標準ライブラリのみで動作します。

## 開発リポジトリについて

このリポジトリは開発用です。配布用プラグインは [daytrace-plugin](https://github.com/matz-d/daytrace-plugin) に分離しています。

```bash
git clone --recurse-submodules https://github.com/matz-d/daytrace.git
```

主要ディレクトリ:

```text
plugins/daytrace/      plugin 本体
tests/                 テストスイート
docs/                  設計・優先度メモ
```

## License

MIT
