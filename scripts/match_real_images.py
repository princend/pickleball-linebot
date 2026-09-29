import requests
import json
import os
import re

DATA_FILE = "data/paddles_data.json"

# Shopify 網站列表，用來萃取真實的圖片
SHOPIFY_SITES = [
    "https://www.selkirk.com/products.json?limit=250",
    "https://crbnpickleball.com/products.json?limit=250",
    "https://www.sixzeropickleball.com/products.json?limit=250",
    "https://engagepickleball.com/products.json?limit=250",
    "https://vaticpro.com/products.json?limit=250",
    "https://www.breadandbutterpickleball.com/products.json?limit=250"
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
                    if "paddle" in title.lower() or "paddle" in prod.get("product_type", "").lower():
                        if images:
                            front = images[0]["src"]
                            back = images[1]["src"] if len(images) > 1 else front
                            inventory.append({
                                "title": title.lower(),
                                "front": front,
                                "back": back,
                                "brand": site.split('/')[2]
                            })
        except Exception as e:
            print(f"抓取失敗 {site}: {e}")
    return inventory

# 針對 Joola 與其他非 Shopify 大廠，手動準備幾組不會擋 LINE 的真實圖作為專屬備援
CUSTOM_FALLBACKS = {
    "JOOLA": [
        {"front": "https://joola.tw/wp-content/uploads/2023/11/Ben-Johns-Perseus-CFS-16-18516-Web-01.jpg", "back": "https://joola.tw/wp-content/uploads/2023/11/Ben-Johns-Perseus-CFS-16-18516-Web-02.jpg"},
        {"front": "https://joola.tw/wp-content/uploads/2023/04/18507_Hyperion-CGS-14-1.jpg", "back": "https://joola.tw/wp-content/uploads/2023/04/18507_Hyperion-CGS-14-2.jpg"},
        {"front": "https://joola.tw/wp-content/uploads/2023/11/18514_Perseus-CFS-14-scaled.jpg", "back": "https://joola.tw/wp-content/uploads/2023/11/Anna-Bright-Scorpeus-CFS-14-18515-Web-03.jpg"}
    ],
    "Paddletek": [
        {"front": "https://www.justpaddles.com/media/catalog/product/p/a/paddletek-tempest-wave-pro-c-standard-pickleball-paddle-front_1.jpg", "back": "https://www.justpaddles.com/media/catalog/product/p/a/paddletek-tempest-wave-pro-c-standard-pickleball-paddle-back_1.jpg"} # 如果 Justpaddles 擋了，這個還是出不來
    ],
    "DEFAULT": [
        {"front": "https://cdn.shopify.com/s/files/1/0667/7348/3824/files/FRONT_7c4fad2f-f7ff-4fd0-8627-edefac3f85f0.png", "back": "https://cdn.shopify.com/s/files/1/0667/7348/3824/files/NEXTGEM_7e76952a-7225-4eed-82b8-2442beffd2d5.png"}
    ]
}

def match_images():
    inventory = get_shopify_inventory()
    print(f"成功收集到 {len(inventory)} 組來自各大品牌官網的真實球拍圖片！")
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        paddles = json.load(f)

    import random
    matched_count = 0
    fallback_count = 0

    for p in paddles:
        name_lower = p["name"].lower()
        brand = p["brand"]
        
        # 1. 嘗試在 Shopify inventory 中進行字串比對
        best_match = None
        max_matches = 0
        
        for item in inventory:
            # 將名稱拆成單字比對
            words = set(re.findall(r'\w+', name_lower))
            item_words = set(re.findall(r'\w+', item["title"]))
            
            # 如果品牌符合，加權
            brand_match = brand.lower().replace(" ", "") in item["brand"].replace("-", "")
            
            common = len(words.intersection(item_words))
            if brand_match:
                common += 2
                
            if common > max_matches and common >= 2:
                max_matches = common
                best_match = item
                
        if best_match:
            p["image_front"] = best_match["front"]
            p["image_back"] = best_match["back"]
            matched_count += 1
        else:
            # 2. 如果配對不到，依照品牌分配特有備援圖，避免「所有人長得一樣」
            pool = CUSTOM_FALLBACKS.get(brand, CUSTOM_FALLBACKS["DEFAULT"])
            # 如果 pool 只有一張，就取第一張。如果有好幾張，就 hash id 來穩定隨機
            idx = sum(ord(c) for c in p["id"]) % len(pool)
            p["image_front"] = pool[idx]["front"]
            p["image_back"] = pool[idx]["back"]
            fallback_count += 1

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(paddles, f, ensure_ascii=False, indent=2)
        
    print(f"圖片重新分配完成！精準配對了 {matched_count} 款球拍，針對特定品牌分配了 {fallback_count} 款特有圖片。")

if __name__ == "__main__":
    match_images()
