# Forme JobHub

Forme JobHub は、就職活動の個人運用をローカル中心で管理するためのアプリです。  
Gmail、応募状況、MyPage、Google Calendar、Google Tasks、メモを一つの運用画面にまとめることを目的にしています。

公開向けの設計要約は [docs/job-operations-design-ja.md](docs/job-operations-design-ja.md) にあります。  
実運用の詳細設計原本は [docs/job-operations-design.md](docs/job-operations-design.md) にあり、メール抽出、Calendar / Tasks 同期、今後のリファクタリング基準をこの文書群で固定しています。

公開前チェックは [docs/public-release-checklist.md](docs/public-release-checklist.md) を参照してください。  
このリポジトリは個人運用アプリ前提で作られているため、公開前には認証ファイル、サンプル値、スクリーンショット、ローカルパスの整理が必要です。

## 現在の範囲

- Gmail OAuth を使ったメール同期
- SQLite ベースのローカル状態管理
- 応募、サイトアカウント、MyPage、メモの管理 UI
- Google Calendar / Google Tasks 連携
- ローカル LLM を使った任意の補助機能

## ディレクトリ構成

```text
forme/
  app/
  auth/google-oauth/
  config/source_registry.json
  data/
  docs/
  playwright/.auth/
  pyproject.toml
```

## クイックスタート

```bash
cd /path/to/forme-local
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli migrate-raw-to-blobs
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

ブラウザで `http://127.0.0.1:8000` を開くとダッシュボードが見られます。

## Gmail 連携

1. Google Cloud で Gmail API を有効化します。
2. Desktop OAuth client を作成します。
3. `credentials.json` を `auth/google-oauth/credentials.json` に配置します。
4. 初回認証後の token は `auth/google-oauth/token.json` に保存されます。

初回フル同期:

```bash
python -m app.cli sync-gmail-full
```

増分同期:

```bash
python -m app.cli sync-gmail-incremental
```

通常運用:

```bash
python -m app.cli sync-gmail-auto
```

## Google Calendar 連携

面接、面談、テスト予約など、時刻が確定したイベントだけを Google Calendar に登録する設計です。

`.env` または `.env.local` に以下を設定します。

```bash
FORME_AUTO_CREATE_CALENDAR_EVENTS_FROM_MAIL="1"
FORME_GOOGLE_CALENDAR_ID="primary"
```

既存 token に必要 scope が足りない場合は、次の一回だけ再認証します。

```bash
python -m app.cli refresh-google-auth
```

保存済みメールを再処理したい場合:

```bash
python -m app.cli ingest-mail-links --force
```

## 主なコマンド

```bash
python -m app.cli init-db
python -m app.cli seed-sources
python -m app.cli seed-demo
python -m app.cli build-digest
python -m app.cli migrate-raw-to-blobs
python -m app.cli summarize-note-local --note-id 1
python -m app.cli scan-sources
python -m app.cli sync-gmail-auto
python -m app.cli sync-gmail-full
python -m app.cli sync-gmail-incremental
python -m app.cli sync-google-tasks
python -m app.cli refresh-google-auth
python -m app.cli show-config
python -m app.cli validate-local
```

## 環境変数

開始時は以下でサンプルファイルをコピーします。

```bash
cd /path/to/forme-local
cp .env.example .env
```

現在の設定確認:

```bash
python -m app.cli show-config
```

詳細は [docs/config.md](docs/config.md) を参照してください。

## ローカル LLM

現在の既定ランタイムは Apple Silicon 向けの `MLX / Metal` です。  
既定モデル alias は `gemma4:e4b-it-8bit` で、内部では `mlx-community/gemma-4-e4b-it-8bit` を使います。

セットアップ:

```bash
cd /path/to/forme-local
source .venv/bin/activate
pip install -e '.[local-llm]'
```

ノート要約の例:

```bash
./scripts/summarize-note-local.sh 1
```

## 推奨運用

- ダッシュボード: `scripts/start-dashboard.sh`
- Gmail 同期: `scripts/sync-mail.sh`
- ソーススキャン: `scripts/scan-sources.sh`
- digest 生成: `scripts/build-digest.sh`
- 初回 Gmail 認証: `scripts/first-gmail-sync.sh`
- ローカル検証: `scripts/validate-local.sh`
- GCP ブートストラップ: `scripts/gcp-bootstrap.sh <project-id> [project-name]`

## launchd テンプレート

```bash
cd /path/to/forme-local
./scripts/render-launchd-plists.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.mail-sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.source-scan.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.digest-morning.plist
```

公開リポジトリにはマシン固有パスを含む `.plist` を直接置かず、`ops/launchd/templates/` のテンプレートから各マシンで生成する方式を使います。

## 公開リポジトリとして扱う場合の注意

- `auth/`, `data/`, `playwright/.auth/`, `.env` は公開しません。
- 実メール、実カレンダー、実ログのスクリーンショットはそのまま載せません。
- launchd plist はテンプレートから生成し、マシン固有パスを含む実体ファイルを repo に tracked しません。
- 実運用インスタンスは非公開、コードと設計だけ公開する形が最も扱いやすいです。
