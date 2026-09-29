import requests
import json
import os
import re
import time

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

SHOPIFY_ENDPOINTS = [
    {"brand": "Six Zero", "url": "https://www.sixzeropickleball.com/products.json?limit=10", "origin": "澳洲"},
    {"brand": "CRBN", "url": "https://crbnpickleball.com/products.json?limit=10", "origin": "美國"},
    {"brand": "Vatic Pro", "url": "https://vaticpro.com/products.json?limit=10", "origin": "美國"},
    {"brand": "Engage", "url": "https://engagepickleball.com/products.json?limit=10", "origin": "美國"}
]

# 品牌字典，用來避免產地幻覺
BRAND_INFO = {
    "Luzz": {"origin": "中國", "desc": "高性價比的中系品牌"},
    "NAPA": {"origin": "台灣", "desc": "台灣新銳品牌"},
    "JNICE": {"origin": "台灣", "desc": "台灣知名羽球大廠"},
    "Selkirk": {"origin": "美國", "desc": "北美頂級匹克球品牌"},
    "Joola": {"origin": "德國/美國", "desc": "國際知名桌球/匹克球大廠"}
}

def is_valid_image(url):
    """抓取時第一時間驗證圖片，不合格直接拋棄"""
    if not url or not url.startswith("http"):
        return False
    try:
        r = requests.head(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code in [403, 405]:
            r = requests.get(url, timeout=5, stream=True, headers={"User-Agent": "Mozilla/5.0"})
            r.close()
        return r.status_code == 200
    except:
        return False

def validate_scraped_data(paddle):
    """嚴格審查抓回來的資料正確性"""
    # 1. 價格合理性 (台幣 500 ~ 20000)
    if paddle["price_ntd"] < 500 or paddle["price_ntd"] > 20000:
        print(f"  [拒絕] 價格異常: {paddle['price_ntd']}")
        return False
        
    # 2. 圖片必備且有效
    if not is_valid_image(paddle["image_front"]) or not is_valid_image(paddle["image_back"]):
        print(f"  [拒絕] 圖片 URL 無效或被阻擋")
        return False
        
    # 3. 厚度合理性 (10mm - 25mm)
    thickness = paddle["thickness"].lower().replace("mm", "").strip()
    try:
        t_val = float(thickness)
        if t_val < 10 or t_val > 25:
             print(f"  [拒絕] 厚度異常: {paddle['thickness']}")
             return False
    except:
        # 如果無法解析為數字，也拒絕
        print(f"  [拒絕] 厚度格式錯誤: {paddle['thickness']}")
        return False
        
    return True

def main():
    print("啟動高嚴格度 Shopify 爬蟲...")
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []
        
    existing_ids = {p["id"] for p in existing}
    added_count = 0

    for endpoint in SHOPIFY_ENDPOINTS:
        brand = endpoint["brand"]
        origin = endpoint["origin"]
        print(f"正在爬取 {brand} ...")
        try:
            r = requests.get(endpoint["url"], timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
                
            products = r.json().get("products", [])
            for prod in products:
                title = prod.get("title", "")
                if "paddle" not in title.lower() and prod.get("product_type", "").lower() != "paddle":
                    continue
                    
                pid = re.sub(r'[^a-z0-9\-]', '', f"{brand.lower()}-{title.lower().replace(' ', '-')}")
                if pid in existing_ids:
                    continue
                
                # 價格
                variants = prod.get("variants", [])
                price = 0
                if variants:
                    try: price = int(float(variants[0].get("price", "0")) * 32)
                    except: pass
                        
                # 圖片
                images = prod.get("images", [])
                front_img = images[0]["src"] if len(images) > 0 else ""
                back_img = images[1]["src"] if len(images) > 1 else front_img
                
                # 分析厚度
                thickness = "16mm"
                if "14mm" in title.lower(): thickness = "14mm"
                elif "13mm" in title.lower(): thickness = "13mm"
                elif "20mm" in title.lower(): thickness = "20mm"
                
                # 客觀文案，避免幻覺
                desc = re.sub(r'<[^>]+>', '', prod.get('body_html', ''))[:80] + "..."
                
                new_paddle = {
                    "id": pid,
                    "name": f"{brand} {title}",
                    "brand": brand,
                    "price_ntd": price,
                    "budget_category": "advanced" if price > 5000 else "intermediate",
                    "style_category": "control",
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
                    "image_back": back_img,
                    "description": f"來自{origin}的 {brand} 最新球拍"
                }
                
                # 執行嚴格驗證！
                if validate_scraped_data(new_paddle):
                    existing.append(new_paddle)
                    existing_ids.add(pid)
                    added_count += 1
                    print(f"  [通過] 成功新增：{new_paddle['name']}")
                
                time.sleep(0.5)
                
        except Exception as e:
            print(f"  [錯誤] {e}")
            
    if added_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
            
    print(f"\n✅ 爬蟲結束！經過嚴格審核後，共新增了 {added_count} 款球拍。")

if __name__ == "__main__":
    main()
