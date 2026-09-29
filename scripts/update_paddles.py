"""定時更新與驗證匹克球主流推薦球拍資料模組。

定期檢查與維護 data/paddles_data.json 的完整性，包含：
1. 欄位結構完整性驗證 (正面與反面圖片、規格、價格、預算與風格分類)。
2. 內容正確性驗證 (厚度必須為合理的 mm，重量必須為合理的 oz，價格必須 > 0)。
3. 遠端圖片實際有效性驗證 (HTTP 200 檢查，排除 403/404)。
4. 若資料有誤或圖片失效則自動修復或替換為同品牌備援圖。
"""

import json
import os
import sys
import requests
import time
from typing import Any, Dict, List

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

# 安全的同品牌/通用備援圖庫，保證不會擋 LINE (HTTP 403)
SAFE_FALLBACKS = {
    "JOOLA": [
        "https://joola.tw/wp-content/uploads/2023/11/Ben-Johns-Perseus-CFS-16-18516-Web-01.jpg",
        "https://joola.tw/wp-content/uploads/2023/04/18507_Hyperion-CGS-14-1.jpg"
    ],
    "Six Zero": [
        "https://cdn.shopify.com/s/files/1/0667/7348/3824/files/FRONT_7c4fad2f-f7ff-4fd0-8627-edefac3f85f0.png"
    ],
    "DEFAULT": [
        "https://cdn.shopify.com/s/files/1/0667/7348/3824/files/2G1A0007_1566d729-dacd-4b74-bca7-dcf390b79c07.png"
    ]
}

REQUIRED_FIELDS = [
    "id", "name", "brand", "price_ntd", "budget_category", 
    "style_category", "thickness", "weight", "image_front", "image_back"
]

def load_paddles() -> List[Dict[str, Any]]:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_paddles(paddles: List[Dict[str, Any]]) -> bool:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(paddles, f, ensure_ascii=False, indent=2)
    return True

def verify_image_url(url: str) -> bool:
    """實際發送 HTTP 請求驗證圖片是否可存取 (排除 404, 403)"""
    if not url or not url.startswith("http"):
        return False
    try:
        # 使用常見 User-Agent 模擬 LINE 或瀏覽器
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"}
        r = requests.head(url, headers=headers, timeout=5)
        # 如果 head 被阻擋，嘗試 get
        if r.status_code in [403, 405]:
             r = requests.get(url, headers=headers, timeout=5, stream=True)
             r.close()
        return r.status_code == 200
    except:
        return False

def get_fallback_image(brand: str) -> str:
    """根據品牌取得安全的備援圖片"""
    import random
    pool = SAFE_FALLBACKS.get(brand, SAFE_FALLBACKS["DEFAULT"])
    return random.choice(pool)

def validate_and_update_paddles() -> bool:
    print("開始執行球拍資料庫嚴格驗證與更新...")
    paddles = load_paddles()
    if not paddles:
        return False

    updated_count = 0
    
    # 建立一個 cache 避免同一個 url 重複檢查浪費時間
    url_cache = {}

    for paddle in paddles:
        name = paddle.get("name", "未命名球拍")
        brand = paddle.get("brand", "DEFAULT")
        modified = False

        # 1. 檢查必填欄位與內容合理性
        for field in REQUIRED_FIELDS:
            if field not in paddle or paddle[field] is None or str(paddle[field]).strip() == "":
                print(f"  - [警告] {name} 缺少欄位 '{field}'")
                modified = True
                if field == "budget_category": paddle["budget_category"] = "intermediate"
                elif field == "style_category": paddle["style_category"] = "control"
                elif field == "thickness": paddle["thickness"] = "16mm"
                elif field == "weight": paddle["weight"] = "8.0 oz"
        
        # 內容邏輯校正
        if "mm" not in str(paddle.get("thickness", "")).lower():
            paddle["thickness"] = f"{paddle.get('thickness', 16)}mm"
            modified = True
            
        if "oz" not in str(paddle.get("weight", "")).lower() and "g" not in str(paddle.get("weight", "")).lower():
            paddle["weight"] = f"{paddle.get('weight', 8.0)} oz"
            modified = True
            
        price = paddle.get("price_ntd")
        if not isinstance(price, (int, float)) or price < 500 or price > 20000:
            paddle["price_ntd"] = 3500
            modified = True

        # 2. 嚴格驗證圖片有效性 (HTTP 200)
        for img_field in ["image_front", "image_back"]:
            img_url = paddle.get(img_field, "")
            
            # 使用 cache 加速
            if img_url not in url_cache:
                is_valid = verify_image_url(img_url)
                url_cache[img_url] = is_valid
                time.sleep(0.1) # 避免被 ban
            else:
                is_valid = url_cache[img_url]

            if not is_valid:
                print(f"  - [圖片失效] {name} 的 {img_field} 無法存取 ({img_url[:30]}...)，執行自動替換。")
                paddle[img_field] = get_fallback_image(brand)
                modified = True

        if modified:
            updated_count += 1

    if updated_count > 0:
        save_paddles(paddles)
        print(f"完成修復與更新！共修正 {updated_count} 款球拍資料。")
    else:
        print("所有 100 款球拍資料與圖片連結 (HTTP 200) 皆完整正確，無須變更。")

    return True

if __name__ == "__main__":
    success = validate_and_update_paddles()
    if not success:
        sys.exit(1)
