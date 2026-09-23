from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, FlexMessage, FlexBubble, FlexBox, FlexText, FlexButton, MessageAction
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, MemberJoinedEvent
import traceback

import config
from handlers.text_handler import handle_pickleball_command
from handlers.postback_handler import process_postback

app = Flask(__name__)

# LINE Bot 基本設定
configuration = Configuration(access_token=config.line_channel_access_token)
handler = WebhookHandler(config.line_channel_secret)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    target_id = event.source.user_id
    if hasattr(event.source, 'group_id'):
        target_id = event.source.group_id
    elif hasattr(event.source, 'room_id'):
        target_id = event.source.room_id

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        try:
            res = handle_pickleball_command(
                text=event.message.text,
                user_id=event.source.user_id,
                target_id=target_id,
                event=event,
                line_bot_api=line_bot_api
            )
            # 若無匹配指令，則不做回應
        except Exception as e:
            print(f"Text Handler Error: {e}")
            traceback.print_exc()

@handler.add(PostbackEvent)
def handle_postback(event):
    target_id = event.source.user_id
    if hasattr(event.source, 'group_id'):
        target_id = event.source.group_id
    elif hasattr(event.source, 'room_id'):
        target_id = event.source.room_id
        
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            process_postback(event, line_bot_api, target_id)
        except Exception as e:
            print(f"Postback Handler Error: {e}")
            traceback.print_exc()

@handler.add(MemberJoinedEvent)
def handle_member_joined(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        try:
            # 建立歡迎卡片 (Flex Message)
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
                            text="為維護群組品質與了解相關規範，請新進成員務必先至「記事本」查看重要公告與置頂貼文。\n\n本群組配有專屬的匹克球機器人，若需使用約戰分組、找球場、查詢近期賽事等功能，可點擊下方按鈕或輸入「!指令」來呼叫選單。",
                            size="sm",
                            color="#4B5563",
                            wrap=True,
                            margin="md"
                        ),
                        FlexButton(
                            style="primary",
                            color="#10B981",
                            margin="xl",
                            action=MessageAction(
                                label="查看機器人指令",
                                text="!指令"
                            )
                        )
                    ]
                )
            )
            
            flex_msg = FlexMessage(alt_text="歡迎加入群組！", contents=bubble)
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_msg]
                )
            )
        except Exception as e:
            print(f"MemberJoined Handler Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
