# Job Operations Design Summary

この文書は `Forme JobHub` の公開向け設計要約です。  
詳細な運用基準は [job-operations-design.md](./job-operations-design.md) にあります。

## 1. 目的

Forme JobHub は、就職活動の個人運用を一つの画面で管理するためのアプリです。

重視する対象:
- Google Calendar
- Google Tasks
- MyPage / ログイン ID
- 応募状況
- 面接メモ / 個人資料

メール解析は主役ではなく、これらを更新するための補助入力として扱います。

## 2. 基本パイプライン

すべての処理は次の流れに沿います。

`collect -> parse -> normalize -> link -> derive -> sync -> serve`

意味:
- `collect`: Gmail や手入力から原本を集める
- `parse`: 件名、本文、URL、日時などの事実を抽出する
- `normalize`: 会社名や選考段階を正規化する
- `link`: メールと会社、アカウント、応募、段階を結び付ける
- `derive`: 現在状態、次アクション、Calendar / Tasks 候補を計算する
- `sync`: Google Calendar / Google Tasks に反映する
- `serve`: ダッシュボードと確認画面に表示する

## 3. 主要データモデル

### Mail
- `mail_messages`: Gmail 原本の保存
- `mail_observations`: メールから抽出した事実の保存

### Account / Application
- `site_accounts`: MyPage URL、ログイン ID、Vault 参照
- `applications`: 応募単位の状態

### Stage
- `application_stages`: 選考段階ごとの状態スナップショット
- `selection_events`: 個別日程や Calendar 連携痕跡

### Sync
- `calendar_sync_records`: Calendar event との対応付け
- `task_items`: Google Tasks と同期する内部 Todo

## 4. Calendar と Tasks の分離

### Calendar に送るもの
- 面接
- 面談
- 予約済みテスト
- 時刻が確定した説明会

### Tasks に送るもの
- MyPage 登録
- エントリー
- ES 提出
- Web テスト受検
- 締切前アクション

方針:
- `Calendar は保守的`
- `Tasks は積極的`

## 5. LLM の位置付け

ローカル LLM は補助機能です。

許可:
- 面接ノート整理
- 個人資料 / 自己PR 整理
- あいまいなメール分類の補助
- 日程抽出の fallback

禁止:
- Calendar / Tasks の最終決定
- メール同期成功の判定
- 内部状態保存の唯一の根拠

つまり、LLM が止まっても運用は継続できる設計を優先します。
