"""匹克球 (Pickleball) 開團功能與開團文產生器模組。

提供七步驟對話式問答引導 (活動名稱、日期、時段、地點、幾面場、幾人、程度)，
並依據輸入內容自動產生標準整齊、可直接複製轉傳的匹克球開團文。
嚴格遵守 No Emoji Policy (無表情符號規範) 與全繁體中文輸出。
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from pickleball.court_finder import COUNTIES
from linebot.v3.messaging import (
    DatetimePickerAction,
    MessageAction,
    PostbackAction,
    QuickReply,
    QuickReplyItem,
)

# 台灣時區常數與星期中文對照表
TAIPEI_TZ = timezone(timedelta(hours=8))
WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]

# 開團七步驟常數定義
STEP_TITLE = "title"
STEP_DATE = "date"
STEP_TIME = "time"
STEP_LOCATION = "location"
STEP_COURTS = "courts"
STEP_PLAYERS = "players"
STEP_LEVEL = "level"
STEP_FEE = "fee"

STEP_SEQUENCE = [
    STEP_TITLE,
    STEP_DATE,
    STEP_TIME,
    STEP_LOCATION,
    STEP_COURTS,
    STEP_PLAYERS,
    STEP_LEVEL,
]


def convert_relative_date(raw_date_text: str, base_dt: Optional[datetime] = None) -> str:
    """將相對日期文字 (例如「明天」、「今天」、「本週六」或「2026-09-18」) 換算為具體日期與星期。

    若無法辨識相對語意則原樣傳回。
    範例輸出: 9/18 (五)
    """
    if not raw_date_text:
        return "未定"
    text = raw_date_text.strip()
    if base_dt is None:
        base_dt = datetime.now(TAIPEI_TZ)

    # 1. 支援 DatetimePicker 或標準 ISO 日期格式 (YYYY-MM-DD)
    iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        dt = datetime(y, m, d, tzinfo=TAIPEI_TZ)
        return f"{dt.month}/{dt.day} ({WEEKDAY_NAMES[dt.weekday()]})"

    # 2. 判斷今天
    if "今天" in text or text == "今":
        return f"{base_dt.month}/{base_dt.day} ({WEEKDAY_NAMES[base_dt.weekday()]})"

    # 3. 判斷明天
    if "明天" in text or text == "明":
        d = base_dt + timedelta(days=1)
        return f"{d.month}/{d.day} ({WEEKDAY_NAMES[d.weekday()]})"

    # 4. 判斷後天
    if "後天" in text:
        d = base_dt + timedelta(days=2)
        return f"{d.month}/{d.day} ({WEEKDAY_NAMES[d.weekday()]})"

    # 5. 判斷大後天
    if "大後天" in text:
        d = base_dt + timedelta(days=3)
        return f"{d.month}/{d.day} ({WEEKDAY_NAMES[d.weekday()]})"

    # 6. 判斷週六
    if any(k in text for k in ["本週六", "這週六", "週六", "星期六", "禮拜六"]):
        days_ahead = (5 - base_dt.weekday()) % 7
        if "下" in text:
            days_ahead += 7
        d = base_dt + timedelta(days=days_ahead)
        return f"{d.month}/{d.day} ({WEEKDAY_NAMES[d.weekday()]})"

    # 7. 判斷週日
    if any(k in text for k in ["本週日", "這週日", "週日", "星期日", "禮拜日", "星期天", "禮拜天"]):
        days_ahead = (6 - base_dt.weekday()) % 7
        if "下" in text:
            days_ahead += 7
        d = base_dt + timedelta(days=days_ahead)
        return f"{d.month}/{d.day} ({WEEKDAY_NAMES[d.weekday()]})"

    return text


def format_time_input(raw_time_text: str) -> str:
    """將單一時間點 (如「19:00」或 DatetimePicker 回傳之「19:00」) 格式化為預設 2 小時打球區間。

    若已為區間字串或自訂文字則原樣傳回。
    """
    if not raw_time_text:
        return "未定"
    text = raw_time_text.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        start_t = f"{h:02d}:{m:02d}"
        end_h = (h + 2) % 24
        end_t = f"{end_h:02d}:{m:02d}"
        return f"{start_t} - {end_t}"
    return text


def get_step_prompt_and_quick_reply(
    step: str,
    collected_data: Optional[Dict[str, Any]] = None,
) -> Tuple[str, QuickReply]:
    """依據當前步驟傳回友善引導文字與專屬 QuickReply 快捷選項。"""
    collected_data = collected_data or {}
    cancel_action = PostbackAction(
        label="取消開團",
        data="action=pickle_action&sub=cancel_create_group",
        display_text="取消開團",
    )

    if step == STEP_TITLE:
        prompt = "【開團步驟 1/8】\n請選擇或輸入【活動名稱】（點選下方快捷或直接輸入自訂名稱）："
        items = [
            QuickReplyItem(action=MessageAction(label="匹克球球聚", text="匹克球球聚")),
            QuickReplyItem(action=MessageAction(label="匹克球暢打", text="匹克球暢打")),
            QuickReplyItem(action=MessageAction(label="匹克球新手友善", text="匹克球新手友善")),
            QuickReplyItem(action=MessageAction(label="匹克球友誼賽", text="匹克球友誼賽")),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    if step == STEP_DATE:
        title_str = collected_data.get("title", "匹克球球聚")
        prompt = f"【開團步驟 2/8】\n已設定名稱：{title_str}\n請選擇或輸入打球【日期】（可點選快捷、挑選日曆或直接輸入）："
        now = datetime.now(TAIPEI_TZ)
        d_today = now
        d_tomorrow = now + timedelta(days=1)

        days_to_sat = (5 - now.weekday()) % 7
        if days_to_sat == 0 and now.hour >= 22:
            days_to_sat = 7
        d_sat = now + timedelta(days=days_to_sat)

        days_to_sun = (6 - now.weekday()) % 7
        if days_to_sun == 0 and now.hour >= 22:
            days_to_sun = 7
        d_sun = now + timedelta(days=days_to_sun)

        today_text = f"{d_today.month}/{d_today.day} ({WEEKDAY_NAMES[d_today.weekday()]})"
        tomorrow_text = f"{d_tomorrow.month}/{d_tomorrow.day} ({WEEKDAY_NAMES[d_tomorrow.weekday()]})"
        sat_text = f"{d_sat.month}/{d_sat.day} ({WEEKDAY_NAMES[d_sat.weekday()]})"
        sun_text = f"{d_sun.month}/{d_sun.day} ({WEEKDAY_NAMES[d_sun.weekday()]})"

        items = [
            QuickReplyItem(
                action=DatetimePickerAction(
                    label="挑選日曆",
                    data="action=pickle_action&sub=pick_date",
                    mode="date",
                    initial=now.strftime("%Y-%m-%d"),
                )
            ),
            QuickReplyItem(action=MessageAction(label=f"今天 ({d_today.month}/{d_today.day})", text=today_text)),
            QuickReplyItem(action=MessageAction(label=f"明天 ({d_tomorrow.month}/{d_tomorrow.day})", text=tomorrow_text)),
            QuickReplyItem(action=MessageAction(label=f"本週六 ({d_sat.month}/{d_sat.day})", text=sat_text)),
            QuickReplyItem(action=MessageAction(label=f"本週日 ({d_sun.month}/{d_sun.day})", text=sun_text)),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    if step == STEP_TIME:
        date_str = collected_data.get("date", "")
        prompt = f"【開團步驟 3/8】\n已設定日期：{date_str}\n請選擇或輸入打球【時段】（可點「自訂時間(Picker)」挑選、點選常用快捷，或手動輸入）："
        items = [
            QuickReplyItem(
                action=DatetimePickerAction(
                    label="自訂時間(Picker)",
                    data="action=pickle_action&sub=pick_time",
                    mode="time",
                    initial="19:00",
                )
            ),
            QuickReplyItem(action=MessageAction(label="08:00 - 10:00", text="08:00 - 10:00")),
            QuickReplyItem(action=MessageAction(label="09:00 - 11:00", text="09:00 - 11:00")),
            QuickReplyItem(action=MessageAction(label="10:00 - 12:00", text="10:00 - 12:00")),
            QuickReplyItem(action=MessageAction(label="13:00 - 15:00", text="13:00 - 15:00")),
            QuickReplyItem(action=MessageAction(label="14:00 - 16:00", text="14:00 - 16:00")),
            QuickReplyItem(action=MessageAction(label="15:00 - 17:00", text="15:00 - 17:00")),
            QuickReplyItem(action=MessageAction(label="16:00 - 18:00", text="16:00 - 18:00")),
            QuickReplyItem(action=MessageAction(label="18:00 - 20:00", text="18:00 - 20:00")),
            QuickReplyItem(action=MessageAction(label="19:00 - 21:00", text="19:00 - 21:00")),
            QuickReplyItem(action=MessageAction(label="20:00 - 22:00", text="20:00 - 22:00")),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    if step == STEP_LOCATION:
        time_str = collected_data.get("time", "")
        prompt = f"【開團步驟 4/8】\n已設定時段：{time_str}\n請選擇【縣市】來尋找球場，或直接「手動輸入」地點名稱："
        items = []
        
        display_counties = list(COUNTIES.keys())[:11] # Reduce to 11 to be absolutely safe (11 + 1 cancel = 12 items)
        for county_name in display_counties:
            items.append(
                QuickReplyItem(
                    action=MessageAction(
                        label=county_name,
                        text=county_name
                    )
                )
            )
            
        items.append(QuickReplyItem(action=cancel_action))
        return prompt, QuickReply(items=items)

    if step == STEP_COURTS:
        loc_str = collected_data.get("location", "")
        prompt = f"【開團步驟 5/8】\n已設定地點：{loc_str}\n請選擇或輸入【場地數量】（例如：1面場、2面場、3面場）："
        items = [
            QuickReplyItem(action=MessageAction(label="1面場", text="1面場")),
            QuickReplyItem(action=MessageAction(label="2面場", text="2面場")),
            QuickReplyItem(action=MessageAction(label="3面場", text="3面場")),
            QuickReplyItem(action=MessageAction(label="4面場", text="4面場")),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    if step == STEP_PLAYERS:
        courts_str = collected_data.get("courts", "")
        prompt = f"【開團步驟 6/8】\n已設定場地：{courts_str}\n請選擇或輸入【報名人數上限】（例如：6人、8人、16人、24人）："
        items = [
            QuickReplyItem(action=MessageAction(label="6人", text="6人")),
            QuickReplyItem(action=MessageAction(label="8人", text="8人")),
            QuickReplyItem(action=MessageAction(label="16人", text="16人")),
            QuickReplyItem(action=MessageAction(label="24人", text="24人")),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    if step == STEP_LEVEL:
        players_str = collected_data.get("players", "")
        prompt = f"【開團步驟 7/8】\n已設定人數：{players_str}\n請選擇或輸入打球【程度/分級】（點選下方快捷或手動輸入自訂程度）："
        items = [
            QuickReplyItem(action=MessageAction(label="不限 (新手友善)", text="不限 (新手友善)")),
            QuickReplyItem(action=MessageAction(label="初階 (DUPR 2.0-2.5)", text="初階 (DUPR 2.0-2.5)")),
            QuickReplyItem(action=MessageAction(label="中階 (DUPR 2.5-3.5)", text="中階 (DUPR 2.5-3.5)")),
            QuickReplyItem(action=MessageAction(label="進階 (DUPR 3.5+)", text="進階 (DUPR 3.5+)")),
            QuickReplyItem(action=MessageAction(label="2.0以上 (歡樂/高手)", text="2.0以上 (歡樂/高手)")),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    if step == STEP_FEE:
        level_str = collected_data.get("level", "")
        prompt = f"【開團步驟 8/8】\n已設定程度：{level_str}\n請選擇或輸入打球【費用】（例如：場地費均分、$150、$200）："
        items = [
            QuickReplyItem(action=MessageAction(label="場地費均分", text="場地費均分")),
            QuickReplyItem(action=MessageAction(label="均分 (依到場人數)", text="場地費均分 (依到場人數)")),
            QuickReplyItem(action=MessageAction(label="$250 / 人", text="$250 / 人")),
            QuickReplyItem(action=MessageAction(label="$150 / 人", text="$150 / 人")),
            QuickReplyItem(action=MessageAction(label="$200 / 人", text="$200 / 人")),
            QuickReplyItem(action=cancel_action),
        ]
        return prompt, QuickReply(items=items)

    return "請輸入資料：", QuickReply(items=[QuickReplyItem(action=cancel_action)])


def parse_player_limit(raw_text: str) -> int:
    """從使用者輸入中解析報名人數上限數字，若無法辨識則預設傳回 8。"""
    digits = re.findall(r"\d+", str(raw_text))
    if digits:
        count = int(digits[0])
        return max(4, min(count, 64))
    return 8


def generate_group_announcement(data: Dict[str, Any]) -> str:
    """依據使用者收集之開團資料產生排版整齊之純文字開團接龍文。"""
    raw_title = data.get("title", "匹克球球聚").strip()
    if not raw_title:
        raw_title = "匹克球球聚"
    if not (raw_title.startswith("【") and raw_title.endswith("】")):
        title_val = f"【{raw_title}】"
    else:
        title_val = raw_title

    date_val = data.get("date", "未定")
    time_val = data.get("time", "未定")
    loc_val = data.get("location", "未定")
    courts_val = data.get("courts", "未定")
    players_limit_raw = data.get("players", "8人")
    level_val = data.get("level", "不限 (新手友善)")
    fee_val = data.get("fee", "場地費均分")

    num_players = parse_player_limit(str(players_limit_raw))

    lines = [
        title_val,
        "",
        f"日期：{date_val}",
        f"時間：{time_val}",
        f"地點：{loc_val}",
        f"場地：{courts_val}",
        f"人數：上限 {num_players} 位",
        f"程度：{level_val}",
        f"費用：{fee_val}",
        "",
        "[報名接龍]",
    ]

    for i in range(1, num_players + 1):
        lines.append(f"{i}.")

    lines.append("")
    lines.append("--- 以下候補 ---")
    for i in range(1, 5):
        lines.append(f"{i}.")

    return "\n".join(lines)
