# Salesforce Status Slack Bot

Salesforce Services の日本インスタンス（`countryCode: JP`）のステータスを 15 分ごとに監視し、障害発生・復旧時に Slack へ自動通知する GitHub Actions ボットです。

**Slack ワークフロービルダーの Webhook** を使うため、ワークスペース管理者の許可不要で動作します。

## 仕組み

```
GitHub Actions (Cron: */15 * * * *)
  └─ check_status.py
       ├─ Salesforce Status API から JP インスタンスを取得
       ├─ state.json（Actions Cache）と差分比較
       └─ 変化あり → Slack ワークフロー Webhook URL に POST → チャンネルへ投稿
```

---

## セットアップ

### 1. Slack ワークフローを作成して Webhook URL を取得する

1. Slack で **ワークフロービルダー** を開く（左サイドバー「その他」→「自動化」）
2. 「新しいワークフロー」→「ゼロから作成」
3. トリガーに **「Webhook から」** を選択
4. データ変数を追加：
   - キー: `message`
   - データタイプ: `テキスト`
5. 「続行する」→ 次のステップで **「メッセージを送信する」** を追加
6. 投稿先チャンネルを選択し、本文に `{{message}}` を入力
7. ワークフローを公開 → 表示された **Webhook URL** をコピー

### 2. GitHub Secrets に登録する

```
リポジトリ → Settings → Secrets and variables → Actions → New repository secret
```

| Secret 名 | 内容 |
|---|---|
| `SLACK_WEBHOOK_URL` | 手順 1 でコピーした Webhook URL |

### 3. GitHub Actions を有効にして動作確認する

リポジトリの **Actions** タブを開き、ワークフローを有効化します。  
**Run workflow** ボタンで手動実行して Slack への投稿を確認してください。

> 初回実行時は `state.json` がないため、現在アクティブな全 JP インスタンスが「新規」として通知されます。2 回目以降は差分のみ通知されます。

---

## 監視対象

- **製品**: Salesforce Services
- **対象インスタンス**: `countryCode == "JP"` かつ `isActive == true`（日本のみ）
- **通知条件**: ステータス変化（OK → 障害 / 障害 → OK）または新規インシデント発生

| ステータス | 意味 |
|---|---|
| `OK` | ✅ 正常稼働 |
| `MINOR_INCIDENT_CORE` | ⚠️ 軽微な障害 |
| `MAJOR_INCIDENT_CORE` | 🔴 重大な障害 |
| `MAINTENANCE` | 🔵 メンテナンス中 |
| `INFORMATIONAL` | ℹ️ 情報提供のみ |

---

## ファイル構成

```
SlackBot/
├── .github/
│   └── workflows/
│       └── salesforce-status.yml   # Cron 定義（15分ごと）
├── check_status.py                  # メインスクリプト
├── requirements.txt                 # 依存ライブラリ（requests のみ）
└── README.md
```

---

## ローカルでのテスト

```bash
pip install -r requirements.txt
export SLACK_WEBHOOK_URL="https://hooks.slack.com/triggers/..."
python check_status.py
```
