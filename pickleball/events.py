import csv
import io
import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
import requests
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexCarousel,
    FlexMessage,
    FlexSeparator,
    FlexText,
    FlexButton,
    URIAction
)

EVENTS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "events_data.json")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Zphr-a547bmb0nTTNxz8p5A1dajAmLSOi-mO1NiRydw/export?format=csv&gid=1270824619"
EVENTS_CACHE: List[dict] = []
LAST_FETCH_TIME = 0


def load_all_events() -> List[dict]:
    """從 Google Sheets 即時讀取賽事資料，具備 5 分鐘快取與本地備援機制。"""
    global EVENTS_CACHE, LAST_FETCH_TIME
    current_time = time.time()

    # 5 分鐘快取機制，避免頻繁請求造成延遲
    if EVENTS_CACHE and (current_time - LAST_FETCH_TIME < 300):
        return EVENTS_CACHE

    try:
        r = requests.get(SHEET_URL, timeout=5)
        r.encoding = "utf-8"
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)

        if len(rows) > 1:
            header = [col.strip().lower() for col in rows[0]]

            # 動態比對標題列欄位索引
            def find_idx(keywords: List[str], default_idx: int) -> int:
                for idx, col_name in enumerate(header):
                    if any(kw in col_name for kw in keywords):
                        return idx
                return default_idx

            idx_title = find_idx(["賽事", "名稱", "title"], 0)
            idx_date = find_idx(["日期", "時間", "date"], 1)
            idx_loc = find_idx(["地點", "縣市", "location"], 2)
            idx_dl = find_idx(["截止", "報名截止", "deadline"], 3)
            idx_price = find_idx(["費用", "報名費", "price"], 4)
            idx_url = find_idx(["連結", "網址", "url", "link"], 5)

            events = []
            for row in rows[1:]:
                # 跳過空白列
                if not any(c.strip() for c in row):
                    continue
                title = row[idx_title].strip() if len(row) > idx_title else ""
                if not title:
                    continue
                date_text = row[idx_date].strip() if len(row) > idx_date else "未提供日期"
                loc = row[idx_loc].strip() if len(row) > idx_loc else "未知地點"
                dl = row[idx_dl].strip() if len(row) > idx_dl else "未提供"
                price = row[idx_price].strip() if len(row) > idx_price else "請見賽事簡章"
                url = row[idx_url].strip() if len(row) > idx_url else ""

                events.append({
                    "title": title,
                    "date": date_text,
                    "location": loc,
                    "deadline": dl,
                    "price": price,
                    "url": url,
                })

            if events:
                EVENTS_CACHE = events
                LAST_FETCH_TIME = current_time
                return events
    except Exception as e:
        print(f"[警告] 讀取 Google Sheets 賽事失敗: {e}", flush=True)

    # 若抓取失敗但過去有快取，回傳快取
    if EVENTS_CACHE:
        return EVENTS_CACHE

    # 降級備援機制：讀取本地 JSON
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("events", [])
        except Exception as e:
            print(f"[警告] 讀取本地賽事快照失敗: {e}", flush=True)

    return []


def _build_compact_event_box(event: dict, index: int) -> FlexBox:
    title = event.get("title", "未知賽事")
    url = event.get("url", "")
    location = event.get("location", "未知地點")
    date_text = event.get("date", "未提供日期")
    price = event.get("price", "未提供")
    deadline = event.get("deadline", "未提供")

    name_row = FlexBox(
        layout="horizontal",
        contents=[
            FlexText(text=f"{index}. {title}", weight="bold", size="sm", color="#B45309", wrap=True, flex=4),
        ]
    )
    
    detail_row = FlexBox(
        layout="vertical",
        margin="sm",
        spacing="xs",
        contents=[
            FlexBox(layout="horizontal", contents=[
                FlexText(text="日期", size="xs", color="#6B7280", flex=2),
                FlexText(text=date_text, size="xs", color="#374151", flex=5, wrap=True)
            ]),
            FlexBox(layout="horizontal", contents=[
                FlexText(text="地點", size="xs", color="#6B7280", flex=2),
                FlexText(text=location, size="xs", color="#374151", flex=5, wrap=True)
            ]),
            FlexBox(layout="horizontal", contents=[
                FlexText(text="截止日", size="xs", color="#6B7280", flex=2),
                FlexText(text=deadline, size="xs", color="#DC2626", flex=5, wrap=True, weight="bold")
            ]),
        ]
    )

    buttons = []
    if url:
        buttons.append(FlexButton(style="primary", color="#10B981", height="sm", action=URIAction(label="🔗 賽事詳情與報名", uri=url), flex=1))
        
    button_row = None
    if buttons:
        button_row = FlexBox(
            layout="horizontal",
            margin="md",
            spacing="sm",
            contents=buttons
        )
    
    box_contents = [name_row, detail_row]
    if button_row:
        box_contents.append(button_row)
        
    return FlexBox(
        layout="vertical",
        padding_all="sm",
        contents=box_contents
    )

def _build_grouped_event_bubble(events: list, start_idx: int) -> FlexBubble:
    body_contents = []
    for i, e in enumerate(events):
        if i > 0:
            body_contents.append(FlexSeparator(margin="md"))
        body_contents.append(
            FlexBox(
                layout="vertical",
                margin="md" if i > 0 else "none",
                contents=[_build_compact_event_box(e, start_idx + i)]
            )
        )
        
    return FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#FEF3C7", # Light yellow/amber
            padding_all="md",
            contents=[
                FlexText(
                    text=f"📅 近期大型賽事 ({start_idx}-{start_idx+len(events)-1})",
                    weight="bold",
                    size="md",
                    color="#92400E",
                )
            ]
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            contents=body_contents
        )
    )

from linebot.v3.messaging import QuickReply, QuickReplyItem, MessageAction

REGION_MAP = {
    "北部": ["基隆", "台北", "臺北", "新北", "桃園", "新竹", "宜蘭", "Taipei", "Taoyuan", "Hsinchu", "New"],
    "中部": ["苗栗", "台中", "臺中", "彰化", "南投", "雲林", "Taichung", "Miaoli", "Changhua", "Nantou", "Yunlin"],
    "南部": ["嘉義", "台南", "臺南", "高雄", "屏東", "Tainan", "Kaohsiung", "Chiayi", "Pingtung"],
    "東部": ["花蓮", "台東", "臺東", "Hualien", "Taitung"],
    "全部": []
}

def get_event_region_quick_reply() -> QuickReply:
    items = []
    for region in ["全部", "北部", "中部", "南部", "東部"]:
        items.append(
            QuickReplyItem(
                action=MessageAction(label=region, text=f"!賽事 {region}")
            )
        )
    items.append(
        QuickReplyItem(
            action=MessageAction(label="❌ 取消", text="!取消")
        )
    )
    return QuickReply(items=items)

def create_events_flex(region: str = "全部", quick_reply: QuickReply = None) -> FlexMessage:
    all_events = load_all_events()
    if not all_events:
        return FlexMessage(
            alt_text="目前尚無賽事資料",
            contents=FlexBubble(body=FlexBox(layout="vertical", contents=[FlexText(text="目前尚無賽事資料")])),
            quick_reply=quick_reply
        )

    
    # 取得今天的日期字串 (YYYY-MM-DD) 以過濾過期賽事
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 過濾與解析日期，準備排序
    valid_events = []
    for e in all_events:
        date_text = e.get("date", "")
        # 嘗試從 date_text 萃取 YYYY-MM-DD
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", date_text)
        
        if not dates:
            # 如果沒有明確日期，看要不要保留。這裡保留並將排序用日期設為最大值放到最後
            e["_sort_date"] = "9999-99-99"
            valid_events.append(e)
            continue
            
        start_date = dates[0]
        end_date = dates[-1] # 如果有兩個日期，取最後一個當作結束日
        
        # 已經比完的賽事 (結束日小於今天) 不顯示
        if end_date < today_str:
            continue
            
        e["_sort_date"] = start_date
        valid_events.append(e)
        
    # 根據日期排序 (最接近的放第一個)
    valid_events.sort(key=lambda x: x["_sort_date"])
    
    events = []
    if region == "全部":
        events = valid_events
    else:
        allowed_counties = REGION_MAP.get(region, [])
        for e in valid_events:
            loc = e.get("location", "")
            if any(c in loc for c in allowed_counties):
                events.append(e)
    
    if not events:
        return FlexMessage(
            alt_text=f"目前尚無 {region} 的賽事資料",
            contents=FlexBubble(body=FlexBox(layout="vertical", contents=[FlexText(text=f"目前尚無 {region} 的賽事資料")])),
            quick_reply=quick_reply
        )
        
    chunk_size = 4
    bubbles = []
    
    for i in range(0, min(len(events), 24), chunk_size):
        chunk = events[i:i+chunk_size]
        bubbles.append(_build_grouped_event_bubble(chunk, i + 1))
        
    if len(events) > 24:
        more_bubble = FlexBubble(
            size="mega",
            body=FlexBox(
                layout="vertical",
                justify_content="center",
                spacing="md",
                padding_all="lg",
                contents=[
                    FlexText(text=f"顯示前 24 筆", size="xs", color="#6B7280", align="center"),
                    FlexText(text="查看更多賽事", weight="bold", size="sm", color="#2563EB", align="center", action=URIAction(label="前往網站", uri="https://ipickleball.com.tw/events/"))
                ]
            )
        )
        bubbles.append(more_bubble)

    title_text = f"📅 近期匹克球賽事 ({region})" if region != "全部" else "📅 近期匹克球賽事清單"
    return FlexMessage(
        alt_text=title_text,
        contents=FlexCarousel(contents=bubbles),
        quick_reply=quick_reply
    )
