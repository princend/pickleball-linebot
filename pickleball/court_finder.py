"""匹克球球場查詢模組。

支援透過 Google Sheets 線上試算表即時讀取全台球場資料（支援行政區分組），
並提供 5 分鐘快取機制與本地 JSON 快照備援。
提供兩階段選擇（縣市 -> 行政區），並支援以「行政區」為單位展示卡片輪播。
"""

import csv
import io
import json
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple
import requests

from linebot.v3.messaging import (
    FlexBox,
    FlexButton,
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

# 縣市名稱對應 URL slug
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

COUNTY_ALIASES = {
    "臺北市": "taipei-city",
    "臺北": "taipei-city",
    "台北": "taipei-city",
    "新北": "new-taipei-city",
    "臺中市": "taichung",
    "臺中": "taichung",
    "台中市": "taichung",
    "新竹市": "hsinchu",
    "新竹縣": "hsinchu",
    "桃園市": "taoyuan",
    "宜蘭縣": "yilan",
    "彰化縣": "changhua",
    "高雄市": "kaohsiung",
    "臺南市": "tainan",
    "臺南": "tainan",
    "台南市": "tainan",
    "嘉義市": "chiayi",
    "嘉義縣": "chiayi",
    "雲林縣": "yunlin",
    "南投縣": "nantou",
    "屏東縣": "pngtung",
    "基隆市": "keelung",
    "花蓮縣": "hualien",
}

SLUG_TO_COUNTY = {v: k for k, v in COUNTIES.items()}

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "courts_data.json")

# Google Sheets 設定
SHEET_ID = "1Zphr-a547bmb0nTTNxz8p5A1dajAmLSOi-mO1NiRydw"
COURTS_SHEET_GID = os.environ.get("COURTS_SHEET_GID", "1386987707")
COURTS_SHEET_URL = os.environ.get(
    "COURTS_SHEET_URL",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={COURTS_SHEET_GID}"
)

COURTS_CACHE: Optional[Dict[str, dict]] = None
LAST_FETCH_TIME = 0


def _normalize_county_slug(raw_name: str) -> str:
    """將縣市名稱標準化為對應的 slug。"""
    clean_name = raw_name.strip()
    if clean_name in COUNTIES:
        return COUNTIES[clean_name]
    if clean_name in COUNTY_ALIASES:
        return COUNTY_ALIASES[clean_name]
    for k, v in COUNTIES.items():
        if k in clean_name or clean_name in k:
            return v
    return clean_name


def load_all_courts_data() -> Dict[str, dict]:
    """讀取全台球場資料，優先從 Google Sheets 讀取並具備 5 分鐘快取與本地 JSON 備援。"""
    global COURTS_CACHE, LAST_FETCH_TIME
    current_time = time.time()

    # 5 分鐘記憶體快取
    if COURTS_CACHE and (current_time - LAST_FETCH_TIME < 300):
        return COURTS_CACHE

    # 1. 嘗試從 Google Sheets CSV 讀取 (若有配置網址)
    if COURTS_SHEET_URL:
        try:
            r = requests.get(COURTS_SHEET_URL, timeout=5)
            r.encoding = "utf-8"
            reader = csv.reader(io.StringIO(r.text))
            rows = list(reader)

            if len(rows) > 1:
                header = [c.strip().lower() for c in rows[0]]

                def find_idx(keywords: List[str], default_idx: int) -> int:
                    for idx, col in enumerate(header):
                        if any(kw in col for kw in keywords):
                            return idx
                    return default_idx

                idx_county = find_idx(["縣市", "城市", "county"], 0)
                idx_dist = find_idx(["行政區", "區", "鄉鎮", "district"], 1)
                idx_name = find_idx(["球場", "名稱", "name"], 2)
                idx_hours = find_idx(["營業時間", "時間", "hours"], 3)
                idx_price = find_idx(["收費", "價格", "price"], 4)
                idx_line = find_idx(["line", "群組", "社群"], 5)
                idx_url = find_idx(["詳情", "網址", "url", "link"], 6)
                idx_addr = find_idx(["地址", "address"], 7)

                sheet_courts_data: Dict[str, dict] = {}
                for row in rows[1:]:
                    if not any(c.strip() for c in row):
                        continue
                    county_raw = row[idx_county].strip() if len(row) > idx_county else ""
                    if not county_raw:
                        continue
                    slug = _normalize_county_slug(county_raw)
                    county_display = SLUG_TO_COUNTY.get(slug, county_raw)

                    if slug not in sheet_courts_data:
                        sheet_courts_data[slug] = {
                            "name": county_display,
                            "url": f"https://ipickleball.com.tw/places/category/{slug}/",
                            "courts": []
                        }

                    court_obj = {
                        "name": row[idx_name].strip() if len(row) > idx_name else "未知球場",
                        "district": row[idx_dist].strip() if len(row) > idx_dist else "市區",
                        "hours": row[idx_hours].strip() if len(row) > idx_hours else "未提供",
                        "price": row[idx_price].strip() if len(row) > idx_price else "未提供",
                        "line_url": row[idx_line].strip() if (len(row) > idx_line and row[idx_line].strip()) else None,
                        "url": row[idx_url].strip() if len(row) > idx_url else "",
                        "address": row[idx_addr].strip() if len(row) > idx_addr else "",
                    }
                    sheet_courts_data[slug]["courts"].append(court_obj)

                if sheet_courts_data:
                    COURTS_CACHE = sheet_courts_data
                    LAST_FETCH_TIME = current_time
                    return sheet_courts_data
        except Exception as e:
            print(f"[警告] 讀取 Google Sheets 球場資料失敗: {e}", flush=True)

    # 2. 若快取存在則返回快取
    if COURTS_CACHE:
        return COURTS_CACHE

    # 3. 降級備援機制：讀取本地 JSON
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                COURTS_CACHE = data
                LAST_FETCH_TIME = current_time
                return data
        except Exception as e:
            print(f"[警告] 讀取本地球場快照失敗: {e}", flush=True)

    return {}


def scrape_courts_by_county(county_slug: str) -> Tuple[List[Dict], str]:
    """取得指定縣市的球場清單與分類網址。"""
    all_data = load_all_courts_data()
    county_data = all_data.get(county_slug, {})
    courts = county_data.get("courts", [])
    url = county_data.get("url", f"https://ipickleball.com.tw/places/category/{county_slug}/")
    return courts, url


def get_county_quick_reply() -> QuickReply:
    """產生第一段：縣市選擇 QuickReply。"""
    items = []
    display_counties = list(COUNTIES.keys())[:12]

    for county_name in display_counties:
        slug = COUNTIES[county_name]
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=county_name,
                    data=f"action=pickle_courts_pick_county&county={slug}&name={county_name}",
                    display_text=f"查詢 {county_name} 球場",
                )
            )
        )

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


def get_district_quick_reply(county_slug: str, county_name: str) -> QuickReply:
    """產生第二段：行政區選擇 QuickReply。

    重點規定：第一個項目必須是「全部」。
    接著列出該縣市各行政區（如：豐原區、北屯區...），最後一個為取消。
    """
    courts, _ = scrape_courts_by_county(county_slug)

    # 統計各行政區之球場數量
    dist_counter: Dict[str, int] = {}
    for c in courts:
        dist = c.get("district", "市區") or "市區"
        dist_counter[dist] = dist_counter.get(dist, 0) + 1

    # 依球場數量由多到少排序
    sorted_districts = sorted(dist_counter.keys(), key=lambda d: dist_counter[d], reverse=True)

    items = [
        QuickReplyItem(
            action=PostbackAction(
                label="全部",
                data=f"action=pickle_courts_district&county={county_slug}&name={county_name}&district=全部",
                display_text=f"查詢 {county_name} 全部區球場",
            )
        )
    ]

    # LINE Quick Reply 最多 13 個按鈕，扣除第 1 個「全部」與最後 1 個「取消」，最多填入 11 個區
    for dist in sorted_districts[:11]:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=dist,
                    data=f"action=pickle_courts_district&county={county_slug}&name={county_name}&district={dist}",
                    display_text=f"查詢 {county_name} {dist} 球場",
                )
            )
        )

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


def _build_compact_court_box(court: dict, index: int) -> FlexBox:
    """產生單一球場的卡片內容區塊。"""
    name = court.get("name", "未知球場") or "未知球場"
    court_url = court.get("url", "")
    hours = court.get("hours", "未提供") or "未提供"
    price = court.get("price", "未提供") or "未提供"
    line_url = court.get("line_url")
    district = court.get("district", "")

    # 若有行政區且球場名稱未提及，可標註
    title_text = f"{index}. {name}"

    name_row = FlexBox(
        layout="horizontal",
        contents=[
            FlexText(text=title_text, weight="bold", size="sm", color="#1E3A8A", wrap=True, flex=4),
        ]
    )

    detail_row = FlexBox(
        layout="vertical",
        margin="sm",
        spacing="xs",
        contents=[
            FlexBox(
                layout="horizontal",
                contents=[
                    FlexText(text="時間", size="xs", color="#6B7280", flex=1),
                    FlexText(text=hours, size="xs", color="#374151", flex=3, wrap=True),
                ]
            ),
            FlexBox(
                layout="horizontal",
                contents=[
                    FlexText(text="收費", size="xs", color="#6B7280", flex=1),
                    FlexText(text=price, size="xs", color="#374151", flex=3, wrap=True),
                ]
            )
        ]
    )

    buttons = []
    map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name)}"
    buttons.append(FlexButton(style="secondary", height="sm", action=URIAction(label="📍地圖", uri=map_url), flex=1))

    if court_url:
        buttons.append(FlexButton(style="secondary", height="sm", action=URIAction(label="🔗詳情", uri=court_url), flex=1))

    if line_url:
        buttons.append(FlexButton(style="secondary", height="sm", action=URIAction(label="💬加群", uri=line_url), flex=1))

    button_row = FlexBox(
        layout="horizontal",
        margin="md",
        spacing="sm",
        contents=buttons
    ) if buttons else None

    box_contents = [name_row, detail_row]
    if button_row:
        box_contents.append(button_row)

    return FlexBox(
        layout="vertical",
        padding_all="sm",
        contents=box_contents
    )


def _build_district_bubble(district_name: str, courts: list, county_name: str) -> FlexBubble:
    """為單一行政區建立一個 Bubble，內含該區的所有球場。"""
    body_contents = []
    for i, c in enumerate(courts[:4]):
        if i > 0:
            body_contents.append(FlexSeparator(margin="md"))
        body_contents.append(
            FlexBox(
                layout="vertical",
                margin="md" if i > 0 else "none",
                contents=[_build_compact_court_box(c, i + 1)]
            )
        )

    if len(courts) > 4:
        body_contents.append(FlexSeparator(margin="md"))
        body_contents.append(
            FlexText(
                text=f"本區共有 {len(courts)} 座球場，已列出前 4 座",
                size="xxs",
                color="#6B7280",
                align="center",
                margin="md"
            )
        )

    return FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#1E3A8A",
            padding_all="md",
            contents=[
                FlexText(
                    text=f"📍 {county_name} {district_name}",
                    weight="bold",
                    size="md",
                    color="#FFFFFF",
                ),
                FlexText(
                    text=f"共有 {len(courts)} 座球場",
                    size="xs",
                    color="#93C5FD",
                    margin="xs",
                )
            ]
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            contents=body_contents
        )
    )


def create_all_districts_courts_flex(
    courts: list,
    county_name: str,
    more_url: str,
) -> FlexMessage:
    """當使用者選擇「全部區」時呼叫。

    核心需求：卡片依「行政區」進行分組顯示，每一張 Bubble 即代表一個「區」。
    """
    if not courts:
        bubble = FlexBubble(
            body=FlexBox(
                layout="vertical",
                contents=[
                    FlexText(text=f"{county_name} 目前尚無球場資料", wrap=True, color="#6B7280", size="sm"),
                ],
            )
        )
        return FlexMessage(alt_text=f"{county_name} 目前尚無球場資料", contents=bubble)

    # 依行政區分組
    dist_map: Dict[str, list] = {}
    for c in courts:
        d = c.get("district", "市區") or "市區"
        if d not in dist_map:
            dist_map[d] = []
        dist_map[d].append(c)

    # 排序行政區：球場數多的排在前面
    sorted_districts = sorted(dist_map.keys(), key=lambda d: len(dist_map[d]), reverse=True)

    bubbles = []
    # LINE Carousel 最多 12 個 Bubble，保留 1 個給「查看更多」引導卡
    for dist in sorted_districts[:11]:
        bubbles.append(_build_district_bubble(dist, dist_map[dist], county_name))

    if len(sorted_districts) > 11 or more_url:
        more_bubble = FlexBubble(
            size="mega",
            body=FlexBox(
                layout="vertical",
                justify_content="center",
                spacing="md",
                padding_all="lg",
                contents=[
                    FlexText(
                        text=f"{county_name} 全區共 {len(courts)} 座球場",
                        size="xs",
                        color="#6B7280",
                        align="center",
                    ),
                    FlexText(
                        text="查看完整清單與地圖",
                        weight="bold",
                        size="sm",
                        color="#2563EB",
                        align="center",
                        action=URIAction(label="前往網站", uri=more_url),
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
        alt_text=f"{county_name} 各區匹克球球場列表",
        contents=FlexCarousel(contents=bubbles),
    )


def create_district_courts_flex(
    courts: list,
    county_name: str,
    district_name: str,
    more_url: str,
) -> FlexMessage:
    """當使用者選擇「特定行政區」（如豐原區）時呼叫。"""
    # 篩選特定行政區
    target_courts = [c for c in courts if c.get("district") == district_name]

    if not target_courts:
        # 若無精準匹配，嘗試模糊比對球場名稱或地址
        target_courts = [c for c in courts if district_name in c.get("name", "") or district_name in c.get("address", "")]

    if not target_courts:
        bubble = FlexBubble(
            body=FlexBox(
                layout="vertical",
                contents=[
                    FlexText(
                        text=f"{county_name} {district_name} 目前尚無球場資料",
                        wrap=True,
                        color="#6B7280",
                        size="sm",
                    ),
                    FlexText(
                        text=f"建議點選「全部」查看 {county_name} 其他區域的球場。",
                        wrap=True,
                        color="#9CA3AF",
                        size="xs",
                        margin="md",
                    )
                ],
            )
        )
        return FlexMessage(alt_text=f"{county_name} {district_name} 目前尚無球場資料", contents=bubble)

    # 每個卡片放 4 個球場
    chunk_size = 4
    bubbles = []

    for i in range(0, min(len(target_courts), 24), chunk_size):
        chunk = target_courts[i:i + chunk_size]
        body_contents = []
        for j, c in enumerate(chunk):
            if j > 0:
                body_contents.append(FlexSeparator(margin="md"))
            body_contents.append(
                FlexBox(
                    layout="vertical",
                    margin="md" if j > 0 else "none",
                    contents=[_build_compact_court_box(c, i + j + 1)]
                )
            )

        bubble = FlexBubble(
            size="mega",
            header=FlexBox(
                layout="vertical",
                background_color="#1E3A8A",
                padding_all="md",
                contents=[
                    FlexText(
                        text=f"📍 {county_name} {district_name} ({i + 1}-{i + len(chunk)})",
                        weight="bold",
                        size="md",
                        color="#FFFFFF",
                    )
                ]
            ),
            body=FlexBox(
                layout="vertical",
                padding_all="md",
                contents=body_contents
            )
        )
        bubbles.append(bubble)

    return FlexMessage(
        alt_text=f"{county_name} {district_name} 匹克球球場列表",
        contents=FlexCarousel(contents=bubbles),
    )


def create_courts_flex(
    courts: list,
    county_name: str,
    more_url: str,
    district_name: Optional[str] = None,
) -> FlexMessage:
    """相容舊版介面：若未指定 district 或指定為「全部」，採用按區分組展示。"""
    if not district_name or district_name == "全部":
        return create_all_districts_courts_flex(courts, county_name, more_url)
    return create_district_courts_flex(courts, county_name, district_name, more_url)