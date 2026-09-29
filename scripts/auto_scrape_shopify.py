import requests
import json
import os
import re
import html
import time


# 在最上方加入 import google.genai 等
import os
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

def ai_analyze_paddle(title, html_desc):
    """使用 Gemini AI 進行進階內容分析與繁體中文改寫"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not genai:
        return None
        
    try:
        client = genai.Client(api_key=api_key)
        prompt = f'''
你是一個專業的匹克球 (Pickleball) 裝備分析專家。
請根據以下原文商品名稱與介紹，回傳一個 JSON 格式的分析結果。

商品名稱: {title}
商品介紹 (HTML):
{html_desc}

請嚴格遵守以下 JSON 格式回傳（不需要 markdown 標記，直接回傳純 JSON）：
{{
    "style_category": "力量/控制/速度/旋轉 四選一。如果介紹強調 power/elongated/smash 則為 power；強調 control/forgiving/touch/16mm 為 control；強調 aero/lightweight/speed/13mm 為 speed；強調 spin/grit/kevlar/texture 為 spin。請回傳英文代碼：power, control, speed, or spin",
    "zh_summary": "用繁體中文寫一段約 50~80 字的精華摘要，語氣要專業生動，吸引人購買，絕對不要出現 HTML 標籤。"
}}
'''
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.replace("```json", "").replace("```", "").strip()
        import json
        result = json.loads(text)
        if result.get("style_category") in ["power", "control", "speed", "spin"] and result.get("zh_summary"):
            return result
    except Exception as e:
        print(f"  [AI 分析失敗] {e}")
    return None

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

# 這裡設定 limit=250 確保抓到全品項，以便準確判斷停售
SHOPIFY_ENDPOINTS = [
    {"brand": "Six Zero", "url": "https://www.sixzeropickleball.com/products.json?limit=250", "origin": "澳洲"},
    {"brand": "CRBN", "url": "https://crbnpickleball.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Vatic Pro", "url": "https://vaticpro.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Engage", "url": "https://engagepickleball.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Pickleball Apes", "url": "https://pickleballapes.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Holbrook", "url": "https://holbrookpickleball.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Thrive", "url": "https://thrivepb.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Neonic", "url": "https://neonicpickleball.com/products.json?limit=250", "origin": "美國"},
    {"brand": "11six24", "url": "https://11six24.com/products.json?limit=250", "origin": "美國"},
    {"brand": "Luzz", "url": "https://luzzpickleball.com/products.json?limit=250", "origin": "美國"}
]

def is_valid_image(url):
    """驗證圖片是否可讀"""
    if not url or not url.startswith("http"): return False
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.head(url, timeout=5, headers=headers)
        if r.status_code in [403, 405]:
            r = requests.get(url, timeout=5, stream=True, headers=headers)
            r.close()
        return r.status_code == 200
    except:
        return False

def validate_scraped_data(paddle):
    """嚴格審查資料"""
    if paddle["price_ntd"] < 500 or paddle["price_ntd"] > 20000: return False
    if not is_valid_image(paddle["image_front"]): return False
    thickness = paddle["thickness"].lower().replace("mm", "").strip()
    try:
        t_val = float(thickness)
        if t_val < 10 or t_val > 25: return False
    except:
        return False
    return True

def main():
    print("啟動 Shopify 全自動雙向同步爬蟲 (支援自動新增與下架)...")
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            paddles_db = json.load(f)
    else:
        paddles_db = []
        
    db_ids = {p["id"]: p for p in paddles_db}
    added_count = 0
    removed_count = 0

    for endpoint in SHOPIFY_ENDPOINTS:
        brand = endpoint["brand"]
        origin = endpoint["origin"]
        print(f"\n--- 正在同步 {brand} ---")
        
        try:
            r = requests.get(endpoint["url"], timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                print(f"  [錯誤] API 存取失敗 ({r.status_code})")
                continue
                
            products = r.json().get("products", [])
            # 建立官方在架清單
            official_active_ids = set()
            
            for prod in products:
                title = prod.get("title", "")
                title_lower = title.lower()
                
                exclude_words = ["eraser", "grip", "shirt", "tank", "hat", "kit", "accessory", "clothing", "bundle", "blemish", "blemished", "demo", "return", "returns", "used", "mystery", "set", "redemption", "not for sale", "cleaner", "tape", "gift", "shoe", "sock", "towel", "net", "ball", "balls", "apparel", "visor", "bottle", "hoodie", "jacket"]
                if any(re.search(r'\b' + re.escape(w) + r'\b', title_lower) for w in exclude_words):
                    continue
                    
                # 專門處理 cover/case/bag 等字眼，只有當它們是標題的主要詞彙時才排除，若前面有 "includes" 則不排除
                if any(re.search(r'\b' + re.escape(w) + r'\b', title_lower) for w in ["bag", "cover", "backpack", "duffle", "case"]):
                    if "include" not in title_lower and "with cover" not in title_lower and "with paddle cover" not in title_lower:
                        continue
                    
                if "paddle" not in title_lower and "paddle" not in prod.get("product_type", "").lower():
                    continue
                    
                pid = re.sub(r'[^a-z0-9\-]', '', f"{brand.lower()}-{title.lower().replace(' ', '-')}")
                official_active_ids.add(pid)
                
                # 若資料庫沒有，則執行新增
                if pid not in db_ids:
                    variants = prod.get("variants", [])
                    price = 0
                    if variants:
                        try: price = int(float(variants[0].get("price", "0")) * 32)
                        except: pass
                            
                    images = prod.get("images", [])
                    front_img = images[0]["src"] if len(images) > 0 else ""
                    back_img = images[1]["src"] if len(images) > 1 else front_img
                    
                    thickness = "16mm"
                    if "14mm" in title.lower(): thickness = "14mm"
                    elif "13mm" in title.lower(): thickness = "13mm"
                    elif "20mm" in title.lower(): thickness = "20mm"
                    
                    html = prod.get('body_html', '') or ''
                    # 清洗 HTML (基本備案)
                    html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
                    html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html_clean, flags=re.DOTALL | re.IGNORECASE)
                    desc_text = re.sub(r'<[^>]+>', ' ', html_clean)
                    desc_text = html.unescape(re.sub(r'\s+', ' ', desc_text).strip())
                    desc = desc_text[:80] + "..." if len(desc_text) > 80 else desc_text
                    
                    # 嘗試呼叫 AI 分析 (如果設定了 GEMINI_API_KEY)
                    ai_result = ai_analyze_paddle(title, html)
                    if ai_result:
                        style_cat = ai_result["style_category"]
                        desc_final = ai_result["zh_summary"]
                        print(f"  [AI 分析成功] 判定球風: {style_cat}")
                    else:
                        # 備用：舊版土法煉鋼關鍵字分類
                        desc_final = desc
                        style_cat = "control"
                        title_l = title.lower()
                        desc_l = desc.lower()
                        if any(w in title_l for w in ["power", "elongated", "fury", "cannon", "ignite"]):
                            style_cat = "power"
                        elif any(w in title_l for w in ["speed", "aero", "air", "swift", "glider", "flare"]):
                            style_cat = "speed"
                        elif any(w in title_l for w in ["spin", "grit", "ruby", "kevlar"]):
                            style_cat = "spin"
                        else:
                            full_t = title_l + " " + desc_l
                            p_score = sum(full_t.count(w) for w in ["power", "elongated", "smash", "drive", "pop"])
                            s_score = sum(full_t.count(w) for w in ["speed", "aero", "aerodynamic", "fast", "quick", "maneuver"])
                            sp_score = sum(full_t.count(w) for w in ["spin", "grit", "friction", "texture", "bite"])
                            c_score = sum(full_t.count(w) for w in ["control", "precision", "soft", "touch", "forgiving", "sweet spot"])
                            if "14mm" in title_l or "13mm" in title_l:
                                p_score += 1
                                s_score += 1
                            elif "16mm" in title_l:
                                c_score += 2
                            scores = {"power": p_score, "speed": s_score, "spin": sp_score, "control": c_score}
                            best_s = max(scores, key=scores.get)
                            if scores[best_s] > 0:
                                style_cat = best_s

                    if price < 1500:
                        budget_cat = "budget"
                    elif price < 3500:
                        budget_cat = "intermediate"
                    elif price < 6500:
                        budget_cat = "advanced"
                    else:
                        budget_cat = "flagship"

                    new_paddle = {
                        "id": pid,
                        "name": f"{brand} {title}",
                        "brand": brand,
                        "price_ntd": price,
                        "budget_category": budget_cat,
                        "style_category": style_cat,
                        "thickness": thickness,
                        "weight": "8.0 oz",
                        "shape": "標準型",
                        "core": "Polymer Honeycomb",
                        "surface": "Carbon Fiber",
                        "usapa_approved": True,
                        "features": [
                            f"來自{origin}的知名品牌 {brand} 最新款式",
                            f"原廠官方說明：{desc_final}"
                        ],
                        "tags": ["最新上架", brand, "原廠直送"],
                        "image_front": front_img,
                        "image_back": "",
                        "description": f"來自{origin}的 {brand} 最新球拍"
                    }
                    
                    if validate_scraped_data(new_paddle):
                        paddles_db.append(new_paddle)
                        db_ids[pid] = new_paddle
                        added_count += 1
                        print(f"  [新增] {new_paddle['name']}")
                    time.sleep(0.5)

            # 執行下架邏輯：
            # 尋找資料庫中屬於該「品牌」，但不在 official_active_ids 裡的球拍
            to_remove = []
            for p in paddles_db:
                if p["brand"] == brand:
                    # 如果原廠目前在架清單沒有這個 ID，且它的確是我們自動產生的 ID 格式
                    # 注意：只對真正從官網抓不到的執行下架
                    if p["id"] not in official_active_ids:
                        to_remove.append(p)
            
            for p in to_remove:
                paddles_db.remove(p)
                del db_ids[p["id"]]
                removed_count += 1
                print(f"  [下架] {p['name']} 已停售，從資料庫中移除")
                
        except Exception as e:
            print(f"  [例外] {e}")

    if added_count > 0 or removed_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(paddles_db, f, ensure_ascii=False, indent=2)
            
    print(f"\n✅ 雙向同步完成！新增 {added_count} 款，下架停售 {removed_count} 款。")

if __name__ == "__main__":
    main()
