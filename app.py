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
            from pickleball import create_welcome_flex
            flex_msg = create_welcome_flex()
            
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
