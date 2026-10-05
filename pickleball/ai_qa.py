"""匹克球 (Pickleball) 專屬 AI 問答模組。

使用 Google Gemini 模型提供匹克球規則、技巧、裝備與賽事等專業諮詢。
整合本地主流球拍知識庫 (paddles_data.json) 與 Google Search Grounding 聯網能力。
嚴格限定僅回答匹克球相關問題，非匹克球問題一律禮貌拒答。
回答必須為通順完整的繁體中文句子。
"""

import json
import os
from typing import Optional
from google import genai
from google.genai import types
from config import gemini_api_key

_client: Optional[genai.Client] = None

REJECTION_MESSAGE = "我是匹克球小幫手，僅回答匹克球相關問題喔！"

PADDLES_DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")


def _get_paddles_summary() -> str:
    """載入球拍資料庫並轉換為 AI 參考摘要。"""
    if not os.path.exists(PADDLES_DATA_FILE):
        return ""
    try:
        with open(PADDLES_DATA_FILE, "r", encoding="utf-8") as f:
            paddles = json.load(f)
        lines = []
        for p in paddles:
            name = p.get("name", "")
            brand = p.get("brand", "")
            price = p.get("price_ntd", 0)
            thickness = p.get("thickness", "")
            shape = p.get("shape", "")
            surface = p.get("surface", "")
            desc = p.get("description", "")
            lines.append(
                f"- 【{brand}】{name} (市價約 NT$ {price:,})：厚度 {thickness}、{shape}、{surface}。特點：{desc}"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[警告] 讀取球拍知識庫失敗: {e}", flush=True)
        return ""


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
    """呼叫 Gemini 進行匹克球專業問答與球拍推薦。

    - 若問題與匹克球無關，傳回固定拒答文字。
    - 若為匹克球問題，傳回通順完整的繁體中文解答。
    - 結合主流球拍知識庫，具備 Google Search 聯網與自動備援機制。
    """
    clean_q = (question or "").strip()
    if not clean_q:
        return "請在指令後方輸入問題，例如：!ai 匹克球發球規則是什麼？ 或 !ai 推薦4000元內的控球拍"

    client = _get_genai_client()
    if not client:
        return "抱歉，目前 AI 服務尚未設定 API 金鑰或暫時無法連線，請稍後再試。"

    paddles_kb = _get_paddles_summary()
    if not paddles_kb:
        paddles_kb = "（目前本地資料庫暫無資料，請依您的內建知識庫回答）"
    else:
        paddles_kb = f"【台灣市售熱門球拍知識庫（即時庫存動態產生）】\n{paddles_kb}"

    system_instruction = (
        "你是專業的匹克球小幫手與球具教練。你的任務是解答使用者的【匹克球 (Pickleball)】相關問題。\n\n"
        "【嚴格準則】\n"
        "1. 主題檢查：請先判斷問題是否與匹克球（規則、發球、非截擊區/廚房區、計分、站位、打法技巧、球拍與球、球場、DUPR、賽制等）密切相關。若使用者僅輸入簡短名詞（如：長丁克、ATP、Erne、過渡球），請一律預設為匹克球術語並給予解釋，切勿輕易拒答。\n"
        "2. 嚴格拒答非匹克球主題：若問題與匹克球毫無關聯（例如日常閒聊、天氣、其他運動、程式設計、常識、歷史等），你必須且只能完全原樣回覆以下這句話：\n"
        "「我是匹克球小幫手，僅回答匹克球相關問題喔！」\n"
        "不得回答任何非匹克球內容，亦不可加油添醋。\n"
        "3. 球拍推薦與分析規範：\n"
        "   - 若使用者詢問球拍推薦、評估、選購或某款球拍的優缺點，請優先參考下方給予的動態知識庫，並以新台幣 (NT$) 報價與分析：\n"
        f"{paddles_kb}\n"
        "   - 若詢問不在清單內的球拍，請依據匹克球通用知識與科技（如 16mm 重控球/減震、14mm 重彈速/力量、生碳纖維 T700 重咬球旋轉）給予專業客觀的優缺點分析。\n"
        "   - 「唯有」當使用者明確在詢問「買球拍、挑選球拍、推薦球拍」等選購問題時，才可在文末加上：「亦可輸入【!選球拍】啟動兩步速配問卷，直接查看球拍照片與比價連結！」。若詢問技術、戰術或規則等非選購問題，絕對「不要」加上這句話。\n"
        "4. 句子完整性：回答必須是【文意通順、表達完整且語意清晰的繁體中文句子】，嚴格禁止出現中途腰斬或殘缺字詞。\n"
        "5. 回答長度與風格：請用約 2 至 4 句簡短段落說明重點，避免為湊字數而冗贅，兼顧精準度與專業度。\n"
        "6. 影片搜尋標記（非常重要）：若使用者詢問特定【打法、技術或球路】（例如：短丁/Dink、抽球/Drive、過渡球/Drop、挑高球/Lob、截擊/Volley、ATP、Erne、Bert 等），請務必在回答的最後（新起一行）加上：\n"
        "[VIDEO_QUERY]匹克球 {您判斷的球路中英文名稱} 教學\n"
        "（例如：[VIDEO_QUERY]匹克球 短丁 Dink 教學）。若非技術球路問題（如規則、選購），請不要加上此標記。\n"
        "7. 知識正確性與禁止幻覺：你必須確保回答的匹克球知識完全正確，特別是球場的空間地理關係。請牢記：廚房區 (NVZ) 僅佔網前 7 呎，而底線 (Baseline) 距離網子高達 22 呎。解釋落點時絕對不可產生矛盾（例如：『廚房區的較深處』絕不可能『靠近底線』）。請依據事實嚴謹回答，切勿胡亂聯想。"
    )

    models_to_try = ["gemini-3.5-flash-lite", "gemini-2.5-flash"]
    last_err = None

    # 嘗試策略：優先使用 Google Search Grounding，若失敗則降級為無工具純文本
    configs_to_try = [
        # 1. 帶 Google Search 聯網
        types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            max_output_tokens=800,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
        # 2. 備援：純知識庫生成 (無聯網工具，避免權限或配額問題)
        types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            max_output_tokens=800,
        ),
    ]

    for model_name in models_to_try:
        for gen_config in configs_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=clean_q,
                    config=gen_config,
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                last_err = e
                # 換下一個 config 或 model 嘗試
                continue

    print(f"[錯誤] 所有 AI 模型與設定呼叫皆失敗: {last_err}", flush=True)
    return "抱歉，AI 服務連線異常，請稍後再試。"
