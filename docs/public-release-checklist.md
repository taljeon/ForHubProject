# Public Release Checklist

この文書は `Forme JobHub` を GitHub 公開リポジトリやポートフォリオとして公開する前に確認する項目をまとめたものです。

## 1. 公開しないもの

- `auth/`
- `data/`
- `playwright/.auth/`
- `.env`
- `.env.local`
- 実運用ログ
- 実 Gmail / Calendar の画面キャプチャ

確認:

```bash
git ls-files auth data playwright/.auth .env .env.local
```

何も出ない状態にします。

## 2. tracked ファイル内の個人情報除去

確認対象:

- 実メールアドレス
- ローカル絶対パス
- token / secret / API key の痕跡
- 生成済み launchd `.plist`

例:

```bash
rg -nP "\\b[A-Za-z0-9._%+-]+@(?!example\\.(com|org|net)\\b)[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b|/Users/your-user|BEGIN PRIVATE KEY|AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|ya29\\.[0-9A-Za-z._-]+" .
```

特に確認しやすい場所:

- `README.md`
- `docs/job-operations-design-ja.md`
- `.env.example`
- `scripts/gcp-bootstrap.sh`
- `ops/launchd/templates/`
- サンプルデータ

## 3. 実運用値とサンプル値を分離する

公開側に残すもの:

- `.env.example`
- サンプルデータ
- placeholder 値
- テンプレート化された `launchd` 設定

公開側に残さないもの:

- 実 Gmail account / recipient
- 実 Google project / account
- 実 Playwright state ファイル
- 実 `.plist`

## 4. env 読み込みの説明を実装に合わせる

公開向けドキュメントでは次を明記します。

- `scripts/*.sh` は `.env` の後に `.env.local` を読む
- `python -m app.cli ...` も repo 直下の `.env` / `.env.local` を自動読込する
- 同じキーが両方にある場合は `.env.local` を優先し、すでに export 済みの環境変数は上書きしない
- `.env.example` には「実際に読まれる変数」だけを残す

## 5. README を公開向けにする

README では次を確認します。

- 現在の実装に存在するコマンドだけを載せる
- 実在しない設計文書やスクリプトにリンクしない
- 実装済みの launchd テンプレートだけを案内する
- 公開されないデータがあることを明記する

## 6. デモデータとスクリーンショット

- 実メール件名、会社名、ID、会議 URL をそのまま使わない
- 可能なら `seed-demo` を使ってスクリーンショットを撮り直す
- ログ画面を公開する場合はメール件名やアドレスを残さない

## 7. launchd / 運用ファイルの扱い

次のようなファイルは、公開リポジトリでは「実運用設定」ではなく「テンプレート」または「生成手順」として扱います。

- `ops/launchd/templates/*.plist.in`
- ローカル絶対パスを含む運用メモ

理由:

- ユーザー名やローカルディレクトリ構造が露出する
- 他環境でそのまま再利用できない

推奨:

- repo にはテンプレートだけ置く
- 実体の `.plist` は `scripts/render-launchd-plists.sh` で各マシンごとに生成する
- digest テンプレートは実在する `scripts/build-digest.sh` を参照させる

## 8. 公開前チェック

```bash
./scripts/preflight-github-check.sh
zsh -n scripts/common.sh scripts/sync-mail.sh scripts/open-dashboard.sh scripts/gcp-bootstrap.sh scripts/preflight-github-check.sh scripts/start-dashboard.sh scripts/first-gmail-sync.sh scripts/build-digest.sh scripts/scan-sources.sh
```

## 9. 推奨公開戦略

- 公開 repo: コード、設計文書、サンプルデータ、マスク済みスクリーンショット
- 非公開運用: OAuth、DB、ログ、Playwright セッション、実データ

つまり、`コードは公開`, `実運用状態は非公開` を基本戦略にします。
