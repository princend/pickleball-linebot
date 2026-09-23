from linebot.v3.messaging import FlexMessage, FlexBubble, FlexBox, FlexText, FlexButton, URIAction, MessageAction

def create_welcome_flex() -> FlexMessage:
    bubble = FlexBubble(
        size="mega",
        body=FlexBox(
            layout="vertical",
            padding_all="xl",
            spacing="md",
            contents=[
                FlexText(
                    text="歡迎加入本群組！",
                    weight="bold",
                    size="lg",
                    color="#1E3A8A",
                    wrap=True
                ),
                FlexText(
                    text="為維護群組品質與了解相關規範，請新進成員務必先至「記事本」查看重要公告與置頂貼文。\n\n本群組配有專屬的匹克球機器人，可點擊下方按鈕或輸入「!指令」來呼叫選單，查看各項實用功能。",
                    size="sm",
                    color="#4B5563",
                    wrap=True,
                    margin="md"
                ),
                FlexBox(
                    layout="vertical",
                    margin="xl",
                    spacing="sm",
                    contents=[
                        FlexButton(
                            style="primary",
                            color="#F59E0B", # Amber/Orange for important
                            action=URIAction(
                                label="查看群組記事本",
                                uri="https://line.me/R/nv/note"
                            )
                        ),
                        FlexButton(
                            style="secondary",
                            action=MessageAction(
                                label="查看機器人指令",
                                text="!指令"
                            )
                        )
                    ]
                )
            ]
        )
    )
    return FlexMessage(alt_text="歡迎加入群組！", contents=bubble)


def create_group_rules_flex() -> FlexMessage:
    bubble = FlexBubble(
        size="mega",
        body=FlexBox(
            layout="vertical",
            padding_all="xl",
            spacing="md",
            contents=[
                FlexText(
                    text="【新成員入群必看守則】",
                    weight="bold",
                    size="lg",
                    color="#92400E",
                    wrap=True,
                    align="center"
                ),
                FlexText(
                    text="歡迎加入ouo匹克球揪團(非營利)！\n為維護良好的打球環境，請大家共同遵守以下規範：",
                    size="sm",
                    color="#4B5563",
                    wrap=True,
                    margin="md"
                ),
                FlexBox(
                    layout="vertical",
                    margin="lg",
                    spacing="sm",
                    contents=[
                        FlexText(text="1. 報名與請假：", weight="bold", size="sm", color="#1F2937"),
                        FlexText(text="取消請於活動「24小時前」告知揪團者；當日取消或放鳥者仍須支付費用，無故放鳥直接退群。", size="sm", color="#4B5563", wrap=True),
                        FlexText(text="2. 球場禮儀：", weight="bold", size="sm", color="#1F2937", margin="md"),
                        FlexText(text="嚴禁勝負魔人，請勿吵架或打架，大家出來運動流汗請互相體諒與包容。", size="sm", color="#4B5563", wrap=True),
                        FlexText(text="3. 群組秩序：", weight="bold", size="sm", color="#1F2937", margin="md"),
                        FlexText(text="嚴禁商業推銷，禁止未經同意私自加好友騷擾球友，違者一律踢出。", size="sm", color="#4B5563", wrap=True),
                        FlexText(text="4. 群組機器人：", weight="bold", size="sm", color="#1F2937", margin="md"),
                        FlexText(text="在群組輸入「!指令」即可查看目前支援的所有自動化功能與查詢指令。", size="sm", color="#4B5563", wrap=True),
                    ]
                ),
                FlexText(
                    text="感謝配合，祝大家打球愉快！",
                    size="sm",
                    color="#10B981",
                    weight="bold",
                    align="center",
                    wrap=True,
                    margin="xl"
                )
            ]
        )
    )
    return FlexMessage(alt_text="群組規範與守則", contents=bubble)
