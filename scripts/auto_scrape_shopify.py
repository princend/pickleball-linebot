import requests
import json
import os
import re

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

# 這裡列出使用 Shopify 架站的知名匹克球品牌 API
SHOPIFY_ENDPOINTS = [
    {"brand": "Six Zero", "url": "https://www.sixzeropickleball.com/products.json?limit=10"},
    {"brand": "CRBN", "url": "https://crbnpickleball.com/products.json?limit=10"},
    {"brand": "Bread & Butter", "url": "https://www.breadandbutterpickleball.com/products.json?limit=10"}
]

def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_paddles(paddles):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(paddles, f, ensure_ascii=False, indent=2)

def main():
    print("開始自動爬取海外 Shopify API 最新球拍資料...")
    existing = load_existing()
    # 建立目前所有的 id 集合，避免重複
    existing_ids = {p["id"] for p in existing}
    added_count = 0

    for endpoint in SHOPIFY_ENDPOINTS:
        brand = endpoint["brand"]
        print(f"正在爬取 {brand} 的最新產品...")
        try:
            r = requests.get(endpoint["url"], timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                print(f"  [失敗] {brand} API 無法存取 (HTTP {r.status_code})")
                continue
                
            data = r.json()
            products = data.get("products", [])
            
            for prod in products:
                title = prod.get("title", "")
                
                # 簡單過濾：必須是 Paddle (排除衣服、配件)
                if "paddle" not in title.lower() and "paddle" not in prod.get("product_type", "").lower():
                    # 很多時候產品名稱不含 paddle，但 type 是 paddle
                    if prod.get("product_type", "").lower() != "paddle":
                        continue
                
                # 產生 ID
                pid = f"{brand.lower().replace(' ', '').replace('&', '')}-{title.lower().replace(' ', '-')}"
                pid = re.sub(r'[^a-z0-9\-]', '', pid)
                
                if pid in existing_ids:
                    continue
                
                # 解析價格
                variants = prod.get("variants", [])
                price = 4500 # 預設價格
                if variants:
                    try:
                        price = int(float(variants[0].get("price", "150.00")) * 32) # 美金轉台幣估算
                    except:
                        pass
                        
                # 解析圖片
                images = prod.get("images", [])
                front_img = images[0]["src"] if len(images) > 0 else ""
                back_img = images[1]["src"] if len(images) > 1 else front_img
                
                # 自動判斷厚度與風格 (簡單的關鍵字猜測)
                thickness = "16mm"
                if "14mm" in title.lower(): thickness = "14mm"
                elif "13mm" in title.lower(): thickness = "13mm"
                elif "20mm" in title.lower(): thickness = "20mm"
                
                style = "control"
                if "power" in title.lower(): style = "power"
                elif "spin" in title.lower(): style = "spin"
                elif "speed" in title.lower(): style = "speed"
                
                # 組合資料
                new_paddle = {
                    "id": pid,
                    "name": f"{brand} {title}",
                    "brand": brand,
                    "price_ntd": price,
                    "budget_category": "advanced" if price > 5000 else "intermediate",
                    "style_category": style,
                    "thickness": thickness,
                    "weight": "8.0 oz",
                    "shape": "標準型",
                    "core": "自動化偵測核心",
                    "surface": "自動化偵測碳纖維",
                    "usapa_approved": True,
                    "features": [
                        f"這是由爬蟲自動從 {brand} 官網抓取的最新球拍！",
                        f"產品原文描述摘要：{prod.get('body_html', '')[:50]}..."
                    ],
                    "tags": ["最新上架", "爬蟲自動同步"],
                    "image_front": front_img,
                    "image_back": back_img,
                    "description": f"由爬蟲自動從 {brand} 官網抓取的最新球拍！"
                }
                
                existing.append(new_paddle)
                existing_ids.add(pid)
                added_count += 1
                print(f"  [新增] 成功抓取新球拍：{new_paddle['name']}")
                
        except Exception as e:
            print(f"  [錯誤] 爬取 {brand} 時發生例外狀況：{e}")
            
    if added_count > 0:
        save_paddles(existing)
        print(f"\n✅ 爬取完成！共自動新增了 {added_count} 款最新球拍。")
    else:
        print("\n✅ 爬取完成！目前官網沒有新球拍。")

if __name__ == "__main__":
    main()
