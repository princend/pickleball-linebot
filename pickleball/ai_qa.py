"""匹克球 (Pickleball) 專屬 AI 問答模組。

使用 Google Gemini 模型提供匹克球規則、技巧、裝備與賽事等專業諮詢。
嚴格限定僅回答匹克球相關問題，非匹克球問題一律禮貌拒答。
回答必須為通順完整的繁體中文句子，避免語句斷裂。
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
    - 若為匹克球問題，傳回通順完整的簡明解答（約 1~3 句完整話）。
    - 優先使用 gemini-3.8-flash 模型，並具備自動備援機制。
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
        "3. 句子完整性：回答必須是【文意通順、表達完整且語意清晰的繁體中文句子】，嚴格禁止出現中途腰斬、殘缺字詞、單一字母或不明斷句（例如切勿只輸出半截的字詞）。\n"
        "4. 回答長度與風格：請用約 1 至 3 句完整句子說明核心重點（約 50 至 100 字左右），兼顧精簡與完整性，直接提供明確有用的指引。"
    )

    models_to_try = ["gemini-3.8-flash", "gemini-2.5-flash"]
    last_err = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=clean_q,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=300,
                ),
            )

            if response and response.text:
                return response.text.strip()
        except Exception as e:
            last_err = e
            print(f"[警告] 模型 {model_name} 呼叫失敗，嘗試備用模型: {e}", flush=True)

    print(f"[錯誤] 所有 AI 模型呼叫皆失敗: {last_err}", flush=True)
    return "抱歉，AI 服務連線異常，請稍後再試。"
