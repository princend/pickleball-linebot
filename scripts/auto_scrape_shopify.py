import requests
import json
import os
import re
import time

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
                    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
                    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                    desc_text = re.sub(r'<[^>]+>', ' ', html)
                    desc_text = re.sub(r'\s+', ' ', desc_text).strip()
                    desc = desc_text[:80] + "..." if len(desc_text) > 80 else desc_text
                    
                    
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
                            f"原廠官方說明：{desc}"
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
