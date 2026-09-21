"""匹克球隨機分組模組。

提供球友名單解析、洗牌隨機分組、多輪公平輪替賽程排定與結果格式化輸出。
支援 LINE 揪團開團文智慧辨識 (自動偵測場地數、分離正選與候補名單)。
遵循標準雙打規範：每場固定 4 人，每隊嚴格 2 人，絕無一隊 3 人的情況。
"""

import random
import re
from typing import Dict, List, Optional, Tuple
from pickleball.constants import (
    BODY_COURT_PATTERN,
    CHINESE_NUM_MAP,
    COURT_SPEC_PATTERN,
    DEFAULT_COURT_SIZE,
    DEFAULT_TEAM_SIZE,
    GROUP_COUNT_PATTERN,
    GROUPING_HELP_TEXT,
    PER_GROUP_PATTERN,
    ROUNDS_SPEC_PATTERN,
    SPLIT_PATTERN,
)
from pickleball.ai_extractor import extract_players_with_ai, standardize_announcement_with_ai

EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\u3030\u303d]"
)


def remove_emoji(text: str) -> str:
    """去除字串中所有的 Emoji 表情符號"""
    return EMOJI_PATTERN.sub("", text)


# 純 Emoji 暱稱純文字對照字典 (均以 Unicode escape 定義，嚴格遵守 No Emoji Policy)
EMOJI_NAME_MAP = {
    # 常見動物
    "\U0001f426": "小鳥",
    "\U0001f422": "烏龜",
    "\U0001f431": "小貓",
    "\U0001f436": "小狗",
    "\U0001f430": "兔子",
    "\U0001f43b": "小熊",
    "\U0001f43c": "熊貓",
    "\U0001f42f": "老虎",
    "\U0001f981": "獅子",
    "\U0001f98a": "狐狸",
    "\U0001f42e": "小牛",
    "\U0001f437": "小豬",
    "\U0001f438": "青蛙",
    "\U0001f435": "猴子",
    "\U0001f427": "企鵝",
    "\U0001f986": "鴨子",
    "\U0001f985": "老鷹",
    "\U0001f995": "恐龍",
    "\U0001f996": "暴龍",
    "\U0001f42c": "海豚",
    "\U0001f433": "鯨魚",
    "\U0001f41f": "小魚",
    "\U0001f988": "鯊魚",
    "\U0001f419": "章魚",
    "\U0001f98b": "蝴蝶",
    "\U0001f41d": "蜜蜂",
    # 常見水果與物品
    "\U0001f34e": "蘋果",
    "\U0001f34c": "香蕉",
    "\U0001f349": "西瓜",
    "\U0001f353": "草莓",
    "\U0001f352": "櫻桃",
    "\u2b50": "星星",
    "\u2600": "太陽",
    "\U0001f319": "月亮",
    "\U0001f525": "火焰",
    "\u26a1": "閃電",
    "\U0001f47b": "幽靈",
    "\U0001f916": "機器人",
}


def clean_player_name(raw_name: str, fallback_seq: str = "") -> str:
    """清理球友名稱，去除前後空白、序號 (含候補序號)、Emoji 與常見繳費註記。
    若球友暱稱完全由 Emoji 組成，將自動轉譯為中文暱稱或球友序號代稱。
    """
    name = raw_name.strip()
    # 1. 提取序號
    seq_match = re.match(r"^(?:候補|備取)?\s*[(\[]?(\d+)[)\]、.\-\s]+", name)
    seq = seq_match.group(1) if seq_match else str(fallback_seq)

    # 去除序號
    name_without_seq = re.sub(r"^(?:候補|備取)?\s*[(\[]?\d+[)\]、.\-\s]+", "", name).strip()
    
    # 2. 去除常見繳費註記 (如 '已付', '已繳', '已轉' 等)
    name_cleaned = re.sub(r"[\s/]*(?:已付|已繳|已轉|已匯).*$", "", name_without_seq).strip()
    
    # 3. 去除 Emoji 表情符號
    name_without_emoji = remove_emoji(name_cleaned).strip()
    
    if not name_without_emoji:
        # 若去除 Emoji 後為空字串，表示球友暱稱純由 Emoji 組成
        for emoji_char, cn_name in EMOJI_NAME_MAP.items():
            if emoji_char in name_cleaned:
                return cn_name
        return f"球友{seq}" if seq else "球友"

    return name_without_emoji


def is_plausible_player_name(name: str) -> bool:
    """檢查字串是否具備合理球友名稱特徵 (排除長句、完整對話、標籤與句末標點)"""
    s = name.strip()
    if not s or len(s) > 18:
        return False
    if re.search(r"[？?！!。]", s):
        return False
    # 排除 LINE 提及 (@人名) 與常見開團客套說明
    if s.startswith("@") or s.startswith("＠"):
        return False
    if re.search(r"接龍|意者|並請|謝謝|感謝|thank\s*you|額滿|滿額|^[滿\U0001f235]+$", s, re.IGNORECASE):
        return False
    return True


def is_empty_slot(line: str) -> bool:
    """檢查該行是否僅為未填名字之空位 (例如 '6 ', '6.', '6、', '6', '候補1.', '候補1' 或 '6. 空')"""
    s = line.strip()
    if not s:
        return True
    # 整行只有序號或候補序號無名字 (例如 '6', '6.', '6、', '候補1.', '候補1', '備取1.')
    if re.match(r"^(?:候補|備取)?\s*[(\[]?\d+[)\]、.\-\s]*$", s):
        return True
    cleaned = re.sub(r"^(?:候補|備取)?\s*[(\[]?\d+[)\]、.\-\s]+", "", s).strip()
    if not cleaned or cleaned in ["空", "空位", "缺", "待定", "暫缺", "無"]:
        return True
    return False


def detect_court_from_text(text: str) -> Optional[int]:
    """從揪團文中自動辨識場地描述 (例如 '場地：一面場' -> 1, '三面場地' -> 3)"""
    match = BODY_COURT_PATTERN.search(text)
    if not match:
        return None

    val = (match.group(1) or match.group(2) or "").strip()
    if val in CHINESE_NUM_MAP:
        return CHINESE_NUM_MAP[val]
    if val.isdigit():
        return int(val)
    return None


def get_heuristic_court_count(total_players: int) -> int:
    """依球館開團常態 (約每 8 人配 1 面場地) 計算預設場地數:
    - 4 ~ 8 人 (接近 8 人): 自動預設 1 面場地 (4 人上場，其餘輪替)
    - 9 ~ 16 人 (接近 16 人): 自動預設 2 面場地 (8 人上場，其餘輪替)
    - 17 ~ 24 人 (接近 24 人): 自動預設 3 面場地
    """
    if total_players < DEFAULT_COURT_SIZE:
        return 1
    max_courts = total_players // DEFAULT_COURT_SIZE
    estimated_courts = (total_players + 7) // 8
    return min(max(1, estimated_courts), max_courts)


def parse_player_input(
    raw_text: str,
    use_ai: bool = True,
) -> Tuple[List[str], Optional[int], Optional[int], Optional[int], Optional[int], str, List[str]]:
    """解析使用者輸入的字串。

    傳回:
        (players, court_limit, rounds, group_count, per_group, mode, waitlist)
        mode 可為:
        - 'help': 僅輸入關鍵字，需顯示說明
        - 'doubles': 匹克球雙打分組 (支援單輪與多輪排程)
        - 'by_count': 指定分成 N 組 (通用分組)
        - 'by_size': 指定每組 N 人 (通用分組)
    """
    text = raw_text.strip()

    # 移除指令前綴關鍵字
    command_prefixes = [
        "匹克球隨機分組",
        "匹克球分組",
        "隨機分組",
        "球友分組",
        "分組",
    ]
    for prefix in command_prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    if not text:
        return [], None, None, None, None, "help", []

    court_limit = None
    rounds = None
    group_count = None
    per_group = None
    mode = "doubles"

    param_part = ""
    list_part = text

    # 1. 檢查是否有冒號分隔參數與名單 (如 '2個場地 2輪: A B C' 或 '2組: A B C')
    if ":" in text or "：" in text:
        parts = re.split(r"[:：]", text, maxsplit=1)
        # 確保第一部分看起來像參數而非開團文欄位 (如 '時間：')
        if not re.search(r"時間|地點|程度|裝備|費用|上場規則", parts[0]):
            param_part = parts[0].strip()
            list_part = parts[1].strip()

    if param_part:
        court_match = COURT_SPEC_PATTERN.search(param_part)
        rounds_match = ROUNDS_SPEC_PATTERN.search(param_part)
        count_match = GROUP_COUNT_PATTERN.match(param_part)
        size_match = PER_GROUP_PATTERN.match(param_part)

        if court_match:
            court_limit = int(court_match.group(1))
        if rounds_match:
            rounds = int(rounds_match.group(1))

        if not court_match and not rounds_match:
            if count_match:
                group_count = int(count_match.group(1))
                mode = "by_count"
            elif size_match:
                per_group = int(size_match.group(1))
                mode = "by_size"

    # 若未透過冒號分開，但開頭帶有參數 (例如 "2個場地 2輪 P1 P2 ...")
    if mode == "doubles" and not court_limit and not rounds:
        first_tokens_match = re.match(r"^([^\n\r]+?)\s+([^\s].*)$", text, re.DOTALL)
        if first_tokens_match:
            candidate_param = first_tokens_match.group(1).strip()
            candidate_rest = first_tokens_match.group(2).strip()

            c_match = COURT_SPEC_PATTERN.search(candidate_param)
            r_match = ROUNDS_SPEC_PATTERN.search(candidate_param)
            cnt_match = GROUP_COUNT_PATTERN.match(candidate_param)
            sz_match = PER_GROUP_PATTERN.match(candidate_param)

            if c_match or r_match:
                if c_match:
                    court_limit = int(c_match.group(1))
                if r_match:
                    rounds = int(r_match.group(1))
                list_part = candidate_rest
            elif cnt_match:
                group_count = int(cnt_match.group(1))
                mode = "by_count"
                list_part = candidate_rest
            elif sz_match:
                per_group = int(sz_match.group(1))
                mode = "by_size"

    # 方案 B (AI-First): 若為長篇開團文，優先交由 Gemini AI 語意過濾為標準接龍名單 (1.xxx\n2.xxx)
    if use_ai and mode == "doubles" and len(list_part) >= 40 and "\n" in list_part:
        if re.search(r"匹克|打球|報名|接龍|臨打|開團|宵夜|相聚|上限|場地|費用|新手|程度", raw_text):
            try:
                standardized = standardize_announcement_with_ai(list_part)
                if standardized:
                    detected_court = detect_court_from_text(raw_text)
                    ai_players, ai_court, ai_rounds, ai_gc, ai_pg, ai_mode, ai_waitlist = parse_player_input(
                        standardized, use_ai=False
                    )
                    if len(ai_players) >= DEFAULT_COURT_SIZE:
                        final_court = court_limit or ai_court or detected_court
                        final_rounds = rounds or ai_rounds
                        return ai_players, final_court, final_rounds, ai_gc, ai_pg, ai_mode, ai_waitlist
            except Exception as e:
                print(f"[警告] AI 開團文標準化轉換失敗，降級退回規則解析: {e}", flush=True)

    # 若未指定場地數，嘗試從內文中自動偵測 (例如「場地：一面場」)
    if not court_limit:
        detected_court = detect_court_from_text(raw_text)
        if detected_court:
            court_limit = detected_court

    # 智慧處理 LINE 揪團開團文：區分前導資訊、正選名單與候補名單
    lines = [line.strip() for line in list_part.splitlines() if line.strip()]
    cleaned_main_raw = []
    cleaned_waitlist_raw = []

    if len(lines) > 1:
        # 尋找名單起點：優先找明確的名單/接龍標題錨點，次之尋找真正的第一個序號行
        start_idx = 0
        found_start = False
        for idx, line in enumerate(lines):
            if re.search(r"【(?:報名)?接龍】|報名(?:清單|名單|名冊)[：:]?|正選名單[：:]?|^名單[：:]?", line):
                start_idx = idx + 1
                found_start = True
                break

        if not found_start:
            for idx, line in enumerate(lines):
                # 尋找序號 1 開頭且排除日期時間行 (如 (9)/(1)(9), 09-14, 19:00 等)
                if re.match(r"^[(\[]?1[)\]、.\-\s]+", line):
                    if not re.search(r"[/／月日號年~～–-]\s*\d", line) and not re.search(r"[:：]\d{2}", line):
                        start_idx = idx
                        break

        candidate_lines = lines[start_idx:]
        is_waitlist = False

        noise_end_pattern = re.compile(
            r"場館設施|設施全面|飲水機|淋浴間|冷氣空調|停車位|臨時取消|負擔費用|經營不易|注意事項|請體諒|意者接龍|意者請|並請\s*[@＠]|謝謝|thank\s*you|感謝"
        )

        for line in candidate_lines:
            # 檢查候補分隔與滿額標記 (例如 額滿符號, 額滿, ===候補===, 候補, 【候補名單】, 滿額線 等)
            if (
                re.search(r"^[=\-~*#—_\s]*[滿\U0001f235额額]+[=\-~*#—_\s]*$", line)
                or re.search(r"^[=\-~*#—_]{2,}\s*(?:[滿\U0001f235]|候補|備取)?", line)
                or re.search(r"^[【\[(]?(?:候補|備取|候選)", line)
            ):
                is_waitlist = True
                cleaned_marker = re.sub(r"^[=\-~*#—_\s]+|[=\-~*#—_\s]+$|[滿\U0001f235额額]", "", line).strip()
                cleaned_marker = re.sub(r"^[【\[(]?(?:候補|備取|候選)(?:名單|人員|區)?[】\])]?[=\-~*#—_\s]*", "", cleaned_marker).strip()
                if not cleaned_marker or is_empty_slot(cleaned_marker):
                    continue
                line = cleaned_marker

            # 遇到場館設施、收費規範、取消規則或文末意者接龍等雜訊，名單正式終止
            if noise_end_pattern.search(line) and not re.match(r"^[(\[]?\d+[)\]、.\-\s]+", line):
                break

            # 跳過規則、說明、費用與裝備等雜訊行
            if re.match(r"^[•*·\-]\s*", line) or re.search(r"^(?:[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\s])*(?:時間|地點|場地|程度|裝備|費用|規則|備註)[：:]", line):
                continue

            # 跳過未填名字之空位行 (例如 '6 ', '6.', '候補1.')
            if is_empty_slot(line):
                continue

            target_list = cleaned_waitlist_raw if is_waitlist else cleaned_main_raw

            # 檢查是否有序號 (支援標準序號與候補序號，例如 '1、Coach ...' 或 '候補1. 木子')
            is_numbered = bool(re.match(r"^(?:候補|備取)?\s*[(\[]?\d+[)\]、.\-\s]+", line))
            content_after_num = re.sub(r"^(?:候補|備取)?\s*[(\[]?\d+[)\]、.\-\s]+", "", line).strip()
            # 檢查行內是否有逗號/分號/頓號或中文空格分隔多人
            has_multiple_players = bool(re.search(r"[,，;；、]", content_after_num)) or bool(
                " " in content_after_num and all(re.search(r"[\u4e00-\u9fa5]", w) for w in content_after_num.split())
            )

            if is_numbered and not has_multiple_players:
                # 標準單行單人接龍 (例如 '1、Coach Omaha 3.0' 或 '4.倫')
                cleaned = clean_player_name(line)
                if cleaned:
                    target_list.append(cleaned)
            else:
                # 處理一行內含多位球友或無序號但具備合理球友名稱特徵之行
                cleaned_line = content_after_num if is_numbered else line.strip()
                sub_parts = re.split(r"[,，;；、]+", cleaned_line)
                for part in sub_parts:
                    part = part.strip()
                    if not part:
                        continue
                    if " " in part:
                        words = part.split()
                        if all(re.search(r"[\u4e00-\u9fa5]", w) for w in words):
                            for w in words:
                                c = clean_player_name(w)
                                if c and is_plausible_player_name(c):
                                    target_list.append(c)
                            continue
                    if is_plausible_player_name(part):
                        c = clean_player_name(part)
                        if c:
                            target_list.append(c)
    else:
        # 單行輸入情境
        cleaned_line = list_part.strip()
        if re.search(r"[,，;；、]", cleaned_line):
            sub_parts = re.split(r"[,，;；、]+", cleaned_line)
            for part in sub_parts:
                part = part.strip()
                if not part:
                    continue
                if " " in part:
                    words = part.split()
                    if all(re.search(r"[\u4e00-\u9fa5]", w) for w in words):
                        for w in words:
                            c = clean_player_name(w)
                            if c:
                                cleaned_main_raw.append(c)
                        continue
                c = clean_player_name(part)
                if c:
                    cleaned_main_raw.append(c)
        else:
            raw_tokens = SPLIT_PATTERN.split(cleaned_line)
            for token in raw_tokens:
                cleaned = clean_player_name(token)
                if cleaned:
                    cleaned_main_raw.append(cleaned)

    # 過濾不合理的長句子，保留真實球友名稱
    cleaned_main_raw = [p for p in cleaned_main_raw if is_plausible_player_name(p)]
    cleaned_waitlist_raw = [p for p in cleaned_waitlist_raw if is_plausible_player_name(p)]

    # 處理正選名單重複名稱 (例如出現兩位 lulu 時標記為 lulu(1), lulu(2))
    name_counts = {}
    for p in cleaned_main_raw:
        name_counts[p] = name_counts.get(p, 0) + 1

    players = []
    seen = {}
    for p in cleaned_main_raw:
        if name_counts[p] > 1:
            seen[p] = seen.get(p, 0) + 1
            players.append(f"{p}({seen[p]})")
        else:
            players.append(p)

    # 處理候補名單
    waitlist = []
    for p in cleaned_waitlist_raw:
        waitlist.append(p)

    # 第二層後備 (Hybrid Fallback): 若規則解析未滿 4 人，且輸入內容具有開團文特徵，嘗試啟用 AI 語意解析
    if len(players) < DEFAULT_COURT_SIZE and mode != "help" and len(raw_text) >= 20:
        if re.search(r"匹克|打球|報名|接龍|臨打|開團|球友", raw_text):
            try:
                ai_data = extract_players_with_ai(raw_text)
                if ai_data and len(ai_data.get("players", [])) >= DEFAULT_COURT_SIZE:
                    players = ai_data["players"]
                    if not court_limit and ai_data.get("court_count"):
                        court_limit = ai_data["court_count"]
                    if not waitlist and ai_data.get("waitlist"):
                        waitlist = ai_data["waitlist"]
            except Exception as e:
                print(f"[警告] AI 後備解析失敗: {e}", flush=True)

    return players, court_limit, rounds, group_count, per_group, mode, waitlist


def schedule_multiple_rounds(
    players: List[str],
    actual_courts: int,
    rounds: int,
    waitlist: Optional[List[str]] = None,
) -> Dict:
    """安排多輪公平輪替雙打賽程。"""
    total = len(players)
    capacity = actual_courts * DEFAULT_COURT_SIZE
    play_counts = {p: 0 for p in players}

    schedule = []

    for r in range(rounds):
        counts_map: Dict[int, List[str]] = {}
        for p in players:
            c = play_counts[p]
            counts_map.setdefault(c, []).append(p)

        sorted_counts = sorted(counts_map.keys())
        candidate_pool = []
        for c in sorted_counts:
            bucket = list(counts_map[c])
            random.shuffle(bucket)
            candidate_pool.extend(bucket)

        active_players = candidate_pool[:capacity]
        resting_players = candidate_pool[capacity:]

        for p in active_players:
            play_counts[p] += 1

        shuffled_active = list(active_players)
        random.shuffle(shuffled_active)

        round_courts = []
        for c_idx in range(actual_courts):
            start = c_idx * DEFAULT_COURT_SIZE
            court_members = shuffled_active[start:start + DEFAULT_COURT_SIZE]
            round_courts.append({
                "court_index": c_idx + 1,
                "team_a": court_members[:DEFAULT_TEAM_SIZE],
                "team_b": court_members[DEFAULT_TEAM_SIZE:],
            })

        schedule.append({
            "round_index": r + 1,
            "courts": round_courts,
            "resting": resting_players,
        })

    return {
        "status": "ok",
        "mode": "multi_round",
        "total_players": total,
        "court_count": actual_courts,
        "rounds": rounds,
        "schedule": schedule,
        "play_counts": play_counts,
        "players": players,
        "waitlist": waitlist or [],
    }


def random_group(
    players: List[str],
    court_limit: Optional[int] = None,
    rounds: Optional[int] = None,
    group_count: Optional[int] = None,
    per_group: Optional[int] = None,
    mode: str = "doubles",
    waitlist: Optional[List[str]] = None,
) -> Dict:
    """對球友名單進行打亂洗牌與嚴格雙打場地分組 (支援單輪與多輪排程)。"""
    total = len(players)
    if total == 0:
        return {
            "status": "empty",
            "mode": mode,
            "total_players": 0,
            "courts": [],
            "groups": [],
            "waiting": [],
            "players": [],
            "waitlist": waitlist or [],
        }

    # 1. 依指定組數分組 (通用分組)
    if mode == "by_count":
        shuffled = list(players)
        random.shuffle(shuffled)
        actual_group_count = min(max(1, group_count or 2), total)
        groups = [[] for _ in range(actual_group_count)]
        for i, player in enumerate(shuffled):
            groups[i % actual_group_count].append(player)

        return {
            "status": "ok",
            "mode": "by_count",
            "total_players": total,
            "courts": [],
            "groups": [
                {"group_index": idx + 1, "members": members}
                for idx, members in enumerate(groups)
            ],
            "waiting": [],
            "players": shuffled,
            "waitlist": waitlist or [],
        }

    # 2. 依每組人數分組 (通用分組)
    if mode == "by_size":
        shuffled = list(players)
        random.shuffle(shuffled)
        size = max(1, per_group or DEFAULT_TEAM_SIZE)
        groups = []
        waiting = []
        for i in range(0, total, size):
            chunk = shuffled[i:i + size]
            if len(chunk) == size:
                groups.append({
                    "group_index": len(groups) + 1,
                    "members": chunk,
                })
            else:
                waiting = chunk

        return {
            "status": "ok",
            "mode": "by_size",
            "total_players": total,
            "courts": [],
            "groups": groups,
            "waiting": waiting,
            "players": shuffled,
            "waitlist": waitlist or [],
        }

    # 3. 嚴格雙打模式 (doubles)
    if total < DEFAULT_COURT_SIZE:
        return {
            "status": "not_enough_players",
            "mode": "doubles",
            "total_players": total,
            "needed_players": DEFAULT_COURT_SIZE - total,
            "courts": [],
            "groups": [],
            "waiting": [],
            "players": players,
            "waitlist": waitlist or [],
        }

    max_courts = total // DEFAULT_COURT_SIZE
    if court_limit and court_limit > 0:
        actual_courts = min(max_courts, court_limit)
    else:
        # 智慧常態預設：接近 8 人 1 面場、接近 16 人 2 面場
        actual_courts = get_heuristic_court_count(total)

    if rounds and rounds > 1:
        return schedule_multiple_rounds(
            players=players,
            actual_courts=actual_courts,
            rounds=rounds,
            waitlist=waitlist,
        )

    # 單輪雙打分組
    shuffled = list(players)
    random.shuffle(shuffled)

    courts = []
    used_player_count = actual_courts * DEFAULT_COURT_SIZE
    active_players = shuffled[:used_player_count]
    waiting_players = shuffled[used_player_count:]

    for c in range(actual_courts):
        start = c * DEFAULT_COURT_SIZE
        court_members = active_players[start:start + DEFAULT_COURT_SIZE]
        courts.append({
            "court_index": c + 1,
            "team_a": court_members[:DEFAULT_TEAM_SIZE],
            "team_b": court_members[DEFAULT_TEAM_SIZE:],
        })

    return {
        "status": "ok",
        "mode": "doubles",
        "total_players": total,
        "court_count": actual_courts,
        "courts": courts,
        "groups": [],
        "waiting": waiting_players,
        "players": shuffled,
        "waitlist": waitlist or [],
    }


def format_group_result(result: Dict) -> str:
    """將分組結果格式化為符合規範的繁體中文純文字 (嚴禁使用 Emoji)。"""
    status = result.get("status", "ok")
    total = result.get("total_players", 0)
    waitlist = result.get("waitlist", [])

    if status == "empty" or total == 0:
        return "名單中未偵測到有效球友名稱，請重新輸入。\n\n" + GROUPING_HELP_TEXT

    # 人數不足 4 人提示
    if status == "not_enough_players":
        needed = result.get("needed_players", 4 - total)
        players = result.get("players", [])
        player_lines = "\n".join([f"- {name}" for name in players])
        output_parts = [
            "[匹克球隨機分組結果]",
            f"參加總人數: {total} 人",
            "-" * 24,
            "目前人數不足以組成標準雙打比賽 (每場需 4 人，每隊固定 2 人)。",
            f"名單中共有 {total} 位球友:",
            player_lines,
            "",
            f"請再找至少 {needed} 位球友即可成場！",
            "-" * 24,
        ]
        if waitlist:
            output_parts.append(f"[活動候補名單] ({len(waitlist)} 人)")
            output_parts.append("  " + ", ".join(waitlist))
            output_parts.append("-" * 24)
        return "\n".join(output_parts).strip()

    mode = result.get("mode", "doubles")

    # 多輪賽程排版
    if mode == "multi_round":
        court_count = result.get("court_count", 1)
        rounds = result.get("rounds", 1)
        schedule = result.get("schedule", [])
        play_counts = result.get("play_counts", {})

        lines = [
            "[匹克球隨機多輪賽程]",
            f"正選人數: {total} 人 | 場地數: {court_count} 面 | 總輪數: {rounds} 輪",
            "=" * 24,
        ]

        for round_item in schedule:
            r_idx = round_item["round_index"]
            lines.append(f"[第 {r_idx} 輪 (Round {r_idx})]")

            for court in round_item["courts"]:
                c_idx = court["court_index"]
                team_a = ", ".join(court["team_a"])
                team_b = ", ".join(court["team_b"])
                lines.append(f"場地 {c_idx}:")
                lines.append(f"  隊伍 A: {team_a}")
                lines.append("  VS")
                lines.append(f"  隊伍 B: {team_b}")

            resting = round_item.get("resting", [])
            if resting:
                resting_names = ", ".join(resting)
                lines.append(f"本輪休息 ({len(resting)} 人):")
                lines.append(f"  {resting_names}")

            lines.append("-" * 24)

        # 出賽統計
        lines.append("[出賽次數統計]")
        unique_counts = set(play_counts.values())
        if len(unique_counts) == 1:
            common_count = list(unique_counts)[0]
            lines.append(f"全員出賽次數均為 {common_count} 次 (完全公平)")
        else:
            summary_parts = []
            for p, cnt in play_counts.items():
                summary_parts.append(f"{p}: {cnt}次")
            lines.append(", ".join(summary_parts))

        if waitlist:
            lines.append("-" * 24)
            lines.append(f"[活動候補名單] ({len(waitlist)} 人)")
            lines.append("  " + ", ".join(waitlist))

        lines.append("=" * 24)
        return "\n".join(lines).strip()

    # 單輪雙打排版
    lines = [
        "[匹克球隨機分組結果]",
        f"正選總人數: {total} 人",
    ]

    if mode == "doubles":
        courts = result.get("courts", [])
        waiting = result.get("waiting", [])
        court_count = len(courts)

        lines.append(f"使用場地數: {court_count} 面")
        lines.append("-" * 24)

        for court in courts:
            idx = court["court_index"]
            team_a = ", ".join(court["team_a"])
            team_b = ", ".join(court["team_b"])
            lines.append(f"[第 {idx} 場地]")
            lines.append(f"  隊伍 A: {team_a}")
            lines.append("  VS")
            lines.append(f"  隊伍 B: {team_b}")
            lines.append("")

        if waiting:
            waiting_names = ", ".join(waiting)
            lines.append(f"[輪空 / 候補] ({len(waiting)} 人)")
            lines.append(f"  {waiting_names}")
            lines.append("")

    elif mode in ["by_count", "by_size"]:
        lines.append("-" * 24)
        groups = result.get("groups", [])
        waiting = result.get("waiting", [])

        for group in groups:
            idx = group["group_index"]
            members = ", ".join(group["members"])
            lines.append(f"[第 {idx} 組] ({len(group['members'])} 人)")
            lines.append(f"  {members}")
            lines.append("")

        if waiting:
            waiting_names = ", ".join(waiting)
            lines.append(f"[候補 / 未滿組] ({len(waiting)} 人)")
            lines.append(f"  {waiting_names}")
            lines.append("")

    if waitlist:
        lines.append(f"[活動候補名單] ({len(waitlist)} 人)")
        lines.append("  " + ", ".join(waitlist))
        lines.append("")

    lines.append("-" * 24)
    return "\n".join(lines).strip()
