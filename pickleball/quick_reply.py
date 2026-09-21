"""匹克球 QuickReply 快捷按鈕產生模組。

為分組結果附帶一鍵操作按鈕，提供重新洗牌、多輪賽程切換、場地數變更與自動開鍵盤貼上新名單。
"""

import urllib.parse
from typing import List, Optional
from linebot.v3.messaging import PostbackAction, QuickReply, QuickReplyItem
from pickleball.constants import DEFAULT_COURT_SIZE


def get_pickleball_quick_reply(
    total_players: int,
    current_court: int = 1,
    current_rounds: int = 1,
) -> QuickReply:
    """產生分組結果專屬的 QuickReply 快捷按鈕。"""
    items = []

    # 1. 重新洗牌按鈕
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="重新洗牌",
                data="action=pickle_action&sub=reshuffle",
                display_text="重新洗牌",
            )
        )
    )

    # 2. 多輪賽程按鈕 (依人數推薦 2 輪或 3 輪)
    if current_rounds != 2:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label="排 2 輪賽程",
                    data="action=pickle_action&sub=rounds&rounds=2",
                    display_text="排 2 輪賽程",
                )
            )
        )

    if current_rounds != 3:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label="排 3 輪賽程",
                    data="action=pickle_action&sub=rounds&rounds=3",
                    display_text="排 3 輪賽程",
                )
            )
        )

    # 3. 場地數動態切換按鈕 (若人數滿 8 人以上可切換)
    if total_players >= DEFAULT_COURT_SIZE * 2:
        if current_court == 1:
            items.append(
                QuickReplyItem(
                    action=PostbackAction(
                        label="改為 2 面場",
                        data="action=pickle_action&sub=court&court=2",
                        display_text="改為 2 面場",
                    )
                )
            )
        else:
            items.append(
                QuickReplyItem(
                    action=PostbackAction(
                        label="改為 1 面場",
                        data="action=pickle_action&sub=court&court=1",
                        display_text="改為 1 面場",
                    )
                )
            )

    # 4. 移除球友（有人取消時啟動候補遞補流程）
    if total_players >= 1:
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label="移除球友",
                    data="action=pickle_action&sub=remove_player_menu",
                    display_text="移除球友",
                )
            )
        )

    # 5. 貼上新開團文 (自動開啟鍵盤並填入前綴)
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="貼上新開團文",
                data="action=pickle_action&sub=prompt_input",
                display_text="貼上新開團文",
            )
        )
    )

    # 6. 純文字版 (方便球友長按複製轉傳)
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="純文字版",
                data="action=pickle_action&sub=text_mode",
                display_text="純文字版",
            )
        )
    )

    # 7. 取消按鈕 (關閉 QuickReply 選單)
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="取消",
                data="action=pickle_action&sub=cancel",
                display_text="取消",
            )
        )
    )

    return QuickReply(items=items)


def get_pickleball_cancel_quick_reply() -> QuickReply:
    """產生僅含「取消」按鈕的 QuickReply，供輸入引導訊息使用。"""
    return QuickReply(
        items=[
            QuickReplyItem(
                action=PostbackAction(
                    label="取消",
                    data="action=pickle_action&sub=cancel",
                    display_text="取消",
                )
            )
        ]
    )


def get_remove_player_quick_reply(players: List[str]) -> QuickReply:
    """產生動態選人 QuickReply，供「移除球友」操作使用。

    為正選名單中每位球友產生一個 PostbackAction 按鈕（上限 12 人），
    並附加「取消」按鈕。使用者點選後，Bot 將自動移除該球友並遞補候補。

    LINE QuickReply 上限為 13 個，保留 1 個給「取消」，最多顯示 12 位球友。
    """
    items = []

    # 最多顯示 12 位 (保留 1 個位置給取消按鈕)
    display_players = players[:12]

    for name in display_players:
        encoded_name = urllib.parse.quote(name)
        items.append(
            QuickReplyItem(
                action=PostbackAction(
                    label=name[:20],  # LINE label 最長 20 字元
                    data=f"action=pickle_action&sub=remove_player&name={encoded_name}",
                    display_text=f"移除 {name}",
                )
            )
        )

    # 取消按鈕
    items.append(
        QuickReplyItem(
            action=PostbackAction(
                label="取消",
                data="action=pickle_action&sub=cancel",
                display_text="取消",
            )
        )
    )

    return QuickReply(items=items)
