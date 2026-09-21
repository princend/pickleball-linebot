"""匹克球名單快取管理模組。

將每個聊天室 (Group / Room) 或個人的最新球友名單暫存於記憶體快取中 (預設有效時間 60 分鐘)。
讓球友在打完一輪後，可直接透過按鈕或指令進行一鍵重新洗牌或切換多輪賽程，無需重複複製貼上名單。
"""

import time
from typing import Any, Dict, List, Optional

# 快取有效期限：3600 秒 (60 分鐘)
SESSION_EXPIRATION_SECONDS = 3600

# 記憶體快取結構: { target_id: { "players": [...], "court_limit": int, "waitlist": [...], "timestamp": float } }
_PICKLEBALL_SESSIONS: Dict[str, Dict] = {}


def save_pickleball_session(
    target_id: str,
    players: List[str],
    court_limit: Optional[int] = None,
    waitlist: Optional[List[str]] = None,
    last_result: Optional[Dict] = None,
) -> None:
    """儲存或更新當前聊天室的匹克球名單快取。"""
    if not target_id:
        return

    _PICKLEBALL_SESSIONS[target_id] = {
        "players": list(players),
        "court_limit": court_limit,
        "waitlist": list(waitlist) if waitlist else [],
        "last_result": last_result,
        "timestamp": time.time(),
    }


def get_pickleball_session(target_id: str) -> Optional[Dict]:
    """取得當前聊天室的匹克球名單快取。若超過有效期限則自動清除並傳回 None。"""
    if not target_id or target_id not in _PICKLEBALL_SESSIONS:
        return None

    session = _PICKLEBALL_SESSIONS[target_id]
    elapsed = time.time() - session.get("timestamp", 0)

    if elapsed > SESSION_EXPIRATION_SECONDS:
        del _PICKLEBALL_SESSIONS[target_id]
        return None

    return session


def clear_pickleball_session(target_id: str) -> bool:
    """清除當前聊天室的匹克球名單快取。"""
    if target_id in _PICKLEBALL_SESSIONS:
        del _PICKLEBALL_SESSIONS[target_id]
        return True
    return False


def remove_player_and_promote(target_id: str, player_name: str) -> Optional[Dict]:
    """從快取正選名單中移除指定球友，並自動從候補名單遞補第一位。

    傳回:
        dict 包含以下欄位：
        - "removed": 被移除的球友名字 (str)
        - "promoted": 遞補上來的候補名字 (str 或 None，無候補時為 None)
        - "players": 更新後的正選名單 (List[str])
        - "waitlist": 更新後的候補名單 (List[str])
        - "court_limit": 原快取場地數 (int 或 None)
        若快取不存在或找不到指定球友，傳回 None。
    """
    session = get_pickleball_session(target_id)
    if not session:
        return None

    players = list(session.get("players", []))
    waitlist = list(session.get("waitlist", []))
    court_limit = session.get("court_limit")

    # 嘗試移除球友 (完全比對)
    if player_name not in players:
        return None

    players.remove(player_name)

    # 從候補遞補
    promoted = None
    if waitlist:
        promoted = waitlist.pop(0)
        players.append(promoted)

    # 更新快取
    save_pickleball_session(
        target_id=target_id,
        players=players,
        court_limit=court_limit,
        waitlist=waitlist,
        last_result=None,
    )

    return {
        "removed": player_name,
        "promoted": promoted,
        "players": players,
        "waitlist": waitlist,
        "court_limit": court_limit,
    }


# 等待輸入開團文狀態管理: { target_id: timestamp }
_AWAITING_PICKLEBALL_INPUT: Dict[str, float] = {}
AWAITING_INPUT_EXPIRATION_SECONDS = 600  # 10 分鐘有效


def set_awaiting_pickleball_input(target_id: str) -> None:
    """設定當前聊天室處於等待輸入開團文或名單之狀態。"""
    if target_id:
        _AWAITING_PICKLEBALL_INPUT[target_id] = time.time()


def is_awaiting_pickleball_input(target_id: str) -> bool:
    """檢查當前聊天室是否處於等待輸入開團文之狀態 (超時自動失效)。"""
    if not target_id or target_id not in _AWAITING_PICKLEBALL_INPUT:
        return False

    elapsed = time.time() - _AWAITING_PICKLEBALL_INPUT[target_id]
    if elapsed > AWAITING_INPUT_EXPIRATION_SECONDS:
        del _AWAITING_PICKLEBALL_INPUT[target_id]
        return False

    return True


def clear_awaiting_pickleball_input(target_id: str) -> bool:
    """清除當前聊天室等待輸入開團文之狀態。"""
    if target_id in _AWAITING_PICKLEBALL_INPUT:
        del _AWAITING_PICKLEBALL_INPUT[target_id]
        return True
    return False


# 開團對話步驟狀態管理: { target_id: { "step": str, "data": dict, "timestamp": float } }
_GROUP_CREATION_SESSIONS: Dict[str, Dict[str, Any]] = {}
GROUP_CREATION_EXPIRATION_SECONDS = 600  # 10 分鐘有效


def set_group_creation_session(target_id: str, session_data: Dict[str, Any]) -> None:
    """儲存或更新當前聊天室或使用者的開團精靈會話資料。"""
    if target_id:
        session_data["timestamp"] = time.time()
        _GROUP_CREATION_SESSIONS[target_id] = session_data


def get_group_creation_session(target_id: str) -> Optional[Dict[str, Any]]:
    """取得當前聊天室或使用者的開團精靈會話資料。超時自動清除並傳回 None。"""
    if not target_id or target_id not in _GROUP_CREATION_SESSIONS:
        return None

    session = _GROUP_CREATION_SESSIONS[target_id]
    elapsed = time.time() - session.get("timestamp", 0)
    if elapsed > GROUP_CREATION_EXPIRATION_SECONDS:
        del _GROUP_CREATION_SESSIONS[target_id]
        return None

    return session


def clear_group_creation_session(target_id: str) -> bool:
    """清除當前聊天室或使用者的開團精靈會話。"""
    if target_id in _GROUP_CREATION_SESSIONS:
        del _GROUP_CREATION_SESSIONS[target_id]
        return True
    return False
