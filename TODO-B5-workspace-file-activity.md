# TODO B5. Source CLI / workspace-file-activity

Phase: Foundation
Depends on: C の先行タスク（共通契約 + sources.json）

## Checklist

- [x] 対象 workspace の指定方法を決める（引数 or cwd）
- [x] `git ls-files --others --exclude-standard` で untracked ファイル一覧を取得する
- [x] `stat` から `mtime` / size を取得して共通イベント形式で JSON 化する
- [x] 対象が指定ディレクトリ配下に限定されるようにする
- [x] Git 管理外ディレクトリや対象なし時の `skipped` 応答を定義する
- [x] tracked ファイルを除外できていることを確認する

## Done Criteria

- [x] untracked ファイルの活動証跡だけを共通形式 JSON で返せる
- [x] repo 状態に依存せず失敗時の扱いが一定である
