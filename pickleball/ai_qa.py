import json
import os
from typing import Optional
from google import genai
from google.genai import types
from config import gemini_api_key  # 保留你原始的 key 引入規則

_client: Optional[genai.Client] = None

REJECTION_MESSAGE = "我是匹克球小幫手，僅回答匹克球相關問題喔！"

PADDLES_DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

# 出現這些字詞即可確定是匹克球問題（全部小寫比對）
PICKLEBALL_KEYWORDS = (
    "匹克球", "皮克球", "匹克", "pickleball", "pickle ball",
    "dupr", "丁克", "dink", "廚房區", "非截擊區", "nvz", "erne",
    "atp", "around the post", "stack", "疊打", "nasty nelson", "third shot drop"
)


def _is_obviously_pickleball(question: str) -> bool:
    q = question.replace("關於匹克球，請告訴我：", "").lower()
    return any(kw in q for kw in PICKLEBALL_KEYWORDS)


def _is_rejection(text: str) -> bool:
    return "僅回答匹克球相關問題" in text


PADDLE_KEYWORDS = ("拍", "paddle", "mm", "碳纖", "玻纖", "玻璃纖維", "克維拉", "kevlar", "t700")
_paddle_brands: Optional[set] = None


def _needs_paddle_kb(question: str) -> bool:
    global _paddle_brands
    q = question.lower()
    if any(kw in q for kw in PADDLE_KEYWORDS):
        return True
    if _paddle_brands is None:
        try:
            with open(PADDLES_DATA_FILE, "r", encoding="utf-8") as f:
                _paddle_brands = {
                    p.get("brand", "").strip().lower()
                    for p in json.load(f)
                    if len(p.get("brand", "").strip()) >= 3
                }
        except Exception:
            _paddle_brands = set()
    return any(b in q for b in _paddle_brands)


def _get_paddles_summary() -> str:
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
                f"- 【{brand}】{name} (約 NT$ {price:,})：{thickness}、{shape}、{surface}。特點：{desc}"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[警告] 讀取球拍知識庫失敗: {e}", flush=True)
        return ""


def _get_genai_client() -> Optional[genai.Client]:
    global _client
    if _client is None and gemini_api_key:
        try:
            _client = genai.Client(api_key=gemini_api_key)
        except Exception as e:
            print(f"[警告] 初始化 Gemini Client 失敗: {e}", flush=True)
            return None
    return _client


def ask_pickleball_ai(question: str) -> str:
    clean_q = (question or "").strip()
    if not clean_q:
        return "請在指令後方輸入問題，例如：!ai 匹克球發球規則是什麼？"

    client = _get_genai_client()
    if not client:
        return "抱歉，目前 AI 服務暫時無法連線。"

    if _needs_paddle_kb(clean_q):
        paddles_kb = _get_paddles_summary()
        paddles_kb = f"【本地球拍知識庫】\n{paddles_kb}" if paddles_kb else "（目前本地資料庫暫無資料）"
    else:
        paddles_kb = "（本題未附球拍知識庫）"

    # --- 這裡是你要求的 100+ 情境優化 Instruction ---
    system_instruction = (
        "# Role: 專業匹克球教練與球具顧問\n\n"
        "## 1. 核心任務與範圍 (Scope)\n"
        "你只解答【匹克球 (Pickleball)】相關問題。包含：規則計分、技術戰術 (Dink/Drive/Drop/Erne/ATP等)、"
        "裝備選購 (球拍/球/鞋/加重貼)、DUPR 等級、賽事、場地尺寸、運動傷害預防、與網球/羽球的比較。\n"
        "【拒答準則】：若問題與匹克球完全無關（如天氣、股票、代碼），必須原樣回覆：「我是匹克球小幫手，僅回答匹克球相關問題喔！」且不得有任何額外字句。\n\n"
        "## 2. 專業知識規範 (Strict Knowledge Rules)\n"
        "- **場地防錯**：非截擊區 (NVZ/廚房區) 距離網子 **7 呎**。底線距離網子 **22 呎**。丁克球 (Dink) 的落點必定在「廚房線」附近，絕對不可描述為靠近「底線」。\n"
        "- **球拍科技分析**：\n"
        "  - 16mm：控球型 (Control)、減震佳。\n"
        "  - 14mm/13mm：力量型 (Power)、彈速快。\n"
        "  - 材質：T700 生碳纖維重旋轉；Kevlar 重甜區穩定度。\n"
        "- **報價**：所有價格請以 **NT$ (新台幣)** 呈現。\n\n"
        "## 3. 輸出引導標記 (Special Tags)\n"
        "- **[VIDEO_QUERY] 標記**：只要問題涉及「擊球動作、技術、球路、戰術」，請在回答最後一行加上：\n"
        "  `[VIDEO_QUERY]匹克球 {技術名稱} 教學`（例如：[VIDEO_QUERY]匹克球 Erne 教學）。規則或裝備類問題嚴禁加上此標記。\n"
        "- **[!選球拍] 標記**：當使用者明確在詢問「買哪把拍子、推薦球拍、如何挑選」時，才在文末加上：「亦可輸入【!選球拍】啟動兩步速配問卷，直接查看球拍照片與比價連結！」。\n\n"
        "## 4. 語意風格\n"
        "- 回答必須為【繁體中文】，語氣專業親切。\n"
        "- 結構清晰，使用 2-4 個簡短段落，關鍵字用 **粗體** 強調。\n\n"
        f"## 5. 參考背景資料 (Context)\n{paddles_kb}"
    )

    models_to_try = ["gemini-2.0-flash", "gemini-1.5-flash"]
    last_err = None

    obviously_related = _is_obviously_pickleball(clean_q)
    contents = (
        f"（此問題與匹克球相關，請專業回答，不可拒答）\n使用者問題：{clean_q}"
        if obviously_related
        else clean_q
    )

    for model_name in models_to_try:
        # 優先嘗試帶 Search 的 Config
        configs_to_try = [
            types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
                max_output_tokens=800,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
            types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
                max_output_tokens=800,
            ),
        ]

        for gen_config in configs_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )
                if response and response.text:
                    text = response.text.strip()
                    if obviously_related and _is_rejection(text):
                        continue
                    return text
            except Exception as e:
                last_err = e
                continue

    return "抱歉，目前 AI 服務暫時無法正確回應，請換個方式詢問或稍後再試。"