import urllib.parse
from linebot.v3.messaging import ReplyMessageRequest, TextMessage, MessageAction, QuickReply, QuickReplyItem, PostbackAction
from pickleball import (
    STEP_COURTS,
    STEP_DATE,
    STEP_LEVEL,
    STEP_LOCATION,
    STEP_PLAYERS,
    STEP_TIME,
    STEP_TITLE,
    clear_awaiting_pickleball_input,
    clear_group_creation_session,
    convert_relative_date,
    create_pickleball_group_flex,
    create_pickleball_highlight_flex,
    create_pickleball_rules_flex,
    format_group_result,
    format_time_input,
    get_group_creation_session,
    get_pickleball_cancel_quick_reply,
    get_pickleball_highlight_video,
    get_pickleball_quick_reply,
    get_pickleball_session,
    get_remove_player_quick_reply,
    get_step_prompt_and_quick_reply,
    random_group,
    remove_player_and_promote,
    save_pickleball_session,
    set_awaiting_pickleball_input,
    set_group_creation_session,
    create_courts_flex,
    scrape_courts_by_county,
)

def process_postback(event, line_bot_api, target_id):
    """處理匹克球相關的 Postback 事件"""
    data = getattr(getattr(event, "postback", None), "data", "")
    if not data:
        return "OK", 200

        parsed_data = urllib.parse.parse_qs(data)
        q_idx = int(parsed_data.get("q", ["1"])[0])
        current_score = int(parsed_data.get("score", ["0"])[0])
        
        reply_msg = get_dupr_quiz_reply(q_idx, current_score)
        
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[reply_msg],
            )
        )
        return "OK", 200

    if data.startswith("action=pickle_courts"):
        parsed_data = urllib.parse.parse_qs(data)
        county_slug = parsed_data.get("county", [""])[0]
        county_name = parsed_data.get("name", ["未知縣市"])[0]
        county_name = urllib.parse.unquote(county_name)

        if county_slug:
            courts, more_url = scrape_courts_by_county(county_slug)
            flex_msg = create_courts_flex(courts, county_name, more_url)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_msg],
                )
            )
        return "OK", 200

    elif data.startswith("action=pickle_action"):
        parsed_data = urllib.parse.parse_qs(data)
        sub = parsed_data.get("sub", ["reshuffle"])[0]
        
        # 開團精靈
        if sub == "create_group":
            clear_group_creation_session(target_id)
            session = {"step": STEP_TITLE, "data": {}}
            set_group_creation_session(target_id, session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_TITLE, {})
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        # 日期選擇
        if sub == "pick_date":
            params = getattr(getattr(event, "postback", None), "params", {}) or {}
            selected_date = params.get("date", "")
            converted_date = convert_relative_date(selected_date)
            creation_session = get_group_creation_session(target_id)
            if not creation_session:
                creation_session = {"step": STEP_TIME, "data": {}}
            collected = creation_session.get("data", {})
            collected["date"] = converted_date
            creation_session["step"] = STEP_TIME
            creation_session["data"] = collected
            set_group_creation_session(target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_TIME, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        # 時間選擇
        if sub == "pick_time":
            params = getattr(getattr(event, "postback", None), "params", {}) or {}
            selected_time = params.get("time", "")
            formatted_time = format_time_input(selected_time)
            creation_session = get_group_creation_session(target_id)
            if not creation_session:
                creation_session = {"step": STEP_LOCATION, "data": {}}
            collected = creation_session.get("data", {})
            collected["time"] = formatted_time
            creation_session["step"] = STEP_LOCATION
            creation_session["data"] = collected
            set_group_creation_session(target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_LOCATION, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        # 選擇地點的縣市 (開團精靈)
        if sub == "pick_county_for_location":
            county_slug = parsed_data.get("county", [""])[0]
            county_name = parsed_data.get("name", [""])[0]
            county_name = urllib.parse.unquote(county_name)
            
            if county_slug:
                courts, _ = scrape_courts_by_county(county_slug)
                
                if not courts:
                    # 如果該縣市沒球場，提示手動輸入
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=f"找不到 {county_name} 的球場資料，請直接手動輸入打球地點：")],
                        )
                    )
                    return "OK", 200
                
                # 最多取 12 個球場 (留一個給取消)
                display_courts = courts[:12]
                items = []
                for c in display_courts:
                    # 避免字數過長，LINE quick reply label 最多 20 字
                    c_name = c["name"][:20]
                    items.append(
                        QuickReplyItem(
                            action=MessageAction(label=c_name, text=c_name)
                        )
                    )
                
                items.append(
                    QuickReplyItem(
                        action=PostbackAction(
                            label="取消開團",
                            data="action=pickle_action&sub=cancel_create_group",
                            display_text="取消開團",
                        )
                    )
                )
                
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(
                            text=f"找到以下 {county_name} 的球場，請點擊選擇（或直接手動輸入地點）：",
                            quick_reply=QuickReply(items=items)
                        )],
                    )
                )
            return "OK", 200

        # 取消開團
        if sub == "cancel_create_group":
            clear_group_creation_session(target_id)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="已取消開團操作。")],
                )
            )
            return "OK", 200

        # 引導輸入名單
        if sub == "prompt_input":
            set_awaiting_pickleball_input(target_id)
            cancel_qr = get_pickleball_cancel_quick_reply()
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請輸入開團文或成員名單", quick_reply=cancel_qr)],
                )
            )
            return "OK", 200

        # 取消名單輸入
        if sub == "cancel":
            clear_awaiting_pickleball_input(target_id)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="已取消分組操作。")],
                )
            )
            return "OK", 200

        # 賽事精華
        if sub == "highlights":
            video = get_pickleball_highlight_video()
            if not video:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="抱歉，目前暫時無法從 YouTube 取得最新賽事精華，請稍後再試。")],
                    )
                )
            else:
                flex_msg = create_pickleball_highlight_flex(video)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[flex_msg],
                    )
                )
            return "OK", 200

        # 匹克球規則
        if sub == "rules":
            flex_msg = create_pickleball_rules_flex()
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_msg],
                )
            )
            return "OK", 200

        # 一鍵重新洗牌
        if sub == "reshuffle":
            session = get_pickleball_session(target_id)
            if not session or not session.get("players"):
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="查無有效的分組紀錄，請重新傳送名單。")],
                    )
                )
                return "OK", 200

            players = session["players"]
            court_limit = session.get("court_limit")
            result = random_group(players, court_limit=court_limit)
            save_pickleball_session(target_id, players, court_limit, waitlist=session.get("waitlist", []), last_result=result)

            waitlist = session.get("waitlist", [])
            reply_messages = []
            reply_messages.append(create_pickleball_group_flex(result))
            
            if result.get("courts"):
                reply_messages.append(
                    TextMessage(
                        text=format_group_result(result, waitlist),
                        quick_reply=get_pickleball_quick_reply()
                    )
                )
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=reply_messages,
                )
            )
            return "OK", 200

        # 展開移除球友選單
        if sub == "remove_player_menu":
            session = get_pickleball_session(target_id)
            if not session or not session.get("players"):
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="查無有效的分組紀錄，請重新傳送名單。")],
                    )
                )
                return "OK", 200
            
            players = session["players"]
            remove_qr = get_remove_player_quick_reply(players)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請選擇要移除的球友：", quick_reply=remove_qr)],
                )
            )
            return "OK", 200

        # 執行移除球友
        if sub == "remove_player":
            name_encoded = parsed_data.get("name", [""])[0]
            name_to_remove = urllib.parse.unquote(name_encoded)
            if not name_to_remove:
                return "OK", 200
                
            res = remove_player_and_promote(target_id, name_to_remove)
            if not res:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"無法移除球友 {name_to_remove}，可能是找不到該名稱。")],
                    )
                )
                return "OK", 200

            promoted_name = res.get("promoted")
            new_players = res.get("players", [])
            new_waitlist = res.get("waitlist", [])
            court_limit = res.get("court_limit")
            
            messages = []
            if promoted_name:
                announcement = f"@{promoted_name} 候補遞補成功，請確認出席！\n目前正選人數：{len(new_players)} 人"
            else:
                announcement = f"已移除 {name_to_remove}，目前無候補名單。\n目前正選人數：{len(new_players)} 人"
            
            if len(new_players) >= 4:
                new_result = random_group(new_players, court_limit=court_limit)
                save_pickleball_session(target_id, new_players, court_limit, waitlist=new_waitlist, last_result=new_result)
                
                messages.append(create_pickleball_group_flex(new_result))
                messages.append(
                    TextMessage(
                        text=f"{announcement}\n\n" + format_group_result(new_result, new_waitlist),
                        quick_reply=get_pickleball_quick_reply()
                    )
                )
            else:
                messages.append(
                    TextMessage(
                        text=announcement,
                        quick_reply=get_pickleball_quick_reply()
                    )
                )
                
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages,
                )
            )
            return "OK", 200

    return "OK", 200
