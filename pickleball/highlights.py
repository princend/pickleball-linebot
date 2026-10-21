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

# 動態檢索關鍵字庫 (輪替檢索國內外頂級巡迴賽最新賽事剪輯)
HIGHLIGHT_SEARCH_KEYWORDS: List[str] = [
    "PPA Tour highlights",
    "Major League Pickleball highlights",
    "pickleball match highlights",
    "pickleball championship highlights",
    "pickleball tournament highlights",
    "PPA pickleball final",
    "MLP pickleball highlights",
]

# 非純賽事精華黑名單關鍵字（過濾 YouTuber 評論、訪談、教學、開箱與覆盤影片）
DISQUALIFIED_KEYWORDS: List[str] = [
    "reaction",
    "review",
    "commentary",
    "breakdown",
    "podcast",
    "interview",
    "discussion",
    "vlog",
    "opinion",
    "tier list",
    "live stream",
    "livestream",
    "talk",
    "q&a",
    "how to",
    "tutorial",
    "drill",
    "paddle",
    "評論",
    "覆盤",
    "复盘",
    "解說",
    "解说",
    "開箱",
    "开箱",
    "專訪",
    "专访",
    "訪談",
    "访谈",
    "閒聊",
    "闲聊",
    "評測",
    "评测",
    "分析",
    "教學",
    "心得",
]

# 官方與頂級職業賽事頻道白名單特徵（優先挑選）
OFFICIAL_CHANNELS: List[str] = [
    "ppa tour",
    "major league pickleball",
    "mlp",
    "pickleball channel",
    "selkirk tv",
    "pickleball tv",
    "usa pickleball",
    "app tour",
]


def get_pickleball_highlight_video(custom_query: Optional[str] = None) -> Optional[Dict[str, str]]:
    """即時透過 YouTube Data API 動態檢索一部最新匹克球賽事精華影片。

    多重過濾機制：
    1. 限制時長為中等（4~20 分鐘），避免長篇 Podcast 或短影音。
    2. 黑名單排除：剔除個人評論、開箱、戰術覆盤與閒聊影片。
    3. 官方頻道優先：若候選中包含 PPA/MLP 官方轉播，第一優先選用。
    """
    try:
        query = custom_query or random.choice(HIGHLIGHT_SEARCH_KEYWORDS)
        
        # 1. 先以 medium 時長檢索最新 15 筆影片
        search_results = search_youtube_videos(query, max_results=15, order="date", video_duration="medium")
        if not search_results:
            # 防呆降級：若無時長結果，退回無時長限制檢索
            search_results = search_youtube_videos(query, max_results=15, order="date")

        if search_results and len(search_results) > 0:
            # 2. 黑名單過濾：剔除標題包含評論、解說、專訪等雜訊的影片
            filtered: List[Dict[str, str]] = []
            for video in search_results:
                title_lower = video.get("title", "").lower()
                if any(bad_kw in title_lower for bad_kw in DISQUALIFIED_KEYWORDS):
                    continue
                filtered.append(video)

            # 若全部被過濾，退回未過濾名單避免無影片可看
            candidates = filtered if filtered else search_results

            # 3. 官方頻道優先挑選（PPA Tour / MLP 等）
            picked: Optional[Dict[str, str]] = None
            is_official = False
            for video in candidates:
                channel_lower = video.get("channel", "").lower()
                if any(official in channel_lower for official in OFFICIAL_CHANNELS):
                    picked = video
                    is_official = True
                    break

            # 4. 若無官方頻道，選取符合篩選條件的第一部（依日期最新）
            if not picked and candidates:
                picked = candidates[0]

            if picked:
                published_at = picked.get("published_at", "")
                pub_date = published_at[:10] if published_at else ""
                badge = "官方賽事精華" if is_official else "最新賽事精華"
                return {
                    "title": picked.get("title", "匹克球精彩賽事剪輯"),
                    "channel": picked.get("channel", "YouTube 賽事精選"),
                    "url": picked.get("url", ""),
                    "thumbnail_url": picked.get("thumbnail_url", ""),
                    "badge": badge,
                    "published_at": pub_date,
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
    badge = video.get("badge", "最新賽事精華")
    published_at = video.get("published_at", "")
    info_text = f"頻道：{channel} • 發布日期：{published_at}" if published_at else f"頻道：{channel}"

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
                    text=info_text,
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
