"""匹克球開團文 AI 語意解析模組。

作為規則解析失效時的第二層後備 (Fallback) 機制。
使用 Gemini 模型將非標準或口語化的開團文結構化轉換為正選球友與候補名單。
"""

import json
import re
from typing import Dict, Optional
from google import genai
from google.genai import types
from config import gemini_api_key

_client: Optional[genai.Client] = None


def _get_genai_client() -> Optional[genai.Client]:
    global _client
    if _client is None and gemini_api_key:
        try:
            _client = genai.Client(api_key=gemini_api_key)
        except Exception as e:
            print(f"[警告] 初始化 Gemini Client 失敗: {e}", flush=True)
            return None
    return _client


def extract_players_with_ai(raw_text: str) -> Optional[Dict]:
    """呼叫 Gemini 進行開團文語意解析與球友名單提取。

    傳回字典格式:
    {
        "court_count": Optional[int],
        "players": List[str],
        "waitlist": List[str]
    }
    """
    client = _get_genai_client()
    if not client:
        return None

    prompt = f"""請從以下匹克球開團貼文中，準確提取報名資訊。
嚴格規則:
1. 提取所有確認參加的正選球友名稱，存入 "players" 陣列。
2. 提取候補或備取人員名稱，存入 "waitlist" 陣列。
3. 若文章中提及場地數量 (例如 一面場、2面)，將數字存入 "court_count"，未提及則為 null。
4. 排除時間、地點、費用、程度、規則與裝備等非人名資訊。
5. 嚴格禁止在輸出中包含任何表情符號 (Emoji)。
6. 必須輸出符合標準的 JSON，格式如下:
{{"court_count": 1, "players": ["名字1", "名字2"], "waitlist": ["候補1"]}}

待分析開團文:
{raw_text}"""

    response = None
    for model_name in ["gemini-3.8-flash", "gemini-2.5-flash"]:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            if response and response.text:
                break
        except Exception as e:
            print(f"[警告] 模型 {model_name} 呼叫失敗，嘗試備用模型: {e}", flush=True)

    if not response or not response.text:
        return None

        # 清理可能包含的 Markdown 標籤
        clean_json_str = re.sub(r"```json\s*|```\s*", "", response.text).strip()
        data = json.loads(clean_json_str)

        players = data.get("players", [])
        waitlist = data.get("waitlist", [])
        court_count = data.get("court_count")

        if isinstance(court_count, str) and court_count.isdigit():
            court_count = int(court_count)
        elif not isinstance(court_count, int):
            court_count = None

        return {
            "court_count": court_count,
            "players": [p.strip() for p in players if isinstance(p, str) and p.strip()],
            "waitlist": [w.strip() for w in waitlist if isinstance(w, str) and w.strip()],
        }
    except Exception as e:
        print(f"[警告] AI 開團文解析發生例外: {e}", flush=True)
        return None


def standardize_announcement_with_ai(raw_text: str) -> Optional[str]:
    """呼叫 Gemini 模型將各類非標準或口語化開團文，過濾並格式化為標準接龍清單。

    輸出格式:
    1.球友A
    2.球友B
    ...
    候補1.候補A
    候補2.候補B
    """
    client = _get_genai_client()
    if not client:
        return None

    prompt = f"""你是一個專業的活動開團文名單整理助手。請將以下開團貼文過濾並整理成純文字標準接龍清單。

嚴格規則:
1. 僅保留確認參加與報名的正選人員名單，每行一位，格式必須為:
1.球友姓名
2.球友姓名
3.球友姓名

2. 若開團文中有候補或備取人員，接續在正選之後，格式必須為:
候補1.候補姓名
候補2.候補姓名

3. 徹底剔除所有非人名之雜訊（例如：時間、地點、費用、匯款帳號、新手/程度標籤、已付款狀態、場館設施說明與其他備註等）。
4. 正確理解並處理口語化報名與取消（例如「小明+1」、「大雄帶朋友共2位」、「靜香臨時取消」請相應增減人員名單）。
5. 嚴格禁止輸出任何表情符號 (Emoji)。若球友暱稱為純表情符號或含有表情符號，請將其轉換為純文字中文（例如「小鳥」、「烏龜」）或以「球友編號」代稱。
6. 全文一律使用繁體中文。
7. 嚴格只輸出整理後的標準名單，不要輸出任何開頭說明、問候、Markdown 程式碼區塊標記 (如 ```) 或總結。

待處理開團文:
{raw_text}"""

    response = None
    for model_name in ["gemini-3.8-flash", "gemini-2.5-flash"]:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                ),
            )
            if response and response.text:
                break
        except Exception as e:
            print(f"[警告] 模型 {model_name} 呼叫失敗，嘗試備用模型: {e}", flush=True)

    if not response or not response.text:
        return None

        # 清除可能包裹的 Markdown 區塊與多餘空白
        cleaned_text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
        if not cleaned_text:
            return None

        return cleaned_text
    except Exception as e:
        print(f"[警告] AI 標準化開團文發生例外: {e}", flush=True)
        return None

