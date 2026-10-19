"""匹克球 AI 球路軌跡追蹤 (TrackNetV3) 橋接與介面模組。

負責接收 LINE 使用者上傳的匹克球影片事件，並將任務非同步派發至雲端 GPU Worker (Modal TrackNetV3)，
待雲端完成時空熱力圖推論、InpaintNet 軌跡修補與霓虹拋物線特效渲染後，主動推播影片回聊天室。
"""

from typing import Optional, Tuple
import requests
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexMessage,
    FlexSeparator,
    FlexText,
    MessageAction,
    QuickReply,
    QuickReplyItem,
)

import config


def get_trajectory_cancel_quick_reply() -> QuickReply:
    """建立取消等待上傳軌跡影片的 QuickReply 按鈕。"""
    return QuickReply(
        items=[
            QuickReplyItem(
                action=MessageAction(label="取消軌跡分析", text="取消軌跡分析")
            )
        ]
    )


def create_trajectory_guide_flex() -> FlexMessage:
    """建立引導使用者上傳匹克球影片進行 TrackNetV3 軌跡追蹤的說明卡片。"""
    bubble = FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#CCFF00",
            padding_all="md",
            contents=[
                FlexText(
                    text="AI 匹克球軌跡追蹤 (TrackNetV3)",
                    weight="bold",
                    size="md",
                    color="#1F2937",
                ),
                FlexText(
                    text="高速小球時空熱力圖偵測與霓虹拋物線渲染",
                    size="xxs",
                    color="#4B5563",
                    margin="xs",
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=[
                FlexText(
                    text="請直接在聊天室「上傳一段匹克球影片」，AI 將自動追蹤球體座標並繪製飛行軌跡回傳給您！",
                    size="sm",
                    weight="bold",
                    color="#1E3A8A",
                    wrap=True,
                ),
                FlexSeparator(margin="md"),
                FlexBox(
                    layout="vertical",
                    background_color="#F8FAFC",
                    corner_radius="md",
                    padding_all="sm",
                    margin="md",
                    spacing="xs",
                    contents=[
                        FlexText(
                            text="最佳拍攝建議",
                            weight="bold",
                            size="xs",
                            color="#334155",
                        ),
                        FlexText(
                            text="1. 影片長度：建議 5 至 15 秒（單一精彩來回回合）\n2. 拍攝視角：手機或相機固定於底線後方或側高角度，避免劇烈晃動\n3. 繪製效果：自動產生霓虹彗星殘影、拋物線平滑修補與落地點標記",
                            size="xs",
                            color="#475569",
                            wrap=True,
                            line_spacing="4px",
                        ),
                    ],
                ),
            ],
        ),
        footer=FlexBox(
            layout="vertical",
            padding_all="sm",
            contents=[
                FlexButton(
                    style="secondary",
                    height="sm",
                    action=MessageAction(label="取消上傳", text="取消軌跡分析"),
                )
            ],
        ),
    )

    return FlexMessage(
        alt_text="請上傳匹克球影片以進行 AI 球路軌跡追蹤",
        contents=bubble,
        quick_reply=get_trajectory_cancel_quick_reply(),
    )


def trigger_trajectory_worker(
    message_id: str,
    target_id: str,
    user_id: str,
) -> Tuple[bool, str]:
    """將 LINE 影片訊息 ID 派發給雲端 TrackNetV3 GPU Worker 進行非同步軌跡渲染。

    Args:
        message_id: LINE 影片訊息的 message.id (供 Worker 下載影片二進位串流)
        target_id: 推播回傳的目標 ID (group_id / room_id / user_id)
        user_id: 觸發上傳的使用者 ID

    Returns:
        (success, status_message)
    """
    worker_url = (config.tracknet_worker_url or "").strip().rstrip("/")
    if not worker_url:
        return (
            False,
            "尚未設定雲端 GPU 軌跡運算伺服器 (TRACKNET_WORKER_URL)。\n"
            "請先部署專案內的 worker/modal_tracknet_worker.py 至 Modal，並將產生的網址填入環境變數 TRACKNET_WORKER_URL。",
        )

    endpoint = worker_url if worker_url.endswith("/analyze") else f"{worker_url}/analyze"

    payload = {
        "message_id": message_id,
        "target_id": target_id,
        "user_id": user_id,
        "line_access_token": config.line_channel_access_token,
    }
    headers = {"Content-Type": "application/json"}
    if config.tracknet_worker_secret:
        headers["X-Worker-Secret"] = config.tracknet_worker_secret

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=8)
        if resp.status_code in (200, 202):
            return (
                True,
                "已收到您的匹克球影片！\n"
                "AI (TrackNetV3 + InpaintNet) 正在雲端 GPU 逐幀追蹤球路並繪製霓虹飛行軌跡，約需 20 至 45 秒，完成後將自動把影片傳送至聊天室！",
            )
        return (
            False,
            f"雲端軌跡運算伺服器回應異常 (HTTP {resp.status_code})，請稍後再試。",
        )
    except requests.exceptions.Timeout:
        # 即使冷啟動超過 8 秒，Modal 端通常已收到請求並排入背景執行
        return (
            True,
            "已收到您的匹克球影片！\n"
            "正在喚醒雲端 GPU 並啟動 TrackNetV3 追蹤球路，約需 30 至 60 秒，完成後將自動把軌跡影片傳送至聊天室！",
        )
    except Exception as e:
        print(f"Trigger Trajectory Worker Error: {e}")
        return (
            False,
            "無法連線至雲端軌跡運算伺服器，請確認 TRACKNET_WORKER_URL 設定是否正確。",
        )
