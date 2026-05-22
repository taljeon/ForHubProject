# Forme JobHub

Forme JobHub は、就職活動の個人運用データをローカル中心で整理するためのアプリです。
Gmail から取得したメール、応募記録、求人ソース、面接メモ、digest を一つのローカル環境で扱います。

設計メモは [docs/job-operations-design-ja.md](docs/job-operations-design-ja.md) と [docs/architecture.md](docs/architecture.md) を参照してください。
公開前チェックは [docs/public-release-checklist.md](docs/public-release-checklist.md) を使います。

## 現在の範囲

- Gmail OAuth を使ったメール同期
- SQLite ベースのローカル状態管理
- 応募、サイトアカウント、面接メモ、求人一覧のダッシュボード
- 求人ソースの seed / scan
- Markdown digest 生成
- MLX ベースの任意ローカル LLM 要約
- `launchd` 用テンプレートの生成

## ディレクトリ構成

```text
app/
auth/google-oauth/
config/source_registry.json
data/
docs/
ops/launchd/
scripts/
```

## クイックスタート

```bash
cd /path/to/forme-local
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m app.cli init-db
python -m app.cli seed-demo
./scripts/open-dashboard.sh
```

`./scripts/open-dashboard.sh` はブラウザを開き、必要なら Forme ダッシュボードだけを起動します。
他プロセスが同じ port を使っている場合は kill せずに停止します。

## 環境変数

ラッパースクリプト (`scripts/*.sh`) と `python -m app.cli ...` は、repo 直下の `.env` と `.env.local` を自動読込します。
同じキーが両方にある場合は `.env.local` を優先し、すでに export 済みの環境変数は上書きしません。

```bash
python -m app.cli show-config
FORME_DASHBOARD_PORT=9000 ./scripts/start-dashboard.sh
```

サポートされている変数は [.env.example](.env.example) を参照してください。
`GCP_ACCOUNT_EXPECTED` は `scripts/gcp-bootstrap.sh` 用、`FORME_AUTO_DIGEST_WITH_LOCAL_LLM` は `scripts/build-digest.sh` 用です。

## Gmail 連携

1. Google Cloud で Gmail API を有効化します。
2. Desktop OAuth client を作成します。
3. `credentials.json` を `auth/google-oauth/credentials.json` に置くか、`FORME_GMAIL_CREDENTIALS` で場所を指定します。
4. 初回認証後の token は `auth/google-oauth/token.json` に保存されるか、`FORME_GMAIL_TOKEN` の指定先に保存されます。

初回フル同期:

```bash
./scripts/first-gmail-sync.sh
```

増分同期:

```bash
./scripts/sync-mail.sh
python -m app.cli sync-gmail-auto
python -m app.cli sync-gmail-incremental
```

フル同期を手動でやり直す場合:

```bash
python -m app.cli sync-gmail-full
python -m app.cli list-mail --limit 10
```

`scripts/sync-mail.sh` のログは `data/logs/mail-sync.log` に残りますが、メール件名や差出人一覧は出力しません。

## Digest

通常の digest:

```bash
./scripts/build-digest.sh
python -m app.cli build-digest
```

ローカル LLM を使う digest:

```bash
FORME_AUTO_DIGEST_WITH_LOCAL_LLM=1 ./scripts/build-digest.sh
python -m app.cli build-digest-local
```

## 主なコマンド

```bash
python -m app.cli init-db
python -m app.cli seed-sources
python -m app.cli seed-demo
python -m app.cli build-digest
python -m app.cli build-digest-local
python -m app.cli migrate-raw-to-blobs
python -m app.cli summarize-note-local --note-id 1
python -m app.cli scan-sources
python -m app.cli scan-sources --include-login-required
python -m app.cli sync-gmail-auto
python -m app.cli sync-gmail-full
python -m app.cli sync-gmail-incremental
python -m app.cli list-mail --limit 10
python -m app.cli show-config
```

## 補助スクリプト

- ダッシュボード起動: `scripts/start-dashboard.sh`
- ダッシュボードをブラウザで開く: `scripts/open-dashboard.sh`
- 初回 Gmail 同期: `scripts/first-gmail-sync.sh`
- 定期 Gmail 同期: `scripts/sync-mail.sh`
- ソーススキャン: `scripts/scan-sources.sh`
- digest 生成: `scripts/build-digest.sh [manual|morning|evening]`
- launchd plist 生成: `scripts/render-launchd-plists.sh [output-dir]`
- GCP ブートストラップ: `scripts/gcp-bootstrap.sh <project-id> [project-name]`
- MLX モデル準備: `scripts/install-mlx-gemma.sh`
- 面接メモ要約: `scripts/summarize-note-local.sh <note-id>`

## launchd テンプレート

```bash
cd /path/to/forme-local
./scripts/render-launchd-plists.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.mail-sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.source-scan.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.digest-morning.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.digest-evening.plist
```

公開リポジトリにはマシン固有パスを含む `.plist` を直接置かず、`ops/launchd/templates/` のテンプレートから各マシンで生成します。
digest 用テンプレートは `scripts/build-digest.sh morning|evening` を実行し、メール送信はしません。

## 公開リポジトリとして扱う場合の注意

- `auth/`, `data/`, `playwright/.auth/`, `.env`, `.env.local` は公開しません。
- 実メール、実ログ、実カレンダーの画面キャプチャはそのまま載せません。
- 実運用の launchd `.plist` は tracked せず、テンプレートから生成します。
- 公開前に `./scripts/preflight-github-check.sh` を実行します。
