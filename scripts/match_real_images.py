import requests
import json
import os
import re

DATA_FILE = "data/paddles_data.json"

SHOPIFY_SITES = [
    "https://www.selkirk.com/products.json?limit=250",
    "https://crbnpickleball.com/products.json?limit=250",
    "https://www.sixzeropickleball.com/products.json?limit=250",
    "https://engagepickleball.com/products.json?limit=250",
    "https://vaticpro.com/products.json?limit=250",
    "https://www.breadandbutterpickleball.com/products.json?limit=250",
    "https://joolausa.com/products.json?limit=250",
    "https://www.ronbus.com/products.json?limit=250",
    "https://paddletek.com/products.json?limit=250",
    "https://diademsports.com/products.json?limit=250",
    "https://volair.com/products.json?limit=250",
    "https://www.gearboxsports.com/products.json?limit=250",
    "https://onixpickleball.com/products.json?limit=250",
    "https://hudefsport.com/products.json?limit=250",
    "https://electrumpickleball.com/products.json?limit=250",
    "https://www.zcebra.com/products.json?limit=250",
    "https://niupipo.com/products.json?limit=250",
    "https://holbrookpickleball.com/products.json?limit=250",
    "https://pickleballapes.com/products.json?limit=250",
    "https://thrivepb.com/products.json?limit=250",
    "https://neonicpickleball.com/products.json?limit=250",
    "https://11six24.com/products.json?limit=250",
    "https://luzzpickleball.com/products.json?limit=250"
]

def get_shopify_inventory():
    inventory = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for site in SHOPIFY_SITES:
        print(f"正在抓取圖片庫: {site.split('/')[2]}")
        try:
            r = requests.get(site, headers=headers, timeout=10)
            if r.status_code == 200:
                products = r.json().get("products", [])
                for prod in products:
                    title = prod.get("title", "")
                    title_lower = title.lower()
                    if any(w in title_lower for w in ["bag", "cover", "backpack", "duffle", "eraser", "grip", "shirt", "tank", "hat"]):
                        continue
                    
                    images = prod.get("images", [])
                    if images:
                        front = images[0]["src"]
                        inventory.append({
                            "title": title.lower(),
                            "front": front,
                            "brand": site.split('/')[2]
                        })
        except Exception as e:
            print(f"抓取失敗 {site}: {e}")
    return inventory

CUSTOM_FALLBACKS = {
    "DEFAULT": [
        {"front": "https://raw.githubusercontent.com/princend/pickleball-linebot/main/data/images/no_image.png"} 
    ]
}

def match_images():
    inventory = get_shopify_inventory()
    print(f"成功收集到 {len(inventory)} 組來自各大品牌官網的真實球拍圖片！")
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        paddles = json.load(f)

    matched_count = 0

    for p in paddles:
        name_lower = p["name"].lower()
        brand = p["brand"]
        
        best_match = None
        max_matches = 0
        
        # 只有當圖片是預設的 no_image.png 時，才嘗試進行配對 (保留爬蟲的精準圖片)
        if "no_image.png" not in p.get("image_front", "no_image.png"):
            continue
            
        for item in inventory:
            # 嚴格要求品牌必須吻合，避免 Insum 配到 Selkirk 的橡皮擦
            brand_match = brand.lower().replace(" ", "") in item["brand"].replace("-", "")
            if not brand_match:
                continue

            words = set(re.findall(r'\w+', name_lower))
            item_words = set(re.findall(r'\w+', item["title"]))
            
            # Remove brand words from the intersection check to avoid matching any random product just because the brand name matches
            brand_words = set(re.findall(r'\w+', brand.lower()))
            words -= brand_words
            item_words -= brand_words
            
            common = len(words.intersection(item_words))
            
            # We require ALL words in the paddle name (excluding brand) to be present in the Shopify title
            # This prevents Z5 Composite matching with Evoke Composite
            if common == len(words) and common > max_matches:
                max_matches = common
                best_match = item
                
        if best_match:
            p["image_front"] = best_match["front"]
            matched_count += 1
            print(f"Matched {p['name']} -> {best_match['title']}")
        else:
            print(f"Unmatched: {p['name']}")
            # 如果沒有配對成功，強制使用『尚無圖片』，確保不會有任何張冠李戴的情況
            p["image_front"] = "https://raw.githubusercontent.com/princend/pickleball-linebot/main/data/images/no_image.png"

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(paddles, f, ensure_ascii=False, indent=2)
        
    print(f"圖片重新分配完成！精準配對了 {matched_count} 款球拍。")

if __name__ == "__main__":
    match_images()
