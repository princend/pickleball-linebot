"""匹克球相關指令處理器。

負責處理隨機分組、名單解析、分組說明與名單快取一鍵重新洗牌等文字指令。
"""

from linebot.v3.messaging import ReplyMessageRequest, TextMessage
from pickleball import (
    create_menu_flex,
    GROUPING_HELP_TEXT,
    STEP_COURTS,
    STEP_DATE,
    STEP_FEE,
    STEP_LEVEL,
    STEP_LOCATION,
    STEP_PLAYERS,
    STEP_TIME,
    STEP_TITLE,
    ask_pickleball_ai,
    clear_awaiting_pickleball_input,
    clear_group_creation_session,
    convert_relative_date,
    create_events_flex,
    create_group_rules_flex,
    create_pickleball_dupr_flex,
    create_pickleball_group_flex,
    create_pickleball_highlight_flex,
    create_pickleball_rules_flex,
    format_group_result,
    format_time_input,
    generate_group_announcement,
    get_county_quick_reply,
    get_event_region_quick_reply,
    get_group_creation_session,
    create_paddle_recommendation_flex,
    get_paddle_budget_quick_reply,
    get_paddle_style_quick_reply,
    get_pickleball_cancel_quick_reply,
    get_pre_grouping_quick_reply,
    get_pickleball_highlight_video,
    get_pickleball_quick_reply,
    get_pickleball_session,
    get_step_prompt_and_quick_reply,
    is_awaiting_pickleball_input,
    parse_player_input,
    random_group,
    save_pickleball_session,
    set_group_creation_session,
    set_awaiting_pickleball_input,
    search_youtube_video,
    create_video_flex,
    set_awaiting_ai_input,
    is_awaiting_ai_input,
    clear_awaiting_ai_input,
)


def handle_pickleball_command(text: str, user_id: str, target_id: str, event, line_bot_api):
    """處理匹克球與隨機分組文字訊息指令。

    支援指令格式範例:
    - 匹克球分組
    - 重新洗牌 / 重分 / 下一輪 (使用快取名單一鍵重新分組)
    - 開團 / 匹克球開團 (啟動七步驟對話式開團精靈)
    - 匹克球分組 2個場地 2輪: [貼上名單]
    - [直接貼上整篇開團文]
    """
    stripped_text = text.strip().replace("！", "!")
    effective_target_id = target_id or user_id

    # 0-0. 檢查是否處於等待 AI 輸入狀態
    if is_awaiting_ai_input(user_id) and not stripped_text.startswith("!"):
        clear_awaiting_ai_input(user_id)
        # 加上明確的匹克球前綴，確保如「長丁克」等簡短名詞不會被 AI 誤判拒答
        stripped_text = f"!ai 關於匹克球，請告訴我：{stripped_text}"

    # 0-1. 檢查是否正處於七步驟開團對話會話中
    creation_session = get_group_creation_session(effective_target_id)
    if creation_session:
        # 使用者主動取消開團
        if stripped_text in ["取消", "取消開團", "結束", "不用了"]:
            clear_group_creation_session(effective_target_id)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="已取消開團操作。")],
                )
            )
            return "OK", 200

        current_step = creation_session.get("step", STEP_TITLE)
        collected = creation_session.get("data", {})

        if current_step == STEP_TITLE:
            collected["title"] = stripped_text
            creation_session["step"] = STEP_DATE
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_DATE, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_DATE:
            collected["date"] = convert_relative_date(stripped_text)
            creation_session["step"] = STEP_TIME
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_TIME, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_TIME:
            collected["time"] = format_time_input(stripped_text)
            creation_session["step"] = STEP_LOCATION
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_LOCATION, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_LOCATION:
            collected["location"] = stripped_text
            creation_session["step"] = STEP_COURTS
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_COURTS, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_COURTS:
            collected["courts"] = stripped_text
            creation_session["step"] = STEP_PLAYERS
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_PLAYERS, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_PLAYERS:
            collected["players"] = stripped_text
            creation_session["step"] = STEP_LEVEL
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_LEVEL, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_LEVEL:
            collected["level"] = stripped_text
            creation_session["step"] = STEP_FEE
            creation_session["data"] = collected
            set_group_creation_session(effective_target_id, creation_session)
            prompt_text, qr = get_step_prompt_and_quick_reply(STEP_FEE, collected)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=prompt_text, quick_reply=qr)],
                )
            )
            return "OK", 200

        elif current_step == STEP_FEE:
            collected["fee"] = stripped_text
            clear_group_creation_session(effective_target_id)
            announcement_text = generate_group_announcement(collected)
            hint_text = "開團文已產生！您可以直接長按上方訊息複製並轉發到 LINE 群組或社群揪球友。"
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text=announcement_text),
                        TextMessage(text=hint_text),
                    ],
                )
            )
            return "OK", 200


    # 0-0. 主選單指令
    if stripped_text == "!指令" or stripped_text.lower() == "!menu":
        menu_flex = create_menu_flex()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[menu_flex],
            )
        )
        return "OK", 200

    # 0-2. 文字指令啟動開團精靈
    if stripped_text in ["!開團", "!匹克球開團", "!我要開團", "!發起開團", "!建立開團文"]:
        session_data = {"step": STEP_TITLE, "data": {}}
        set_group_creation_session(effective_target_id, session_data)
        prompt_text, qr = get_step_prompt_and_quick_reply(STEP_TITLE)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=prompt_text, quick_reply=qr)],
            )
        )
        return "OK", 200

    if stripped_text == "!AI問答" or stripped_text == "!ai問答":
        set_awaiting_ai_input(user_id)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="【AI 匹克球教練】\n請直接輸入您的問題（不需加 !ai），例如：\n\n「匹克球發球規則是什麼？」\n「推薦適合新手的球拍」")]
            )
        )
        return "OK", 200

    if stripped_text in ["!球路教學", "!球路"]:
        set_awaiting_ai_input(user_id)
        from linebot.v3.messaging import QuickReply, QuickReplyItem, MessageAction
        qr = QuickReply(items=[
            QuickReplyItem(action=MessageAction(label="短丁 (Dink)", text="短丁")),
            QuickReplyItem(action=MessageAction(label="抽球 (Drive)", text="抽球")),
            QuickReplyItem(action=MessageAction(label="第三板 (Drop)", text="第三板過渡")),
            QuickReplyItem(action=MessageAction(label="挑高球 (Lob)", text="挑高球")),
            QuickReplyItem(action=MessageAction(label="ATP", text="ATP")),
            QuickReplyItem(action=MessageAction(label="Erne", text="Erne")),
        ])
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="【球路教學影片搜尋】\n請點擊下方快速按鈕，或手動直接輸入（例如：長丁克）來查詢：", quick_reply=qr)]
            )
        )
        return "OK", 200

    # 0-3. AI 匹克球專屬問答指令 (!ai:問題 / !ai 問題 / !ai)
    lower_text = stripped_text.lower()
    if lower_text == "!ai" or lower_text.startswith("!ai:") or lower_text.startswith("!ai：") or lower_text.startswith("!ai "):
        if lower_text == "!ai":
            question = ""
        elif lower_text.startswith("!ai:") or lower_text.startswith("!ai："):
            question = stripped_text[4:].strip()
        else:
            question = stripped_text[3:].strip()

        if not question:
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請在指令後方輸入問題，例如：!ai 匹克球發球規則是什麼？")]
                )
            )
        else:
            reply_text = ask_pickleball_ai(question)
            
            # 解析是否帶有 [VIDEO_QUERY] 標記
            video_query_marker = "[VIDEO_QUERY]"
            messages = []
            if video_query_marker in reply_text:
                parts = reply_text.split(video_query_marker)
                main_text = parts[0].strip()
                query = parts[1].strip()
                
                # 若 AI 提供了解釋，加入文字訊息
                if main_text:
                    messages.append(TextMessage(text=main_text))
                    
                # 搜尋影片並建立 Flex Message
                video_data = search_youtube_video(query)
                video_flex = create_video_flex(query, video_data)
                messages.append(video_flex)
            else:
                messages.append(TextMessage(text=reply_text))

            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages,
                )
            )
        return "OK", 200
    # 0-4. 球拍推薦指令 (!選球拍 / !推薦球拍 / !球拍推薦 / !球拍)
    paddle_keywords = [
        "!選球拍",
        "!推薦球拍",
        "!球拍推薦",
        "!球拍",
        "!匹克球球拍",
        "!paddle",
        "!paddles",
    ]
    if stripped_text.lower() in [k.lower() for k in paddle_keywords]:
        paddle_qr = get_paddle_budget_quick_reply()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text="請選擇您的預算範圍，小幫手將為您推薦符合需求的熱門球拍：",
                        quick_reply=paddle_qr,
                    )
                ],
            )
        )
        return "OK", 200

    # 1. 匹克球球場查詢指令 (顯示縣市 QuickReply，由 PostbackHandler 接手爬取球場資料)
    court_keywords = [
        "!匹克球球場",
        "!查球場",
        "!球場查詢",
        "!匹克球場地",
        "!附近球場",
        "!pickleball courts",
    ]
    if stripped_text.lower() in [k.lower() for k in court_keywords]:
        county_qr = get_county_quick_reply()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text="請選擇要查詢的縣市，Bot 將即時從 ipickleball.com.tw 取得最新球場資料。",
                        quick_reply=county_qr,
                    )
                ],
            )
        )
        return "OK", 200

    # 2. 匹克球賽事精華推薦指令 (關鍵字均需明確包含「匹克球」，避免誤觸其他主題)
    highlight_keywords = [
        "!匹克球精華",
        "!匹克球賽事精華",
        "!匹克球影片",
        "!匹克球精彩剪輯",
        "!匹克球剪輯",
        "!匹克球賽事",
        "!pickleball highlights",
        "!pickleball highlight",
    ]
    if stripped_text.lower() in [k.lower() for k in highlight_keywords]:
        video = get_pickleball_highlight_video()
        if not video:
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="抱歉，目前暫時無法從 YouTube 取得最新賽事精華，請稍後再試。")],
                )
            )
            return "OK", 200

        flex_msg = create_pickleball_highlight_flex(video)
        text_msg = TextMessage(
            text=f"【匹克球精彩賽事推薦】\n{video.get('title', '')}\n{video.get('url', '')}"
        )
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[flex_msg, text_msg],
            )
        )
        return "OK", 200

    # 2. 匹克球規則說明指令 (回傳規則 Flex 卡片，絕不帶 QuickReply)
    rule_keywords = [
        "!匹克球規則",
        "!匹克球基本規則",
        "!匹克球新手規則",
        "!匹克球教學",
        "!匹克球怎麼玩",
        "!匹克球玩法",
        "!pickleball rules",
    ]
    if stripped_text.lower() in [k.lower() for k in rule_keywords]:
        rules_flex = create_pickleball_rules_flex()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[rules_flex],
            )
        )
        return "OK", 200

    # 2.5 實力分級指令
    dupr_keywords = ["!dupr", "!分級", "!實力測驗", "!匹克球分級", "!等級"]
    if stripped_text.lower() in [k.lower() for k in dupr_keywords]:
        flex_msg = create_pickleball_dupr_flex()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[flex_msg],
            )
        )
        return "OK", 200

    # 2.6 近期賽事指令
    event_keywords = ["!賽事", "!比賽", "!近期賽事", "!賽事行事曆", "!賽事精華", "!比賽資訊"]
    
    # 檢查是否為賽事相關指令開頭
    is_event_cmd = any(stripped_text.lower().startswith(k.lower()) for k in event_keywords)
    if is_event_cmd and stripped_text.lower() != "!賽事精華":
        # 解析是否帶有區域參數 (例如: !賽事 北部)
        parts = stripped_text.split()
        region = "全部"
        if len(parts) > 1:
            region = parts[1]
            
        if len(parts) == 1:
            # 沒帶參數，先回傳 Quick Reply 讓使用者選擇
            qr = get_event_region_quick_reply()
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請問你想查詢哪個區域的近期賽事？", quick_reply=qr)],
                )
            )
        else:
            # 有帶參數，直接回傳過濾後的 FlexMessage (並附上 QR 方便切換)
            qr = get_event_region_quick_reply()
            flex_msg = create_events_flex(region=region, quick_reply=qr)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_msg],
                )
            )
        return "OK", 200

    # 2.8 群組規範指令
    if stripped_text.lower() in ["!群組規範", "!公告", "!版規"]:
        flex_msg = create_group_rules_flex()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[flex_msg]
            )
        )
        return "OK", 200

    # 3. 快捷一鍵操作 (重新洗牌、重分、下一輪)
    if stripped_text in ["!重新洗牌", "!重分", "!再分一次", "!下一輪"]:
        session = get_pickleball_session(effective_target_id)
        if session and session.get("players"):
            cached_players = session["players"]
            cached_court = session.get("court_limit")
            cached_waitlist = session.get("waitlist", [])

            group_result = random_group(
                players=cached_players,
                court_limit=cached_court,
                rounds=1,
                mode="doubles",
                waitlist=cached_waitlist,
            )
            save_pickleball_session(
                target_id=effective_target_id,
                players=cached_players,
                court_limit=cached_court,
                waitlist=cached_waitlist,
                last_result=group_result,
            )
            quick_reply = get_pickleball_quick_reply(
                total_players=len(cached_players),
                current_court=group_result.get("court_count", 1),
                current_rounds=1,
            )
            flex_msg = create_pickleball_group_flex(group_result, quick_reply=quick_reply)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_msg],
                )
            )
            return "OK", 200
        else:
            quick_reply = get_pickleball_quick_reply(total_players=0)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="目前沒有暫存的球友名單，請點下方按鈕貼上開團文開始分組。",
                            quick_reply=quick_reply,
                        )
                    ],
                )
            )
            return "OK", 200

    # 2. 檢查是否正處於點擊「分組」後等待輸入開團文的狀態
    if is_awaiting_pickleball_input(effective_target_id):
        if stripped_text in ["取消", "結束", "不用了"]:
            clear_awaiting_pickleball_input(effective_target_id)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="已取消分組操作。")],
                )
            )
            return "OK", 200

        # 將輸入作為名單嘗試解析
        p_wait, c_wait, r_wait, gc_wait, pg_wait, m_wait, w_wait = parse_player_input(stripped_text)
        if p_wait and len(p_wait) >= 1:
            clear_awaiting_pickleball_input(effective_target_id)
            
            # 若為預設模式且使用者未明確指定輪數，先詢問排賽程條件
            if m_wait == "doubles" and r_wait is None:
                save_pickleball_session(
                    target_id=effective_target_id,
                    players=p_wait,
                    court_limit=c_wait,
                    waitlist=w_wait,
                    last_result=None,
                )
                pre_group_qr = get_pre_grouping_quick_reply(len(p_wait))
                court_msg = f" (系統偵測為 {c_wait} 面場)" if c_wait else ""
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(
                                text=f"成功解析名單，正選共 {len(p_wait)} 人！{court_msg}\n請問您想排幾輪賽程或調整場地數？",
                                quick_reply=pre_group_qr,
                            )
                        ],
                    )
                )
                return "OK", 200

            group_result = random_group(
                players=p_wait,
                court_limit=c_wait,
                rounds=r_wait,
                group_count=gc_wait,
                per_group=pg_wait,
                mode=m_wait,
                waitlist=w_wait,
            )
            if group_result.get("status") != "empty":
                save_pickleball_session(
                    target_id=effective_target_id,
                    players=p_wait,
                    court_limit=c_wait or group_result.get("court_count"),
                    waitlist=w_wait,
                    last_result=group_result,
                )
                quick_reply = get_pickleball_quick_reply(
                    total_players=len(p_wait),
                    current_court=group_result.get("court_count", c_wait or 1),
                    current_rounds=r_wait or 1,
                )
                flex_msg = create_pickleball_group_flex(group_result, quick_reply=quick_reply)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[flex_msg],
                    )
                )
                return "OK", 200

    # 3. 判定是否為明確分組指令 (嚴禁模糊自動觸發，避免球友接龍時連環誤發分組)
    matching_keywords = [
        "!匹克球隨機分組",
        "!匹克球分組",
        "!隨機分組",
        "!球友分組",
        "!匹克球說明",
        "!分組說明",
        "!分組",
    ]

    matched_keyword = None
    for kw in matching_keywords:
        if stripped_text == kw or stripped_text.startswith(kw):
            matched_keyword = kw
            break

    # 若未帶明確分組指令前綴，直接略過，不干涉一般聊天與球友接龍訊息
    if not matched_keyword:
        return None

    # 如果輸入「分組說明」，純文字回傳操作指引說明
    content_after_keyword = stripped_text[len(matched_keyword):].strip()
    
    if stripped_text in ["!分組說明", "!匹克球說明"]:
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=GROUPING_HELP_TEXT)],
            )
        )
        return "OK", 200

    # 如果僅輸入關鍵字，進入等待輸入名單狀態
    if not content_after_keyword:
        set_awaiting_pickleball_input(effective_target_id)
        cancel_qr = get_pickleball_cancel_quick_reply()
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="請輸入開團文或成員名單", quick_reply=cancel_qr)],
            )
        )
        return "OK", 200

    # 解析名單與分組參數 (包含開團文偵測與活動候補名單)
    players, court_limit, rounds, group_count, per_group, mode, waitlist = parse_player_input(stripped_text)

    if mode == "help" or not players:
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=GROUPING_HELP_TEXT)],
            )
        )
        return "OK", 200

    # 若為預設模式且使用者未明確指定輪數，先詢問排賽程條件
    if mode == "doubles" and rounds is None:
        save_pickleball_session(
            target_id=effective_target_id,
            players=players,
            court_limit=court_limit,
            waitlist=waitlist,
            last_result=None,
        )
        pre_group_qr = get_pre_grouping_quick_reply(len(players))
        court_msg = f" (系統偵測為 {court_limit} 面場)" if court_limit else ""
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=f"成功解析名單，正選共 {len(players)} 人！{court_msg}\n請問您想排幾輪賽程或調整場地數？",
                        quick_reply=pre_group_qr,
                    )
                ],
            )
        )
        return "OK", 200

    # 執行隨機分組運算
    group_result = random_group(
        players=players,
        court_limit=court_limit,
        rounds=rounds,
        group_count=group_count,
        per_group=per_group,
        mode=mode,
        waitlist=waitlist,
    )

    # 成功分組後將名單儲存至快取 (記憶 60 分鐘)
    save_pickleball_session(
        target_id=effective_target_id,
        players=players,
        court_limit=court_limit,
        waitlist=waitlist,
        last_result=group_result,
    )

    # 組裝 QuickReply 快捷按鈕
    quick_reply = get_pickleball_quick_reply(
        total_players=len(players),
        current_court=group_result.get("court_count", 1),
        current_rounds=rounds or 1,
    )
    flex_msg = create_pickleball_group_flex(group_result, quick_reply=quick_reply)

    line_bot_api.reply_message_with_http_info(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[flex_msg],
        )
    )
    return "OK", 200
