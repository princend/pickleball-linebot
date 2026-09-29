"""匹克球主流球拍推薦模組。

提供兩步速配問卷 (預算區間 -> 球風取向)、條件過濾篩選、
以及包含球拍高畫質圖片的 LINE Flex 輪播卡片 (Carousel)。
遵循無表情符號規範 (No Emoji Policy) 與優雅排版風格。
"""

import json
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexCarousel,
    FlexImage,
    FlexMessage,
    FlexSeparator,
    FlexText,
    MessageAction,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    URIAction,
)

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

BUDGET_MAP = {
    "budget": {"name": "平價入門", "desc": "NT$ 1,500 以下", "color": "#10B981"},
    "intermediate": {"name": "實惠進階", "desc": "NT$ 1,500 ~ 3,500", "color": "#3B82F6"},
    "advanced": {"name": "競技中高階", "desc": "NT$ 3,500 ~ 6,500", "color": "#8B5CF6"},
    "flagship": {"name": "頂級旗艦", "desc": "NT$ 6,500 以上", "color": "#EF4444"},
}

STYLE_MAP = {
    "control": {"name": "控球防守", "desc": "重視手感與廚房區 Dink", "badge": "控球防守型"},
    "power": {"name": "力量攻擊", "desc": "重視底線重抽與殺球速度", "badge": "力量攻擊型"},
    "spin": {"name": "旋轉均衡", "desc": "重視生碳纖維咬球與全能", "badge": "旋轉均衡型"},
}


def load_all_paddles() -> List[Dict[str, Any]]:
    """讀取本地主流球拍資料。"""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[錯誤] 讀取球拍資料庫失敗: {e}", flush=True)
        return []


def get_paddle_budget_quick_reply() -> QuickReply:
    """產生步驟 1：選擇預算區間 Quick Reply。"""
    items = []
    for key, info in BUDGET_MAP.items():
        label = f"{info['name']}"
        postback_data = f"action=paddle_action&sub=select_budget&budget={key}"
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=label[:20],
                    data=postback_data,
                    display_text=f"選擇預算：{info['name']} ({info['desc']})",
                )
            )
        )

    # 取消按鈕
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="取消",
                data="action=paddle_action&sub=cancel",
                display_text="取消球拍推薦",
            )
        )
    )
    return QuickReply(items=items)


def get_paddle_style_quick_reply(budget_key: str) -> QuickReply:
    """產生步驟 2：選擇打法球風 Quick Reply。"""
    items = []
    for key, info in STYLE_MAP.items():
        label = f"{info['name']}"
        postback_data = f"action=paddle_action&sub=select_style&budget={budget_key}&style={key}"
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=label[:20],
                    data=postback_data,
                    display_text=f"選擇球風：{info['name']} ({info['desc']})",
                )
            )
        )

    # 上一步 / 取消按鈕
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="重選預算",
                data="action=paddle_action&sub=restart",
                display_text="重選預算",
            )
        )
    )
    return QuickReply(items=items)


def filter_paddles(budget_key: str, style_key: str) -> List[Dict[str, Any]]:
    """依據預算與風格篩選球拍，具備容錯回退機制。"""
    all_paddles = load_all_paddles()
    if not all_paddles:
        return []

    # 1. 完美符合
    matched = [
        p for p in all_paddles
        if p.get("budget_category") == budget_key and p.get("style_category") == style_key
    ]

    # 使用者要求：絕對不要 fallback，沒有就是沒有
    # (原本的 fallback 邏輯已移除，確保只推薦100%符合條件的球拍)

    # 4. 隨機回傳最多 3 款代表拍 (使用戶每次查詢有不同結果)
    import random
    if matched:
        return random.sample(matched, min(3, len(matched)))
    return random.sample(all_paddles, min(3, len(all_paddles)))


def create_paddle_card(paddle: Dict[str, Any], budget_key: str, style_key: str) -> FlexBubble:
    """建立單一球拍的 FlexBubble，特別強調球拍視覺展示。"""
    name = paddle.get("name", "精選匹克球拍")
    brand = paddle.get("brand", "精選品牌")
    price = paddle.get("price_ntd", 0)
    price_formatted = f"NT$ {price:,}"
    thickness = paddle.get("thickness", "標準厚度")
    weight = paddle.get("weight", "標準重量")
    shape = paddle.get("shape", "標準型")
    surface = paddle.get("surface", "碳纖維")
    tags = paddle.get("tags", [])
    features = paddle.get("features", [])
    front_img = paddle.get("image_front", "")
    description = paddle.get("description", "")

    # 標籤色 (優先使用球拍主題色，否則使用預算對應顏色)
    budget_color = paddle.get("theme_color") or BUDGET_MAP.get(budget_key, {}).get("color", "#2563EB")

    # 單一圖片預覽區
    preview_box = FlexBox(
        layout="vertical",
        background_color="#F3F4F6",
        padding_all="md",
        contents=[
            FlexBox(
                layout="vertical",
                background_color="#FFFFFF",
                corner_radius="md",
                padding_all="xs",
                contents=[
                    FlexImage(
                        url=front_img,
                        size="full",
                        aspect_ratio="1:1",
                        aspect_mode="cover",
                    )
                ],
            )
        ],
    )

    # 標籤列
    tag_boxes = []
    for tag in tags[:3]:
        tag_boxes.append(
            FlexBox(
                layout="vertical",
                background_color="#E0E7FF",
                corner_radius="sm",
                padding_start="sm",
                padding_end="sm",
                padding_top="none",
                padding_bottom="none",
                contents=[
                    FlexText(text=f"#{tag}", size="xxs", color="#3730A3", weight="bold")
                ],
            )
        )

    # 特色說明列
    feature_boxes = []
    for feat in features[:2]:
        feature_boxes.append(
            FlexBox(
                layout="horizontal",
                spacing="xs",
                contents=[
                    FlexText(text="•", size="xs", color="#4B5563", flex=0),
                    FlexText(text=feat, size="xs", color="#4B5563", wrap=True, flex=1),
                ],
            )
        )

    search_query = f"{brand} {name} 匹克球拍"
    google_search_url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"

    bubble = FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color=budget_color,
            padding_all="md",
            contents=[
                FlexBox(
                    layout="horizontal",
                    contents=[
                        FlexText(
                            text=brand.upper(),
                            size="xs",
                            color="#FFFFFF",
                            weight="bold",
                            flex=1,
                        ),
                        FlexText(
                            text=price_formatted,
                            size="sm",
                            color="#FFFFFF",
                            weight="bold",
                            align="end",
                            flex=1,
                        ),
                    ],
                ),
                FlexText(
                    text=name,
                    size="md",
                    color="#FFFFFF",
                    weight="bold",
                    wrap=True,
                    margin="sm",
                ),
            ],
        ),
        hero=preview_box,
        body=FlexBox(
            layout="vertical",
            padding_all="lg",
            spacing="sm",
            contents=[
                # 標籤清單
                FlexBox(
                    layout="horizontal",
                    spacing="xs",
                    contents=tag_boxes,
                ),
                FlexSeparator(margin="md"),
                # 規格列表
                FlexBox(
                    layout="vertical",
                    margin="sm",
                    spacing="xs",
                    contents=[
                        FlexBox(
                            layout="horizontal",
                            contents=[
                                FlexText(text="拍身厚度", size="xs", color="#6B7280", flex=2),
                                FlexText(text=thickness, size="xs", color="#111827", weight="bold", flex=4),
                            ],
                        ),
                        FlexBox(
                            layout="horizontal",
                            contents=[
                                FlexText(text="拍身重量", size="xs", color="#6B7280", flex=2),
                                FlexText(text=weight, size="xs", color="#111827", weight="bold", flex=4),
                            ],
                        ),
                        FlexBox(
                            layout="horizontal",
                            contents=[
                                FlexText(text="拍型外觀", size="xs", color="#6B7280", flex=2),
                                FlexText(text=shape, size="xs", color="#111827", weight="bold", flex=4),
                            ],
                        ),
                        FlexBox(
                            layout="horizontal",
                            contents=[
                                FlexText(text="拍面材質", size="xs", color="#6B7280", flex=2),
                                FlexText(text=surface, size="xs", color="#111827", weight="bold", flex=4),
                            ],
                        ),
                    ],
                ),
                FlexSeparator(margin="md"),
                # 核心亮點特色
                FlexBox(
                    layout="vertical",
                    margin="sm",
                    spacing="xs",
                    contents=feature_boxes,
                ),
            ],
        ),
        footer=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=[
                FlexButton(
                    style="primary",
                    color=budget_color,
                    height="sm",
                    action=MessageAction(
                        label="AI 深入解析這款",
                        text=f"!ai 請分析 {name} 的優缺點",
                    ),
                ),
                FlexButton(
                    style="secondary",
                    height="sm",
                    action=URIAction(
                        label="線上比價與通路搜尋",
                        uri=google_search_url,
                    ),
                ),
            ],
        ),
    )
    return bubble


def create_paddle_recommendation_flex(
    budget_key: str,
    style_key: str,
    quick_reply: Optional[QuickReply] = None,
) -> Any:
    """產生球拍推薦的 Flex Carousel 輪播訊息。"""
    paddles = filter_paddles(budget_key, style_key)
    bubbles = [create_paddle_card(p, budget_key, style_key) for p in paddles]

    if not bubbles:
        from linebot.v3.messaging import TextMessage
        return TextMessage(
            text=f"目前在「{budget_info['name']}」且主打「{style_info['name']}」的分類中，還沒有找到符合的球拍喔！\n您可以試著調整預算或球風，探索更多球拍！",
            quick_reply=quick_reply
        )

    budget_info = BUDGET_MAP.get(budget_key, {"name": "自選預算"})
    style_info = STYLE_MAP.get(style_key, {"name": "自選球風"})

    alt_text = f"匹克球球拍推薦：{budget_info['name']} / {style_info['name']}"
    carousel = FlexCarousel(contents=bubbles)

    return FlexMessage(
        alt_text=alt_text,
        contents=carousel,
        quick_reply=quick_reply,
    )
