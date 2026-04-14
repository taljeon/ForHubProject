#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "使い方: $0 <project-id> [project-name]"
  exit 1
fi

PROJECT_ID="$1"
PROJECT_NAME="${2:-Forme JobHub}"
ACCOUNT_EXPECTED="${GCP_ACCOUNT_EXPECTED:-}"

ACTIVE_ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
if [[ -n "$ACCOUNT_EXPECTED" && "$ACTIVE_ACCOUNT" != "$ACCOUNT_EXPECTED" ]]; then
  echo "現在の gcloud account は '$ACTIVE_ACCOUNT' です。"
  echo "'$ACCOUNT_EXPECTED' に切り替えてから再実行してください:"
  echo "  gcloud config configurations activate <your-config>"
  echo "  gcloud config set account $ACCOUNT_EXPECTED"
  exit 1
fi

echo "プロジェクトを作成します: $PROJECT_ID ($PROJECT_NAME)"
gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME" || true
gcloud config set project "$PROJECT_ID"
gcloud services enable gmail.googleapis.com

cat <<EOF

'$PROJECT_ID' の CLI 初期設定が完了しました。

次に Google Cloud Console で Desktop OAuth client を作成してください:
1. Google Auth Platform > Branding を開く
2. アプリ名とサポートメールを設定する
3. Audience を External にする
4. 必要なら自分の Google アカウントを test user に追加する
5. Data Access に https://www.googleapis.com/auth/gmail.readonly を追加する
6. Clients > Create Client > Desktop app を作成する
7. JSON をダウンロードして次へ保存する:
   $ROOT_DIR/auth/google-oauth/credentials.json

その後、次を実行します:
  cd $ROOT_DIR
  ./scripts/first-gmail-sync.sh
EOF
