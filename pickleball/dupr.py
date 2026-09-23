from linebot.v3.messaging import (
    FlexMessage,
    FlexCarousel,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexButton,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
    TextMessage,
    URIAction,
    FlexImage,
)

def create_pickleball_dupr_flex() -> FlexMessage:
    """產生匹克球 DUPR 分級說明的 Flex Carousel"""
    levels = [
        {
            "level": "2.0 ~ 2.5",
            "title": "新手入門 (Beginner)",
            "color": "#10B981", # Green
            "desc": [
                "• 剛接觸匹克球，了解基本規則與計分",
                "• 能夠把球打過網，但缺乏方向與力道控制",
                "• 大多留在底線，不習慣主動上網",
                "• 常常發球失誤或接發球出界"
            ]
        },
        {
            "level": "3.0",
            "title": "初階球員 (Adv. Beginner)",
            "color": "#3B82F6", # Blue
            "desc": [
                "• 能穩定發球與接發球，節奏中等",
                "• 開始知道「網前小球(Dink)」與「過渡球(Drop)」的概念，但成功率不高",
                "• 正手拍比反手拍穩定許多",
                "• 會主動上網，但容易被對手的高遠球(Lob)或快球打穿"
            ]
        },
        {
            "level": "3.5",
            "title": "中階球員 (Intermediate)",
            "color": "#8B5CF6", # Purple
            "desc": [
                "• 具備穩定的發球、接發球與底線抽球",
                "• 能連續進行網前小球(Dink)對打",
                "• 懂得使用第三拍過渡球(Drop)來爭取上網",
                "• 雙打時能與搭檔一起移動，不會輕易漏球"
            ]
        },
        {
            "level": "4.0",
            "title": "高階球員 (Advanced)",
            "color": "#F59E0B", # Orange
            "desc": [
                "• 各項技術都非常穩定，失誤率極低",
                "• 能夠利用旋轉、落點與速度來壓制對手",
                "• 遇到對手的強力抽球，能穩定擋回(Reset)到廚房內",
                "• 有清晰的比賽策略，能找出對手弱點並攻擊"
            ]
        },
        {
            "level": "4.5 ~ 5.0+",
            "title": "專家/職業 (Expert/Pro)",
            "color": "#EF4444", # Red
            "desc": [
                "• 擁有極高的預判能力與反應速度",
                "• 能夠在任何位置打出具破壞力的球",
                "• 完美掌握比賽節奏，戰術執行力極高",
                "• 經常參與正規比賽並獲得佳績"
            ]
        }
    ]

    bubbles = []
    for lvl in levels:
        desc_boxes = [
            FlexBox(
                layout="horizontal",
                margin="sm",
                contents=[
                    FlexText(text=text, size="sm", color="#4B5563", wrap=True)
                ]
            )
            for text in lvl["desc"]
        ]
        
        bubble = FlexBubble(
            size="kilo",
            header=FlexBox(
                layout="vertical",
                background_color=lvl["color"],
                padding_all="lg",
                contents=[
                    FlexText(text=lvl["level"], color="#FFFFFF", weight="bold", size="xl", align="center"),
                    FlexText(text=lvl["title"], color="#FFFFFF", size="xs", align="center", margin="md")
                ]
            ),
            body=FlexBox(
                layout="vertical",
                spacing="sm",
                padding_all="lg",
                contents=desc_boxes
            )
        )
        bubbles.append(bubble)

    info_bubble = FlexBubble(
        size="kilo",
        body=FlexBox(
            layout="vertical",
            justify_content="center",
            align_items="center",
            padding_all="xl",
            contents=[
                FlexText(text="想獲得正式的匹克球積分？", weight="bold", size="md", color="#1F2937", align="center", wrap=True),
                FlexText(text="DUPR 是全球最權威、也是", size="sm", color="#6B7280", align="center", margin="sm", wrap=True),
                FlexText(text="美國職業聯賽官方指定的系統", size="sm", color="#6B7280", align="center", wrap=True),
                FlexButton(
                    style="primary",
                    color="#1E3A8A",
                    margin="xl",
                    action=URIAction(
                        label="🔗 前往 DUPR 官網",
                        uri="https://mydupr.com"
                    )
                )
            ]
        )
    )
    bubbles.append(info_bubble)

    return FlexMessage(
        alt_text="匹克球 DUPR 實力分級介紹",
        contents=FlexCarousel(contents=bubbles)
    )