import json
import os
from typing import List
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

def create_events_flex() -> FlexMessage:
    if not os.path.exists(EVENTS_FILE):
        return FlexMessage(
            alt_text="目前尚無賽事資料",
            contents=FlexBubble(body=FlexBox(layout="vertical", contents=[FlexText(text="目前尚無賽事資料")]))
        )
        
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    events = data.get("events", [])
    
    if not events:
        return FlexMessage(
            alt_text="目前尚無賽事資料",
            contents=FlexBubble(body=FlexBox(layout="vertical", contents=[FlexText(text="目前尚無賽事資料")]))
        )
        
    chunk_size = 4
    bubbles = []
    
    # max 11 bubbles = 44 events
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
                    FlexText(text=f"顯示前 {min(len(events), 24)} 筆", size="xs", color="#6B7280", align="center"),
                    FlexText(text="查看更多賽事", weight="bold", size="sm", color="#2563EB", align="center", action=URIAction(label="前往網站", uri="https://ipickleball.com.tw/events/"))
                ]
            )
        )
        bubbles.append(more_bubble)

    return FlexMessage(
        alt_text="📅 近期匹克球賽事清單",
        contents=FlexCarousel(contents=bubbles)
    )
