import json
import time
import requests
import re
from bs4 import BeautifulSoup
import os

COUNTIES = {
    "台北市": "taipei-city",
    "新北市": "new-taipei-city",
    "台中": "taichung",
    "新竹": "hsinchu",
    "桃園": "taoyuan",
    "宜蘭": "yilan",
    "彰化": "changhua",
    "高雄": "kaohsiung",
    "台南": "tainan",
    "嘉義": "chiayi",
    "雲林": "yunlin",
    "南投": "nantou",
    "屏東": "pngtung",
    "基隆": "keelung",
    "花蓮": "hualien",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
BASE_URL = "https://ipickleball.com.tw/places/category"

all_courts_data = {}

print("開始爬取 ipickleball.com.tw 球場資料...")

for name, slug in COUNTIES.items():
    print(f"正在爬取 {name} ({slug})...")
    url = f"{BASE_URL}/{slug}/"
    
    try:
        county_courts = []
        page = 1
        while True:
            page_url = url if page == 1 else f"{url}page/{page}/"
            print(f"    - 正在爬取第 {page} 頁...")
            res = requests.get(page_url, headers=HEADERS, timeout=10)
            if res.status_code == 404:
                break
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            
            cards = soup.select(".geodir-category-list-view li")
            if not cards:
                cards = soup.select("div.card.h-100, div.card")
            if not cards:
                break
            for card in cards:
                # 取得名稱與連結
                title_el = card.select_one(".geodir-entry-title a, h2 a, h3 a")
                if not title_el:
                    continue

                court_name = title_el.text.strip()
                court_url = title_el.get("href")
            
                # 去重複 (同一卡片可能匹配到多次)
                if any(c['url'] == court_url for c in county_courts):
                    continue

                # 嘗試取得營業時間
                hours = "未提供"
                hours_el = card.select_one(".gd-bh-today-range, .gd-bh-expand-range")
                if hours_el:
                    hours = hours_el.text.strip()

                # 嘗試取得收費資訊
                price = "未提供"
                price_box = card.find(lambda tag: tag.name == "div" and tag.get("class") and any("geodir-field-cf1" in c or "geodir-field-price" in c for c in tag.get("class", [])))
                if not price_box:
                    price_el = card.find(string=re.compile(r"收費"))
                    if price_el:
                        p = price_el
                        for _ in range(3):
                            if p and p.parent:
                                p = p.parent
                                if "收費" in p.text and len(p.text.strip()) > len(price_el.text.strip()) + 1:
                                    price_box = p
                                    break

                if price_box:
                    price_text = price_box.text.strip()
                    price = re.sub(r"收費\s*[:：]?\s*", "", price_text).strip()
            
                if price == "0" or price == "":
                    price = "免費" if price == "0" else "未提供"

                # LINE 群連結
                line_url = None
                line_el = card.select_one(".geodir-field-line_ a")
                if line_el:
                    line_url = line_el.get("href")
                else:
                    line_el = card.find("a", string=re.compile(r"LINE", re.I))
                    if line_el:
                        line_url = line_el.get("href")

                county_courts.append({
                    "name": court_name,
                    "url": court_url,
                    "hours": hours,
                    "price": price,
                    "line_url": line_url,
                })
            
            page += 1
        all_courts_data[slug] = {
            "name": name,
            "url": url,
            "courts": county_courts
        }
        print(f"  ✅ 找到 {len(county_courts)} 個球場")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print(f"  ❌ 遭到伺服器阻擋 (403 Forbidden)，無法爬取 {name}")
        else:
            print(f"  ❌ HTTP 錯誤 {name}: {e}")
        all_courts_data[slug] = {"name": name, "url": url, "courts": []}
    except Exception as e:
        print(f"  ❌ 爬取錯誤 {name}: {e}")
        all_courts_data[slug] = {"name": name, "url": url, "courts": []}
        
    time.sleep(2)  # 避免請求過快被鎖 IP

# 儲存 JSON
data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(data_dir, exist_ok=True)
json_path = os.path.join(data_dir, "courts_data.json")

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(all_courts_data, f, ensure_ascii=False, indent=2)

print(f"\n🎉 爬取完成！資料已儲存至 {json_path}")
