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
                    text="為維護群組品質與了解相關規範，請新進成員務必先至「記事本」查看重要公告與置頂貼文。\\n\\n本群組配有專屬的匹克球機器人，可點擊下方按鈕或輸入「!指令」來呼叫選單，查看各項實用功能。",
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
                                label="查看重要貼文",
                                uri="https://linevoom.line.me/post/1179015146135834353"
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
