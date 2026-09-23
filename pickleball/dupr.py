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

    # 測驗按鈕卡片
    test_bubble = FlexBubble(
        size="kilo",
        body=FlexBox(
            layout="vertical",
            justify_content="center",
            align_items="center",
            padding_all="xl",
            contents=[
                FlexText(text="不知道自己是幾級嗎？", weight="bold", size="md", color="#1F2937", align="center", wrap=True),
                FlexText(text="透過 4 個小問題，", size="sm", color="#6B7280", align="center", margin="sm", wrap=True),
                FlexText(text="快速測出你的實力落點！", size="sm", color="#6B7280", align="center", wrap=True),
                FlexButton(
                    style="primary",
                    color="#10B981",
                    margin="xl",
                    action=PostbackAction(
                        label="🎯 開始測驗",
                        data="action=dupr_quiz&q=1&score=0",
                        display_text="開始實力測驗"
                    )
                )
            ]
        )
    )
    bubbles.append(test_bubble)

    return FlexMessage(
        alt_text="匹克球 DUPR 實力分級介紹",
        contents=FlexCarousel(contents=bubbles)
    )

QUESTIONS = [
    {
        "q": "1. 發球與接發球 (Serve & Return)",
        "opts": [
            ("偶爾會失誤出界或掛網", 1),
            ("穩定過網，但缺乏深度與變化", 2),
            ("發球深遠，接發能穩定打到後場", 3),
            ("能根據對手弱點改變落點與旋轉", 4)
        ]
    },
    {
        "q": "2. 第三拍過渡球 (Third Shot Drop)",
        "opts": [
            ("不懂過渡球，我都直接大力抽", 1),
            ("知道要打，但常常掛網或太高", 2),
            ("能穩定將球控制在對手廚房內", 3),
            ("在任何位置面對強球也能穩定 Drop", 4)
        ]
    },
    {
        "q": "3. 網前小球對搓 (Dinking)",
        "opts": [
            ("搓兩下就沒耐心，想要大力打", 1),
            ("可連續搓幾拍，但不太會移動對手", 2),
            ("穩定對搓，能利用小球製造對手失誤", 3),
            ("極度穩定，精準利用旋轉主導節奏", 4)
        ]
    },
    {
        "q": "4. 雙打觀念與防守 (Strategy)",
        "opts": [
            ("努力把球打過就好，沒想太多", 1),
            ("知道要上網，但常跟搭檔撞在一起", 2),
            ("能與搭檔連動，遇到抽球能擋回(Reset)", 3),
            ("完美走位，戰術多變，隨時調整策略", 4)
        ]
    }
]

def get_dupr_quiz_reply(q_idx: int, current_score: int):
    """處理測驗問題與 QuickReply"""
    if q_idx > len(QUESTIONS):
        # 測驗結束，計算結果
        return get_dupr_result(current_score)
        
    q_data = QUESTIONS[q_idx - 1]
    items = []
    
    # LINE Quick Reply label 上限 20 字，所以選項要精簡
    for opt_text, opt_score in q_data["opts"]:
        short_label = opt_text[:20]
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=short_label,
                    data=f"action=dupr_quiz&q={q_idx+1}&score={current_score + opt_score}",
                    display_text=opt_text
                )
            )
        )
        
    return TextMessage(
        text=f"【匹克球實力測驗 {q_idx}/{len(QUESTIONS)}】\n\n{q_data['q']}\n請憑直覺選擇最符合你的描述：",
        quick_reply=QuickReply(items=items)
    )

def get_dupr_result(score: int) -> FlexMessage:
    """根據分數回傳測驗結果 Flex 卡片"""
    if score <= 6:
        level = "2.0 ~ 2.5"
        title = "新手入門 (Beginner)"
        desc = "你剛接觸匹克球，正在熟悉規則與擊球感。繼續保持熱情，多上場打球，很快就能掌握手感！"
        color = "#10B981"
    elif score <= 9:
        level = "3.0"
        title = "初階球員 (Adv. Beginner)"
        desc = "你已經能穩定對打，是球場上的中堅份子！接下來可以多練習「網前小球(Dink)」與「過渡球(Drop)」，減少失誤。"
        color = "#3B82F6"
    elif score <= 13:
        level = "3.5"
        title = "中階球員 (Intermediate)"
        desc = "你的基本功已經相當扎實，懂得控制節奏與網前戰術。嘗試提升反手拍的穩定度與落點精準度，向高手邁進！"
        color = "#8B5CF6"
    else:
        level = "4.0+"
        title = "高階球員 (Advanced)"
        desc = "你是球場上的高手！具備極高的穩定度與戰術意識。不管面對強攻還是小球，你都能游刃有餘地化解並反擊。"
        color = "#F59E0B"
        
    bubble = FlexBubble(
        size="kilo",
        header=FlexBox(
            layout="vertical",
            background_color=color,
            padding_all="xl",
            contents=[
                FlexText(text="你的測驗結果", color="#FFFFFF", size="sm", weight="bold", align="center", margin="sm"),
                FlexText(text=level, color="#FFFFFF", weight="bold", size="3xl", align="center", margin="md"),
                FlexText(text=title, color="#FFFFFF", size="md", align="center", margin="sm")
            ]
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="lg",
            contents=[
                FlexText(text=desc, size="sm", color="#4B5563", wrap=True, margin="md")
            ]
        )
    )
    return FlexMessage(alt_text=f"你的匹克球實力落在 {level} ({title})", contents=bubble)
