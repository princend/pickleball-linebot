"""匹克球 (Pickleball) 規則說明模組。

提供匹克球新手實戰規則之高質感 LINE Flex Message 雙卡片橫向輪播排版。
精簡條理化六大核心主題：發球規範、站位換邊、計分與 Deuce、兩次彈跳、廚房區非截擊、壓線與犯規判定。
所有標題與內文均啟用 wrap=True 完整顯示，杜絕任何刪節號截斷。
遵循 No Emoji Policy (嚴禁任何表情符號) 與全繁體中文規範。
"""

from typing import Any, List
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexCarousel,
    FlexMessage,
    FlexText,
    URIAction,
)


def _build_rule_section(
    title: str,
    title_color: str,
    bg_color: str,
    items: List[str],
) -> FlexBox:
    """建構單一規則區塊卡片色塊。"""
    contents: List[Any] = [
        FlexText(
            text=title,
            weight="bold",
            size="md",
            color=title_color,
            wrap=True,
        )
    ]

    for item in items:
        contents.append(
            FlexText(
                text=f"- {item}",
                size="sm",
                color="#374151",
                wrap=True,
                margin="sm",
            )
        )

    return FlexBox(
        layout="vertical",
        background_color=bg_color,
        corner_radius="md",
        padding_all="md",
        spacing="xs",
        contents=contents,
    )


def create_pickleball_rules_flex() -> FlexMessage:
    """產生匹克球新手實戰規則指引之精簡高質感雙卡片 Flex Carousel 輪播訊息。"""
    # -------------------------------------------------------------
    # 卡片一：發球規範、站位輪替與計分 Deuce (1/2)
    # -------------------------------------------------------------
    card_1_sections: List[Any] = []

    # 1. 發球規範 (清新藍底)
    card_1_sections.append(
        _build_rule_section(
            title="1. 發球規範 (Serve)",
            title_color="#2563EB",
            bg_color="#EFF6FF",
            items=[
                "凌空發球：由下而上揮拍，擊球點與拍面須低於腰部手腕。",
                "墜地發球：鬆手落地彈跳後擊球，不受腰部手腕高度限制。",
                "站位界外：擊球瞬間雙腳須在底線外，嚴禁踩線或踩入場內。",
                "發球落點：須發往斜對角發球區，且必須越過廚房區線。",
            ],
        )
    )

    # 2. 站位與換邊 (青綠底)
    card_1_sections.append(
        _build_rule_section(
            title="2. 站位與換邊 (Rotation)",
            title_color="#0D9488",
            bg_color="#F0FDFA",
            items=[
                "右側起發：取得發球權時，第一發球員一律從己方右側發球。",
                "得分換邊：僅發球方得分才左右換位，並由原發球員續發。",
                "接發不換位：接發方不可換位；若非對角球員代接直接失分。",
            ],
        )
    )

    # 3. 計分與 Deuce (淺紫底)
    card_1_sections.append(
        _build_rule_section(
            title="3. 計分與 Deuce (Scoring)",
            title_color="#7E22CE",
            bg_color="#FAF5FF",
            items=[
                "發球得分制：僅發球方能得分，通常打 11 分制。",
                "報分三位數：我方分 - 對方分 - 第幾發球員 (例 4-3-1)。",
                "平分延長 (Deuce)：10-10 平手後須淨勝 2 分才獲勝 (如 12-10)。",
                "首局首發例外 (0-0-2)：開局先發隊伍僅 1 次失誤機會，失誤即換邊 (Side-out)。",
            ],
        )
    )

    bubble_1 = FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#CCFF00",
            padding_all="md",
            contents=[
                FlexText(
                    text="匹克球新手實戰指引 (1/2)",
                    weight="bold",
                    size="xl",
                    color="#1F2937",
                    wrap=True,
                ),
                FlexText(
                    text="發球規範、站位輪替與計分 Deuce 手冊",
                    size="sm",
                    color="#4B5563",
                    margin="xs",
                    wrap=True,
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="md",
            contents=card_1_sections,
        ),
        footer=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=[
                FlexButton(
                    action=URIAction(
                        label="中華民國匹克球總會 (中文規則)",
                        uri="https://www.ctpf.org.tw",
                    ),
                    style="primary",
                    color="#0D9488",
                    height="sm",
                ),
                FlexButton(
                    action=URIAction(
                        label="國際官方規則 (USA Pickleball)",
                        uri="https://usapickleball.org/rules/",
                    ),
                    style="secondary",
                    height="sm",
                ),
            ],
        ),
    )

    # -------------------------------------------------------------
    # 卡片二：對打節奏、非截擊廚房區與犯規判定 (2/2)
    # -------------------------------------------------------------
    card_2_sections: List[Any] = []

    # 1. 兩次彈跳 (清新綠底)
    card_2_sections.append(
        _build_rule_section(
            title="1. 兩次彈跳 (Two-Bounce)",
            title_color="#16A34A",
            bg_color="#F0FDF4",
            items=[
                "兩次彈跳：接發球須落地、回擊後發球方也須落地才能打。",
                "自由截擊：雙方各落地打一次後，第三拍起可凌空截擊。",
                "非故意連擊合法：同一次連續揮拍動作中觸球兩次不犯規。",
            ],
        )
    )

    # 2. 廚房區非截擊 (暖橘底)
    card_2_sections.append(
        _build_rule_section(
            title="2. 廚房區非截擊 (Kitchen)",
            title_color="#EA580C",
            bg_color="#FFF7ED",
            items=[
                "禁凌空截擊：球未落地前，嚴禁踩線或踏入廚房區截擊 (含慣性踩線)。",
                "落地可進出：球在廚房區內彈跳落地後，可自由進出擊球。",
            ],
        )
    )

    # 3. 壓線與犯規判定 (淺灰底)
    card_2_sections.append(
        _build_rule_section(
            title="3. 壓線與犯規判定 (Faults)",
            title_color="#4B5563",
            bg_color="#F3F4F6",
            items=[
                "壓線皆界內：除發球壓廚房線算犯規出界外，其餘壓線皆界內 (In)。",
                "發球擦網無 Let：發球擦網只要落入發球區即為活球，不重發。",
                "觸網即犯規：活球中身體、衣物或球拍碰網即判失分。",
                "發球踩線犯規：發球瞬間踩底線或踩入場內皆算犯規。",
            ],
        )
    )

    bubble_2 = FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#CCFF00",
            padding_all="md",
            contents=[
                FlexText(
                    text="匹克球新手實戰指引 (2/2)",
                    weight="bold",
                    size="xl",
                    color="#1F2937",
                    wrap=True,
                ),
                FlexText(
                    text="兩次彈跳、非截擊廚房區與犯規判定手冊",
                    size="sm",
                    color="#4B5563",
                    margin="xs",
                    wrap=True,
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="md",
            contents=card_2_sections,
        ),
        footer=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=[
                FlexButton(
                    action=URIAction(
                        label="觀看新手教學影片 (YouTube)",
                        uri="https://www.youtube.com/results?search_query=pickleball+tutorial+rules",
                    ),
                    style="primary",
                    color="#DC2626",
                    height="sm",
                )
            ],
        ),
    )

    carousel = FlexCarousel(contents=[bubble_1, bubble_2])

    return FlexMessage(
        alt_text="匹克球新手實戰規則指引手冊",
        contents=carousel,
    )
