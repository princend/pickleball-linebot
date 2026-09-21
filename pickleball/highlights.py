"""匹克球 (Pickleball) YouTube 賽事精華推薦模組。

提供世界頂級匹克球巡迴賽事 (PPA Tour, MLP 等) 之精彩剪輯推薦。
完全透過 YouTube Data API 即時動態檢索真實影片，不使用任何寫死假資料。
"""

import random
from typing import Dict, List, Optional
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexImage,
    FlexMessage,
    FlexText,
    URIAction,
)
from ai.get_youtube_search import search_youtube_videos

# 動態檢索關鍵字庫 (輪替檢索真實 YouTube 賽事精彩剪輯)
HIGHLIGHT_SEARCH_KEYWORDS: List[str] = [
    "pickleball highlights best points",
    "PPA Tour pickleball highlights",
    "Major League Pickleball best rallies",
    "pickleball top 10 plays",
    "pickleball championship final highlights",
    "匹克球 賽事 精華",
    'pickleball highlights',
]


def get_pickleball_highlight_video(custom_query: Optional[str] = None) -> Optional[Dict[str, str]]:
    """即時透過 YouTube Data API 動態檢索一部真實匹克球賽事精華影片。

    不使用任何寫死之靜態假資料；若 API 異常或無搜尋結果則回傳 None。
    """
    try:
        query = custom_query or random.choice(HIGHLIGHT_SEARCH_KEYWORDS)
        search_results = search_youtube_videos(query, max_results=10)
        if search_results and len(search_results) > 0:
            picked = random.choice(search_results)
            return {
                "title": picked.get("title", "匹克球精彩賽事剪輯"),
                "channel": picked.get("channel", "YouTube 賽事精選"),
                "url": picked.get("url", ""),
                "thumbnail_url": picked.get("thumbnail_url", ""),
                "badge": "YouTube 即時精選",
            }
    except Exception as e:
        print(f"[錯誤] 匹克球 YouTube 即時搜尋發生例外: {e}", flush=True)

    return None


def create_pickleball_highlight_flex(video: Dict[str, str]) -> FlexMessage:
    """將匹克球賽事影片資料包裝為專屬的高質感 Flex Message 卡片。"""
    title = video.get("title", "匹克球精華賽事")
    channel = video.get("channel", "Pickleball Highlights")
    url = video.get("url", "https://www.youtube.com")
    thumbnail_url = video.get("thumbnail_url") or "https://images.unsplash.com/photo-1599474924187-334a4ae5bd3c?w=640&q=80"
    badge = video.get("badge", "YouTube 即時精選")

    bubble = FlexBubble(
        size="mega",
        hero=FlexImage(
            url=thumbnail_url,
            size="full",
            aspect_ratio="16:9",
            aspect_mode="cover",
            action=URIAction(uri=url, label="點擊觀看賽事"),
        ),
        body=FlexBox(
            layout="vertical",
            spacing="sm",
            contents=[
                FlexBox(
                    layout="horizontal",
                    contents=[
                        FlexText(
                            text=badge,
                            color="#0D9488",
                            size="xs",
                            weight="bold",
                        )
                    ],
                ),
                FlexText(
                    text=title,
                    weight="bold",
                    size="md",
                    wrap=True,
                    max_lines=2,
                    color="#1F2937",
                ),
                FlexText(
                    text=f"頻道：{channel}",
                    size="xs",
                    color="#6B7280",
                ),
            ],
        ),
        footer=FlexBox(
            layout="vertical",
            spacing="sm",
            contents=[
                FlexButton(
                    style="primary",
                    color="#FF0033",
                    action=URIAction(label="前往 YouTube 觀看", uri=url),
                )
            ],
        ),
    )

    alt_text = f"匹克球精彩賽事剪輯：{title}"
    return FlexMessage(alt_text=alt_text, contents=bubble)
