"""匹克球球場查詢模組。

即時爬取 ipickleball.com.tw 各縣市球場資料，提供 LINE Flex 卡片與 QuickReply 縣市選單。
每張卡片顯示球場名稱、今日營業時間、收費資訊與 LINE 群連結（若有）。
嚴格遵守無表情符號規範 (No Emoji Policy)。
"""

import re
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexCarousel,
    FlexMessage,
    FlexSeparator,
    FlexText,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    URIAction,
)

# 縣市名稱對應 URL slug（僅列出有球場資料的縣市）
COUNTIES: Dict[str, str] = {
    "台北市": "taipei-city",
    "新北市": "new-taipei-city",
    "台中": "taichung",
    "新竹": "hsinchu",
    "桃園": "taoyuan",
    "宜蘭": "yilan",
    "彰化": "changhua",
    "高雄": "kaohsiung",
    "台南": "tainan",
    "嘉義": "chiayi",
    "雲林": "yunlin",
    "南投": "nantou",
    "屏東": "pngtung",
    "基隆": "keelung",
    "花蓮": "hualien",
}

BASE_URL = "https://ipickleball.com.tw/places/category"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 10


def _safe_text(element, default: str = "") -> str:
    """安全取得 BeautifulSoup element 的純文字，去除多餘空白。"""
    if element is None:
        return default
    return element.get_text(strip=True)


def scrape_courts_by_county(county_slug: str) -> Tuple[List[Dict], str]:
    """爬取指定縣市的球場列表（僅第 1 頁，最多 10 筆）。

    傳回:
        (courts, more_url)
        courts: 球場資料 list，每筆含 name, url, hours, price, line_url
        more_url: 該縣市在 ipickleball.com.tw 的完整列表網址
    """
    url = f"{BASE_URL}/{county_slug}/"
    courts: List[Dict] = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return courts, url

    soup = BeautifulSoup(resp.text, "html.parser")

    # 每個球場卡片的根節點（GeoDirectory 主題使用 .card 搭配 geodir-entry-title）
    title_links = soup.select("h2.geodir-entry-title a")

    for link in title_links:
        name = link.get_text(strip=True)
        court_url = link.get("href", "")

        # 找到該卡片的父層容器（向上找到包含所有欄位的 card 區塊）
        card = link.find_parent("div", class_=lambda c: c and "card" in c.split())
        if card is None:
            courts.append({
                "name": name,
                "url": court_url,
                "hours": "未知",
                "price": "未知",
                "line_url": None,
            })
            continue

        # 今日營業時間
        hours_el = card.select_one(".gd-bh-today-range")
        hours = _safe_text(hours_el, "未提供") if hours_el else "未提供"
        # 統一格式
        if hours in ("Open 24 hours",):
            hours = "全天開放"
        elif hours == "Closed":
            hours = "今日休息"

        # 收費
        price_el = card.select_one(".geodir-field-cf1763282984")
        if price_el:
            price_text = _safe_text(price_el)
            # 移除「收費:」標籤
            price_text = re.sub(r"收費\s*[:：]?\s*", "", price_text).strip()
            price = price_text if price_text else "未提供"
            if price == "0":
                price = "免費"
        else:
            price = "未提供"

        # LINE 群連結
        line_el = card.select_one(".geodir-field-line_ a")
        line_url = line_el.get("href") if line_el else None

        courts.append({
            "name": name,
            "url": court_url,
            "hours": hours,
            "price": price,
            "line_url": line_url,
        })

    return courts, url


def get_county_quick_reply() -> QuickReply:
    """產生縣市選擇 QuickReply，供「查球場」指令使用。

    LINE QuickReply 上限 13 個，優先顯示球場數最多的縣市（前 12 個），
    最後一個保留給「取消」按鈕。
    """
    items = []
    # 依照 COUNTIES 定義順序（已依球場數量由多到少排列），取前 12 個
    display_counties = list(COUNTIES.keys())[:12]

    for county_name in display_counties:
        slug = COUNTIES[county_name]
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=county_name,
                    data=f"action=pickle_courts&county={slug}&name={county_name}",
                    display_text=f"查詢 {county_name} 球場",
                )
            )
        )

    # 取消按鈕
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="取消",
                data="action=pickle_action&sub=cancel",
                display_text="取消",
            )
        )
    )

    return QuickReply(items=items)


def _build_court_bubble(court: Dict, index: int) -> FlexBubble:
    """建構單一球場的 Flex Bubble 卡片。"""
    name = court.get("name", "未知球場")
    court_url = court.get("url", "")
    hours = court.get("hours", "未提供")
    price = court.get("price", "未提供")
    line_url = court.get("line_url")

    # 標頭
    header_contents = [
        FlexText(
            text=f"{index}. {name}",
            weight="bold",
            size="sm",
            color="#FFFFFF",
            wrap=True,
        )
    ]

    # 主體內容列
    body_contents = [
        FlexBox(
            layout="horizontal",
            spacing="xs",
            contents=[
                FlexText(
                    text="營業時間",
                    size="xs",
                    color="#6B7280",
                    flex=3,
                ),
                FlexText(
                    text=hours,
                    size="xs",
                    color="#111827",
                    wrap=True,
                    flex=5,
                ),
            ],
        ),
        FlexSeparator(margin="xs"),
        FlexBox(
            layout="horizontal",
            spacing="xs",
            contents=[
                FlexText(
                    text="收費",
                    size="xs",
                    color="#6B7280",
                    flex=3,
                ),
                FlexText(
                    text=price,
                    size="xs",
                    color="#111827",
                    wrap=True,
                    flex=5,
                ),
            ],
        ),
    ]

    # 底部操作按鈕
    footer_contents = []

    if court_url:
        footer_contents.append(
            FlexBox(
                layout="vertical",
                contents=[
                    FlexText(
                        text="查看詳情",
                        size="xs",
                        color="#2563EB",
                        align="center",
                        action=URIAction(label="查看詳情", uri=court_url),
                    )
                ],
            )
        )

    if line_url:
        if footer_contents:
            footer_contents.append(FlexSeparator())
        footer_contents.append(
            FlexBox(
                layout="vertical",
                contents=[
                    FlexText(
                        text="加入 LINE 群",
                        size="xs",
                        color="#06C755",
                        align="center",
                        action=URIAction(label="加入 LINE 群", uri=line_url),
                    )
                ],
            )
        )

    return FlexBubble(
        size="kilo",
        header=FlexBox(
            layout="vertical",
            background_color="#1E40AF",
            padding_all="md",
            contents=header_contents,
        ),
        body=FlexBox(
            layout="vertical",
            spacing="sm",
            padding_all="md",
            contents=body_contents,
        ),
        footer=FlexBox(
            layout="vertical",
            spacing="sm",
            padding_all="sm",
            contents=footer_contents,
        ) if footer_contents else None,
    )


def create_courts_flex(
    courts: List[Dict],
    county_name: str,
    more_url: str,
) -> FlexMessage:
    """將球場列表包裝為 Flex Carousel 訊息。

    若球場數為 0，回傳提示 Bubble。
    若超過 10 筆，截斷並在最後一張卡片提示查看更多。
    """
    if not courts:
        bubble = FlexBubble(
            body=FlexBox(
                layout="vertical",
                contents=[
                    FlexText(
                        text=f"{county_name} 目前尚無球場資料",
                        wrap=True,
                        color="#6B7280",
                        size="sm",
                    ),
                    FlexText(
                        text="資料來源：ipickleball.com.tw",
                        size="xxs",
                        color="#9CA3AF",
                        margin="md",
                        action=URIAction(
                            label="前往網站",
                            uri=more_url,
                        ),
                    ),
                ],
            )
        )
        return FlexMessage(alt_text=f"{county_name} 目前尚無球場資料", contents=bubble)

    display_courts = courts[:10]
    bubbles = [
        _build_court_bubble(court, idx + 1)
        for idx, court in enumerate(display_courts)
    ]

    # 若有更多球場，加入「查看更多」尾卡
    total = len(courts)
    if total >= 10 or more_url:
        more_bubble = FlexBubble(
            size="kilo",
            body=FlexBox(
                layout="vertical",
                justify_content="center",
                spacing="md",
                padding_all="lg",
                contents=[
                    FlexText(
                        text=f"顯示前 {len(display_courts)} 筆",
                        size="xs",
                        color="#6B7280",
                        align="center",
                    ),
                    FlexText(
                        text="查看完整球場列表",
                        weight="bold",
                        size="sm",
                        color="#2563EB",
                        align="center",
                        action=URIAction(
                            label="查看更多",
                            uri=more_url,
                        ),
                    ),
                    FlexText(
                        text="資料來源：ipickleball.com.tw",
                        size="xxs",
                        color="#9CA3AF",
                        align="center",
                        margin="sm",
                    ),
                ],
            ),
        )
        bubbles.append(more_bubble)

    return FlexMessage(
        alt_text=f"{county_name} 匹克球球場列表（{len(display_courts)} 筆）",
        contents=FlexCarousel(contents=bubbles),
    )
