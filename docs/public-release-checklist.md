# Public Release Checklist

この文書は `Forme JobHub` を GitHub 公開リポジトリやポートフォリオとして公開する前に確認する項目をまとめたものです。

## 1. 公開しないもの

- `auth/`
- `data/`
- `playwright/.auth/`
- `.env`
- 実運用ログ
- 実 Gmail / Calendar / Tasks の画面キャプチャ

確認:

```bash
git ls-files auth data playwright/.auth .env
```

何も出ない状態にします。

## 2. tracked ファイル内の個人情報除去

確認対象:

- 実メールアドレス
- ローカル絶対パス
- 個人用 GCP config 名
- token / secret / API key の痕跡

例:

```bash
rg -n "your-real-email@example.com|/Users/your-user|token.json|credentials.json|refresh_token|access_token|AIza|ghp_|github_pat_" .
```

特に確認しやすい場所:

- `README.md`
- `docs/job-operations-design-ja.md`
- `.env.example`
- `scripts/gcp-bootstrap.sh`
- サンプルデータ
- UI の初期入力値

## 3. 実運用値とサンプル値を分離する

公開側に残すもの:

- `.env.example`
- サンプルデータ
- placeholder 値

公開側に残さないもの:

- 実 Gmail recipient
- 実 Google project / account
- 実 `vault_item_id`
- 実 Playwright state ファイル

## 4. README を公開向けにする

README では次を明確にします。

- このプロジェクトが個人運用アプリであること
- 公開されないデータがあること
- 使っている外部 API
- ローカルで再現する最小手順
- 実運用環境と公開コードが分かれている理由

## 5. デモデータとスクリーンショット

- 実メール件名、会社名、ID、会議 URL をそのまま使わない
- 可能なら `seed-demo` を使ってスクリーンショットを撮り直す
- Calendar / Tasks の画面もマスキングまたはサンプルアカウントで用意する

## 6. 運用ファイルの扱い

次のようなファイルは、公開リポジトリでは「実運用設定」ではなく「テンプレート」または「生成手順」として扱う方が安全です。

- `ops/launchd/templates/*.plist.in`
- ローカル絶対パスを含む運用メモ

理由:

- ユーザー名やローカルディレクトリ構造が露出する
- 他環境でそのまま再利用できない

推奨:

- repo にはテンプレートだけ置く
- 実体の `.plist` は `scripts/render-launchd-plists.sh` で各マシンごとに生成する

## 7. 公開前チェック

```bash
./scripts/preflight-github-check.sh
python -m app.cli validate-local
```

## 8. 推奨公開戦略

- 公開 repo: コード、設計文書、サンプルデータ、スクリーンショット
- 非公開運用: OAuth、DB、ログ、Playwright セッション、実データ

つまり、`コードは公開`, `実運用状態は非公開` を基本戦略にします。
