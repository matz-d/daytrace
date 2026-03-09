# TODO B5. Source CLI / workspace-file-activity

Phase: Foundation
Depends on: C の先行タスク（共通契約 + sources.json）

## Checklist

- [ ] 対象 workspace の指定方法を決める（引数 or cwd）
- [ ] `git ls-files --others --exclude-standard` で untracked ファイル一覧を取得する
- [ ] `stat` から `mtime` / size を取得して共通イベント形式で JSON 化する
- [ ] 対象が指定ディレクトリ配下に限定されるようにする
- [ ] Git 管理外ディレクトリや対象なし時の `skipped` 応答を定義する
- [ ] tracked ファイルを除外できていることを確認する

## Done Criteria

- [ ] untracked ファイルの活動証跡だけを共通形式 JSON で返せる
- [ ] repo 状態に依存せず失敗時の扱いが一定である
