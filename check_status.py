"""
Salesforce Services ステータス監視 → Slack ワークフロー Webhook 通知スクリプト

監視対象: TARGET_INSTANCES に列挙したインスタンスのみ
通知条件: 前回実行時からステータスが変化したとき、または新規インシデント発生時
通知方法: Slack ワークフロービルダーの Webhook URL に POST
"""

import json
import os
import sys
from pathlib import Path

import requests

SALESFORCE_API_URL = "https://api.status.salesforce.com/v1/products/Salesforce_Services"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
STATE_FILE = Path("state.json")

# 監視対象インスタンス: キー → 表示名
TARGET_INSTANCES = {
    "JPN156": "本番環境",
    "JPN6S": "Systest環境",
}

STATUS_LABEL = {
    "OK": "✅ 正常",
    "MINOR_INCIDENT_CORE": "⚠️ 軽微な障害",
    "MAJOR_INCIDENT_CORE": "🔴 重大な障害",
    "MAINTENANCE": "🔵 メンテナンス中",
    "INFORMATIONAL": "ℹ️ 情報",
}


def fetch_status() -> dict:
    resp = requests.get(SALESFORCE_API_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_target_instances(data: dict) -> dict[str, dict]:
    """TARGET_INSTANCES に指定したインスタンスのみ抽出する。"""
    result = {}
    for instance in data.get("Instances", []):
        key = instance["key"]
        if key in TARGET_INSTANCES:
            result[key] = {
                "status": instance.get("status", "UNKNOWN"),
                "city": instance.get("city", ""),
                "environment": instance.get("environment", ""),
                "env_label": TARGET_INSTANCES[key],
                "incident_ids": sorted(
                    inc["id"] for inc in instance.get("Incidents", []) if "id" in inc
                ),
            }
    return result


def load_previous_state() -> dict[str, dict]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_current_state(state: dict[str, dict]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_changes(prev: dict, curr: dict) -> list[dict]:
    changes = []
    all_keys = set(prev) | set(curr)
    for key in sorted(all_keys):
        prev_info = prev.get(key)
        curr_info = curr.get(key)

        env_label = TARGET_INSTANCES.get(key, key)
        info = curr_info or prev_info
        city = info["city"]

        if prev_info is None:
            # 初回検出はスキップ（初回起動時の全件通知を抑制）
            pass
        elif curr_info is None:
            changes.append({
                "key": key,
                "type": "removed",
                "city": city,
                "env_label": env_label,
                "prev_status": prev_info["status"],
                "curr_status": None,
                "new_incidents": [],
            })
        else:
            status_changed = prev_info["status"] != curr_info["status"]
            new_incidents = [
                iid for iid in curr_info["incident_ids"]
                if iid not in prev_info["incident_ids"]
            ]
            if status_changed or new_incidents:
                changes.append({
                    "key": key,
                    "type": "changed",
                    "city": city,
                    "env_label": env_label,
                    "prev_status": prev_info["status"],
                    "curr_status": curr_info["status"],
                    "new_incidents": new_incidents,
                })
    return changes


def format_message(changes: list[dict]) -> str:
    """変化一覧をテキストメッセージに変換する。"""
    lines = ["*Salesforce ステータス変化通知*"]

    for ch in changes:
        key = ch["key"]
        city = ch["city"] or "—"
        env_label = ch["env_label"]
        curr_label = STATUS_LABEL.get(ch["curr_status"], ch["curr_status"] or "—")
        prev_label = STATUS_LABEL.get(ch["prev_status"], ch["prev_status"] or "—")

        if ch["type"] == "changed":
            lines.append(f"[{env_label}] {key} ({city}): {prev_label} → {curr_label}")
        elif ch["type"] == "removed":
            lines.append(f"[{env_label}] {key} ({city}) → 非アクティブ")

        for iid in ch["new_incidents"]:
            lines.append(f"  インシデント: https://status.salesforce.com/instances/{key}")

    lines.append("詳細: https://status.salesforce.com/products/Salesforce_Services")
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
    print("Salesforce Status API を取得中…")
    data = fetch_status()

    curr_state = extract_target_instances(data)
    print(f"監視対象インスタンス数: {len(curr_state)} ({', '.join(curr_state.keys())})")

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
