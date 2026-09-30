import requests
import json
import time
import os
import html
from bs4 import BeautifulSoup
from google import genai
import gspread
from google.oauth2.service_account import Credentials

# --- 設定 ---
SHEET_ID = "1Zphr-a547bmb0nTTNxz8p5A1dajAmLSOi-mO1NiRydw"

SHOPIFY_ENDPOINTS = [
    {"brand": "Selkirk", "url": "https://www.selkirk.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "JOOLA", "url": "https://joolausa.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Paddletek", "url": "https://www.paddletek.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Gearbox", "url": "https://gearboxsports.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Onix", "url": "https://onixpickleball.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Hudef", "url": "https://hudefsport.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Ronbus", "url": "https://www.ronbus.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Volair", "url": "https://www.volair.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Six Zero", "url": "https://www.sixzeropickleball.com/collections/paddles/products.json?limit=250"},
    {"brand": "CRBN", "url": "https://crbnpickleball.com/collections/pickleball-paddles/products.json?limit=250"},
    {"brand": "Engage", "url": "https://engagepickleball.com/collections/paddles/products.json?limit=250"},
    {"brand": "Pickleball Apes", "url": "https://www.pickleballapes.com/collections/all-paddles/products.json?limit=250"},
    {"brand": "Holbrook", "url": "https://holbrookpickleball.com/collections/paddles/products.json?limit=250"},
    {"brand": "Thrive", "url": "https://thrivepb.com/collections/all-paddles/products.json?limit=250"},
    {"brand": "Neonic", "url": "https://neonicpickleball.com/collections/all/products.json?limit=250"},
    {"brand": "11six24", "url": "https://11six24.com/collections/paddles/products.json?limit=250"},
    {"brand": "Luzz", "url": "https://luzzpickleball.com/collections/paddle/products.json?limit=250"},
]

def ai_analyze_paddle(title, desc_html):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    
    try:
        client = genai.Client(api_key=api_key)
        prompt = f'''
你是一位專業的匹克球(Pickleball)球拍評測專家。
請閱讀以下球拍名稱與官方英文介紹，判斷它的「球風分類」並寫出「繁體中文摘要」。

球拍名稱：{title}
官方介紹：
{desc_html}

請嚴格遵守以下 JSON 格式回傳（不需要 markdown 標記，直接回傳純 JSON）：
{{
    "style_category": "控制/力量/全面均衡 三選一。如果介紹強調 power/elongated/smash 則為 power；強調 control/forgiving/touch/16mm 為 control；如果是攻守兼備、主打全能、或是同時強調 spin(旋轉)與 speed(速度)，則為 all_around。請回傳英文代碼：control, power, or all_around",
    "zh_summary": "用繁體中文寫一段約 50~80 字的精華摘要，語氣要專業生動，吸引人購買，絕對不要出現 HTML 標籤。"
}}
'''
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        text = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        if result.get("style_category") in ["power", "control", "all_around"] and result.get("zh_summary"):
            return result
    except Exception as e:
        print(f"  [AI 分析失敗] {e}")
    return None

def strip_html_tags(html_str):
    if not html_str:
        return ""
    soup = BeautifulSoup(html_str, "html.parser")
    return html.unescape(soup.get_text(separator=" ", strip=True))

def main():
    print("啟動自動化爬蟲與 Google Sheets 寫入作業...")
    
    # 讀取 Google Sheets 憑證
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        print("[錯誤] 未設定 GOOGLE_CREDENTIALS 環境變數！")
        return
        
    try:
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
    except Exception as e:
        print(f"[錯誤] Google Sheets 驗證或連線失敗: {e}")
        return

    try:
        existing_ids = worksheet.col_values(1)[1:] # 第 1 欄是 ID，跳過標題
    except Exception as e:
        print(f"[錯誤] 讀取 Google Sheets 現有資料失敗: {e}")
        return
        
    print(f"目前 Google Sheets 中已有 {len(existing_ids)} 支球拍。")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    new_paddles_count = 0
    
    for endpoint in SHOPIFY_ENDPOINTS:
        brand = endpoint["brand"]
        url = endpoint["url"]
        origin = "澳洲" if brand == "Six Zero" else "美國"
        print(f"\n[{brand}] 正在掃描...")
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"  [失敗] 狀態碼 {resp.status_code}")
                continue
                
            data = resp.json()
            products = data.get("products", [])
            
            for prod in products:
                title = prod.get("title", "")
                handle = prod.get("handle", "")
                
                # 排除無關周邊 (嚴格過濾)
                title_lower = title.lower()
                exclude_words = ["cleaner", "tape", "gift", "demo", "return", "blemish", "shoe", "sock", "ball", "apparel", "hat", "cap", "bag", "backpack", "net", "overgrip", "eraser", "t-shirt", "bundle"]
                is_paddle = True
                for word in exclude_words:
                    if word in title_lower:
                        if word == "cover" and "includes paddle cover" in title_lower:
                            pass
                        elif word == "bag" and "sling bag" in title_lower:
                            is_paddle = False
                        elif "lead" in title_lower and "weights" in title_lower:
                            pass
                        else:
                            is_paddle = False
                            break
                if not is_paddle:
                    continue
                
                # 排除未含 paddle 且包含 clothing/accessory 的
                prod_type = prod.get("product_type", "").lower()
                if "paddle" not in prod_type and prod_type != "":
                    if "clothing" in prod_type or "accessory" in prod_type or "gear" in prod_type:
                        continue
                        
                pid = f"{brand.lower().replace(' ', '')}-{handle}"
                
                if pid in existing_ids:
                    continue
                    
                print(f"  [發現新球拍] {title}")
                
                # 取得價格 (抓取第一個 variant)
                variants = prod.get("variants", [])
                price = 0
                if variants:
                    try:
                        usd_price = float(variants[0].get("price", 0))
                        price = int(usd_price * 32)
                    except ValueError:
                        pass
                if price == 0:
                    continue
                    
                # 取得圖片
                images = prod.get("images", [])
                front_img = images[0].get("src", "") if len(images) > 0 else "https://raw.githubusercontent.com/princend/pickleball-linebot/main/data/images/no_image.png"
                
                # 取得說明
                desc_html = prod.get("body_html", "")
                desc = strip_html_tags(desc_html)
                
                # AI 分析
                ai_result = ai_analyze_paddle(title, desc_html)
                if ai_result:
                    style_cat = ai_result["style_category"]
                    desc_final = ai_result["zh_summary"]
                    print(f"    [AI 判定] 球風: {style_cat}")
                else:
                    print(f"    [舊版判定] 使用預設值")
                    desc_final = desc
                    style_cat = "all_around"

                budget_cat = "flagship"
                if price < 1500: budget_cat = "budget"
                elif price < 3500: budget_cat = "intermediate"
                elif price < 6500: budget_cat = "advanced"

                thickness = "16mm"
                if "14mm" in title.lower(): thickness = "14mm"
                elif "13mm" in title.lower(): thickness = "13mm"
                elif "11mm" in title.lower(): thickness = "11mm"

                # 準備寫入的 Row
                # 欄位順序: id, name, brand, price_ntd, budget_category, style_category, thickness, weight, shape, core, surface, usapa_approved, features, tags, image_front, description
                row = [
                    pid,
                    f"{brand} {title}",
                    brand,
                    price,
                    budget_cat,
                    style_cat,
                    thickness,
                    "8.0 oz",
                    "標準型",
                    "Polymer Honeycomb",
                    "Carbon Fiber",
                    "TRUE",
                    f"來自{origin}的知名品牌 {brand} 最新款式 | 原廠官方說明：{desc_final}",
                    f"最新上架 | {brand} | 原廠直送",
                    front_img,
                    desc_final
                ]
                
                # 寫入 Google Sheets
                try:
                    worksheet.append_row(row)
                    existing_ids.append(pid)
                    new_paddles_count += 1
                    print(f"    -> 成功寫入 Google Sheets: {title}")
                except Exception as e:
                    print(f"    -> 寫入失敗: {e}")
                    
                time.sleep(3) # 避免密集寫入導致 Sheets API 或 Gemini API 達上限
                
        except Exception as e:
            print(f"  [失敗] {e}")

    print(f"\n自動化作業完成！共新增 {new_paddles_count} 支球拍至 Google Sheets。")

if __name__ == "__main__":
    main()
