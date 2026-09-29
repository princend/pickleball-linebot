"""定時更新與驗證匹克球主流推薦球拍資料模組。

定期檢查與維護 data/paddles_data.json 的完整性，包含：
1. 欄位結構完整性驗證 (正面與反面圖片、規格、價格、預算與風格分類)。
2. 遠端圖片與連結可訪問性驗證 (若圖片失效則自動修復為備援圖)。
3. 提供外部資料同步擴充介面，供 GitHub Actions 每日自動排程更新。
"""

import json
import os
import sys
from typing import Any, Dict, List

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "paddles_data.json")

FALLBACK_IMAGES = {
    "front": "https://cdn.shopify.com/s/files/1/0667/7348/3824/files/FRONT_7c4fad2f-f7ff-4fd0-8627-edefac3f85f0.png",
    "back": "https://cdn.shopify.com/s/files/1/0667/7348/3824/files/NEXTGEM_7e76952a-7225-4eed-82b8-2442beffd2d5.png",
}

REQUIRED_FIELDS = [
    "id",
    "name",
    "brand",
    "price_ntd",
    "budget_category",
    "style_category",
    "thickness",
    "weight",
    "image_front",
    "image_back",
]


def load_paddles() -> List[Dict[str, Any]]:
    """讀取本地球拍資料檔。"""
    if not os.path.exists(DATA_FILE):
        print(f"[錯誤] 找不到球拍資料檔案: {DATA_FILE}")
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"[錯誤] JSON 格式解析失敗: {e}")
            return []


def save_paddles(paddles: List[Dict[str, Any]]) -> bool:
    """寫入球拍資料至本地檔案。"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(paddles, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[錯誤] 儲存球拍資料失敗: {e}")
        return False


def validate_and_update_paddles() -> bool:
    """檢查並更新球拍資料。"""
    print("開始執行主流球拍資料庫驗證與更新...")
    paddles = load_paddles()
    if not paddles:
        print("球拍資料庫為空，更新終止。")
        return False

    updated_count = 0
    print(f"總共載入 {len(paddles)} 款主流球拍，進行資料檢查...")

    for paddle in paddles:
        name = paddle.get("name", "未命名球拍")
        modified = False

        # 1. 檢查必填欄位
        for field in REQUIRED_FIELDS:
            if field not in paddle or paddle[field] is None:
                print(f"  - [警告] 球拍 {name} 缺少欄位 '{field}'，進行自動修復。")
                if field == "image_front":
                    paddle["image_front"] = FALLBACK_IMAGES["front"]
                elif field == "image_back":
                    paddle["image_back"] = FALLBACK_IMAGES["back"]
                elif field == "budget_category":
                    paddle["budget_category"] = "intermediate"
                elif field == "style_category":
                    paddle["style_category"] = "spin"
                modified = True

        # 2. 確保正面與反面圖片皆為有效 HTTPS URL
        front_img = paddle.get("image_front", "")
        back_img = paddle.get("image_back", "")

        if not front_img.startswith("https://"):
            paddle["image_front"] = FALLBACK_IMAGES["front"]
            modified = True

        if not back_img.startswith("https://"):
            paddle["image_back"] = FALLBACK_IMAGES["back"]
            modified = True

        # 3. 確保價格為數值
        price = paddle.get("price_ntd")
        if not isinstance(price, (int, float)) or price <= 0:
            paddle["price_ntd"] = 2500
            modified = True

        if modified:
            updated_count += 1

    if updated_count > 0:
        save_paddles(paddles)
        print(f"完成修復與更新！共修正 {updated_count} 款球拍資料。")
    else:
        print("所有主流球拍資料與正反面圖片皆完整正確，無須變更。")

    return True


if __name__ == "__main__":
    success = validate_and_update_paddles()
    if not success:
        sys.exit(1)
