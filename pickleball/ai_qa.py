"""匹克球 (Pickleball) 專屬 AI 問答模組。

使用 Google Gemini 模型提供匹克球規則、技巧、裝備與賽事等專業諮詢。
嚴格限定僅回答匹克球相關問題，非匹克球問題一律禮貌拒答，且回覆文字精簡在 50 字以內。
"""

from typing import Optional
from google import genai
from google.genai import types
from config import gemini_api_key

_client: Optional[genai.Client] = None

REJECTION_MESSAGE = "我是匹克球小幫手，僅回答匹克球相關問題喔！"


def _get_genai_client() -> Optional[genai.Client]:
    """取得或初始化 Gemini Client。"""
    global _client
    if _client is None and gemini_api_key:
        try:
            _client = genai.Client(api_key=gemini_api_key)
        except Exception as e:
            print(f"[警告] 初始化 Gemini Client 失敗: {e}", flush=True)
            return None
    return _client


def ask_pickleball_ai(question: str) -> str:
    """呼叫 Gemini 進行匹克球專業問答。

    - 若問題與匹克球無關，傳回固定拒答文字。
    - 若為匹克球問題，傳回 50 字以內的極簡精準解答。
    """
    clean_q = (question or "").strip()
    if not clean_q:
        return "請在指令後方輸入問題，例如：!ai 匹克球發球規則是什麼？"

    client = _get_genai_client()
    if not client:
        return "抱歉，目前 AI 服務尚未設定 API 金鑰或暫時無法連線，請稍後再試。"

    system_instruction = (
        "你是專業的匹克球小幫手。你的任務是解答使用者的【匹克球 (Pickleball)】相關問題。\n"
        "【嚴格準則】\n"
        "1. 主題檢查：請先判斷問題是否與匹克球（規則、發球、非截擊區/廚房區、計分、站位、打法技巧、球拍與球、球場、DUPR、賽制等）密切相關。\n"
        f"2. 嚴格拒答非匹克球主題：若問題與匹克球無關（例如日常閒聊、天氣、其他運動、程式設計、常識、歷史等），你必須且只能完全原樣回覆：\n"
        f"{REJECTION_MESSAGE}\n"
        "不得回答任何非匹克球內容，亦不可加油添醋。\n"
        "3. 字數與風格：若是匹克球相關問題，請以【繁體中文】回答，文字務必【極致精簡、一針見血、字數在 50 字以內】。\n"
        "4. 嚴格禁止長篇大論，直接給出核心答案。"
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=clean_q,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=150,
            ),
        )

        if not response or not response.text:
            return "抱歉，AI 暫時無法產生回答，請稍後再試。"

        answer = response.text.strip()
        return answer
    except Exception as e:
        print(f"[警告] AI 問答呼叫失敗: {e}", flush=True)
        return "抱歉，AI 服務連線異常，請稍後再試。"
