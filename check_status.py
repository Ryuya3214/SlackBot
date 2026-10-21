"""
Salesforce Services ステータス監視 → Slack ワークフロー Webhook 通知スクリプト

監視対象: TARGET_INSTANCES に列挙したインスタンスのサービスごとのインシデント
通知条件: 新規インシデント発生・既存インシデント復旧（Resolved）
通知方法: Slack ワークフロービルダーの Webhook URL に POST
"""

import json
import os
import sys
from pathlib import Path

import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
STATE_FILE = Path("state.json")

# 監視対象インスタンス: キー → 表示名
TARGET_INSTANCES = {
    "JPN156": "本番環境",
    "JPN6S": "Systest環境",
}

# サービスキー → 日本語表示名
SERVICE_LABEL = {
    "coreService": "コアサービス",
    "Agentforce": "Agentforce",
    "AgentforceContactCenter": "Agentforce Contact Center",
    "AgentforceVoice": "Agentforce Voice",
    "analytics": "Analytics",
    "B2BCommerce": "B2B Commerce",
    "B2B2CCommerce": "B2B2C Commerce",
    "Communities": "Experience Cloud (Communities)",
    "CPQandBilling": "CPQ & Billing",
    "Customer360Audiences": "Marketing Cloud CDP",
    "EinsteinBots": "Einstein Bots",
    "FieldServiceCorePlatform": "Field Service Core Platform",
    "FieldServiceMobile": "Field Service Mobile",
    "FieldServiceScheduling": "Field Service Scheduling",
    "FieldServiceVRA": "Field Service VRA",
    "liveAgent": "Live Agent",
    "MCGrowth": "Marketing Cloud Growth",
    "PromptStudio": "Prompt Studio",
    "SalesforceCMS": "Salesforce CMS",
    "SALESFORCEORDERMANAGEMENT": "Order Management",
    "SalesforceUnifiedMessaging": "Unified Messaging",
    "ServiceCloudMessagingChannels": "Service Cloud Messaging",
    "ServiceCloudVoice": "Service Cloud Voice",
    "search": "検索 (Search)",
}

# インシデントステータス → 日本語ラベル
INCIDENT_STATUS_LABEL = {
    "Active": "🔴 発生中",
    "Degradation": "⚠️ 障害発生",
    "Resolved": "✅ 復旧",
    "Maintenance": "🔵 メンテナンス",
}

# インシデントタイプ → 日本語ラベル
INCIDENT_TYPE_LABEL = {
    "Degradation": "障害",
    "Maintenance": "メンテナンス",
    "Informational": "情報",
}


def fetch_instance_status(instance_key: str) -> dict:
    url = f"https://api.status.salesforce.com/v1/instances/{instance_key}/status"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_active_incidents(data: dict) -> dict[int, dict]:
    """アクティブ（未解決）なインシデントを id をキーとして返す。"""
    result = {}
    for inc in data.get("Incidents", []):
        if inc.get("status") != "Resolved":
            result[inc["id"]] = {
                "status": inc.get("status", ""),
                "type": inc.get("type", ""),
                "service_keys": inc.get("serviceKeys", []),
                "is_core": inc.get("isCore", False),
            }
    return result


def load_previous_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_current_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_changes(prev_state: dict, curr_state: dict) -> list[dict]:
    """
    curr_state / prev_state の構造:
      { "JPN156": { incident_id(int): {...}, ... }, "JPN6S": {...} }
    """
    changes = []

    for instance_key, env_label in TARGET_INSTANCES.items():
        prev_incidents = prev_state.get(instance_key, {})
        curr_incidents = curr_state.get(instance_key, {})

        # prev のキーは JSON のため文字列になっている可能性があるので int に統一
        prev_incidents = {int(k): v for k, v in prev_incidents.items()}

        # 新規インシデント（前回になかったもの）
        for inc_id, inc_info in curr_incidents.items():
            if inc_id not in prev_incidents:
                changes.append({
                    "change_type": "new",
                    "instance_key": instance_key,
                    "env_label": env_label,
                    "incident_id": inc_id,
                    "incident_status": inc_info["status"],
                    "incident_type": inc_info["type"],
                    "service_keys": inc_info["service_keys"],
                    "is_core": inc_info["is_core"],
                })

        # 復旧インシデント（前回あったが今回なくなったもの）
        for inc_id, inc_info in prev_incidents.items():
            if inc_id not in curr_incidents:
                changes.append({
                    "change_type": "resolved",
                    "instance_key": instance_key,
                    "env_label": env_label,
                    "incident_id": inc_id,
                    "incident_status": "Resolved",
                    "incident_type": inc_info["type"],
                    "service_keys": inc_info["service_keys"],
                    "is_core": inc_info["is_core"],
                })

    return changes


def format_service_names(service_keys: list[str]) -> str:
    labels = [SERVICE_LABEL.get(k, k) for k in service_keys]
    return "、".join(labels) if labels else "不明"


def format_message(changes: list[dict]) -> str:
    lines = ["*Salesforce ステータス変化通知*"]

    for ch in changes:
        env_label = ch["env_label"]
        instance_key = ch["instance_key"]
        services = format_service_names(ch["service_keys"])
        inc_type = INCIDENT_TYPE_LABEL.get(ch["incident_type"], ch["incident_type"])
        status_label = INCIDENT_STATUS_LABEL.get(ch["incident_status"], ch["incident_status"])
        core_mark = "【コア】" if ch["is_core"] else ""
        url = f"https://status.salesforce.com/instances/{instance_key}"

        if ch["change_type"] == "new":
            lines.append(
                f"{status_label} [{env_label}] {core_mark}{inc_type}発生\n"
                f"  対象サービス: {services}\n"
                f"  詳細: {url}"
            )
        elif ch["change_type"] == "resolved":
            lines.append(
                f"{status_label} [{env_label}] {core_mark}{inc_type}復旧\n"
                f"  対象サービス: {services}\n"
                f"  詳細: {url}"
            )

    return "\n".join(lines)


def post_to_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL が設定されていません。", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"message": message},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()


def main() -> None:
    print("Salesforce インスタンスステータスを取得中…")

    curr_state = {}
    for instance_key, env_label in TARGET_INSTANCES.items():
        data = fetch_instance_status(instance_key)
        active = extract_active_incidents(data)
        curr_state[instance_key] = active
        print(f"  {instance_key} ({env_label}): アクティブインシデント {len(active)} 件")

    prev_state = load_previous_state()
    changes = build_changes(prev_state, curr_state)

    save_current_state(curr_state)

    if not changes:
        print("変化なし。Slack への通知はスキップします。")
        return

    print(f"{len(changes)} 件の変化を検知しました。Slack に通知します。")
    message = format_message(changes)
    post_to_slack(message)
    print("Slack への投稿が完了しました。")


if __name__ == "__main__":
    main()
