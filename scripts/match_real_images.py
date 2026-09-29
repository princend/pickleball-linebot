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
    "https://niupipo.com/products.json?limit=250"
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
        {"front": "https://images.unsplash.com/photo-1622227432807-91eb590c31bb?auto=format&fit=crop&w=400&q=80"} # General paddle-like image or just leave it
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
        
        for item in inventory:
            words = set(re.findall(r'\w+', name_lower))
            item_words = set(re.findall(r'\w+', item["title"]))
            
            brand_match = brand.lower().replace(" ", "") in item["brand"].replace("-", "")
            
            common = len(words.intersection(item_words))
            if brand_match:
                common += 3
                
            if common > max_matches and common >= 2:
                max_matches = common
                best_match = item
                
        if best_match:
            p["image_front"] = best_match["front"]
            matched_count += 1
            print(f"Matched {p['name']} -> {best_match['title']}")
        else:
            print(f"Unmatched: {p['name']}")
            # Keep existing image_front if it's already a shopify link or something valid
            current = p.get("image_front", "")
            if not current or "7c4fad2f-f7ff-4fd0" in current or "joola.tw/wp-content" in current:
                # Give it a generic valid Unsplash paddle image instead of the wrong Six Zero one
                p["image_front"] = "https://images.unsplash.com/photo-1622227432807-91eb590c31bb?auto=format&fit=crop&w=400&q=80"

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(paddles, f, ensure_ascii=False, indent=2)
        
    print(f"圖片重新分配完成！精準配對了 {matched_count} 款球拍。")

if __name__ == "__main__":
    match_images()
