<!-- sample output: /post-draft (date-first / Context & Narrative) -->

# date-first で振り返る：DayTrace を「3 スキルの役割分担」として再設計した日

> 注記: Claude/Codex/Chrome はその日全体の証跡、Git とファイル変更は current workspace に限定された証跡です。

## 背景

DayTrace は当初、3 つのスキル（`daily-report` / `post-draft` / `skill-miner`）がそれぞれ独立した要約ツールとして設計されていた。
しかし、使い続けるうちに「3 スキルが同じ履歴を別の角度から読んでいる」という説明では、役割の差がぼやけることに気づいた。

そこで、この日は 3 スキルを「Fact & Action」「Context & Narrative」「Pattern Extraction」という役割レイヤーとして再定義する作業に集中した。

## 何を進めたか

SKILL.md と README の両方を v2.3 framing に揃えた。
最も大きな変更は、`daily-report` と `post-draft` が **date-first**（対象日が主軸）、`skill-miner` が **scope-first**（観測範囲が主軸）という違いを明示したことだ。

あわせて、`workspace` の意味がスキルごとに異なることを整理した。

- `daily-report` / `post-draft` では workspace は「補助フィルタ」として機能する。指定しなくても動く。
- `skill-miner` では workspace は「観測スコープ」そのものであり、`--all-sessions` との対比が UX 上の核になる。

## 詰まった点 / 判断したこと

mixed-scope の説明をどの粒度で README に入れるかで迷った。
詳細すぎると読み手が構えてしまうし、省略しすぎると出力の coverage を誤解させる。

判断として、「coverage の誤認を防ぐための事実説明に留め、日報や narrative の価値を弱めない」という線引きを採用した。
mixed-scope 注記はあくまで情報であり、成果を割り引くものではないことを一文で添えることにした。

## 学び

`date-first` と `scope-first` を対比させることで、3 スキルの説明が一段と整理された。
用語を決めると、README の文章が自然に短くなる。定義が曖昧なまま文章で補おうとすると逆に長くなる。

## 次にやること

- fixture と README の wording を突き合わせてレビューする
- 3 分デモのシナリオが product copy と一致しているか確認する
- skill-miner の workspace / all-sessions 選択フローを審査員向けに短く説明する方法を考える
