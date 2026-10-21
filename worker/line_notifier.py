"""LINE Messaging API 通訊輔助函式 (影片下載與推播訊息)。"""
from pathlib import Path
from typing import Dict, List


def _download_line_video(message_id: str, line_access_token: str, dest_path: Path) -> bool:
    """從 LINE Messaging API Blob 端點下載使用者上傳的原始影片。"""
    import requests

    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {line_access_token}"}
    resp = requests.get(url, headers=headers, stream=True, timeout=60)
    if resp.status_code != 200:
        print(f"LINE 影片下載失敗: HTTP {resp.status_code} - {resp.text}")
        return False

    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return True


def _push_line_messages(target_id: str, line_access_token: str, messages: List[Dict]) -> None:
    """呼叫 LINE Push Message API 將處理完成的軌跡影片與分析報告圖片傳回聊天室。"""
    import requests

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {line_access_token}",
    }
    payload = {"to": target_id, "messages": messages}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"LINE Push Message 失敗: HTTP {resp.status_code} - {resp.text}")
