"""定期更新各縣市球場資料爬蟲腳本。

爬取 ipickleball.com.tw 最新球場資料，自動萃取地址與行政區，
並更新 data/courts_data.json 與 data/courts_for_sheet.csv。
若環境設定有 GOOGLE_CREDENTIALS 與 COURTS_SHEET_GID，可自動同步至 Google Sheets。
"""

import csv
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List
import requests
from bs4 import BeautifulSoup

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

DISTRICT_MAP = {
    "台北市": ["中正區", "大同區", "中山區", "松山區", "大安區", "萬華區", "信義區", "士林區", "北投區", "內湖區", "南港區", "文山區"],
    "新北市": ["板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "土城區", "蘆洲區", "樹林區", "汐止區", "鶯歌區", "三峽區", "淡水區", "五股區", "泰山區", "林口區", "深坑區", "石碇區", "坪林區", "三芝區", "石門區", "八里區", "平溪區", "雙溪區", "貢寮區", "金山區", "萬里區", "烏來區"],
    "台中": ["豐原區", "北屯區", "西屯區", "南屯區", "北區", "南區", "西區", "東區", "中區", "太平區", "大里區", "霧峰區", "烏日區", "后里區", "石岡區", "東勢區", "和平區", "新社區", "潭子區", "大雅區", "神岡區", "大肚區", "沙鹿區", "龍井區", "梧棲區", "清水區", "大甲區", "外埔區", "大安區"],
    "高雄": ["楠梓區", "左營區", "鼓山區", "三民區", "鹽埕區", "前金區", "新興區", "苓雅區", "前鎮區", "旗津區", "小港區", "鳳山區", "大寮區", "鳥松區", "林園區", "仁武區", "大樹區", "大社區", "岡山區", "路竹區", "橋頭區", "梓官區", "彌陀區", "永安區", "燕巢區", "田寮區", "阿蓮區", "茄萣區", "湖內區", "旗山區", "美濃區", "內門區", "杉林區", "甲仙區", "六龜區", "茂林區", "桃源區", "那瑪夏區"],
    "台南": ["東區", "南區", "北區", "安南區", "安平區", "中西區", "新營區", "鹽水區", "白河區", "柳營區", "後壁區", "東山區", "麻豆區", "下營區", "六甲區", "官田區", "大內區", "佳里區", "學甲區", "西港區", "七股區", "將軍區", "北門區", "新化區", "善化區", "新市區", "安定區", "山上區", "玉井區", "楠西區", "南化區", "左鎮區", "仁德區", "歸仁區", "關廟區", "龍崎區", "永康區"],
    "桃園": ["桃園區", "中壢區", "平鎮區", "八德區", "楊梅區", "蘆竹區", "大溪區", "龍潭區", "龜山區", "大園區", "觀音區", "新屋區", "復興區"],
    "新竹": ["東區", "北區", "香山區", "竹北市", "竹東鎮", "新埔鎮", "關西鎮", "湖口鄉", "新豐鄉", "芎林鄉", "橫山鄉", "北埔鄉", "寶山鄉", "峨眉鄉", "尖石鄉", "五峰鄉"],
    "彰化": ["彰化市", "員林市", "和美鎮", "鹿港鎮", "溪湖鎮", "田中鎮", "北斗鎮", "二林鎮", "線西鄉", "伸港鄉", "福興鄉", "秀水鄉", "花壇鄉", "芬園鄉", "大村鄉", "埔鹽鄉", "埔心鄉", "永靖鄉", "社頭鄉", "二水鄉", "田尾鄉", "埤頭鄉", "芳苑鄉", "大城鄉", "竹塘鄉", "溪州鄉"],
    "嘉義": ["東區", "西區", "太保市", "朴子市", "布袋鎮", "大林鎮", "民雄鄉", "溪口鄉", "新港鄉", "六腳鄉", "東石鄉", "義竹鄉", "鹿草鄉", "水上鄉", "中埔鄉", "竹崎鄉", "梅山鄉", "番路鄉", "大埔鄉", "阿里山鄉"],
    "屏東": ["屏東市", "潮州鎮", "東港鎮", "恆春鎮", "萬丹鄉", "長治鄉", "麟洛鄉", "九如鄉", "里港鄉", "鹽埔鄉", "高樹鄉", "萬巒鄉", "內埔鄉", "竹田鄉", "新埤鄉", "枋寮鄉", "新園鄉", "崁頂鄉", "林邊鄉", "南州鄉", "佳冬鄉", "琉球鄉", "車城鄉", "滿州鄉", "枋山鄉", "三地門鄉", "霧台鄉", "瑪家鄉", "泰武鄉", "來義鄉", "春日鄉", "獅子鄉", "牡丹鄉"],
    "宜蘭": ["宜蘭市", "羅東鎮", "蘇澳鎮", "頭城鎮", "礁溪鄉", "壯圍鄉", "員山鄉", "冬山鄉", "五結鄉", "三星鄉", "大同鄉", "南澳鄉"],
    "基隆": ["仁愛區", "信義區", "中正區", "中山區", "安樂區", "暖暖區", "七堵區"],
    "花蓮": ["花蓮市", "鳳林鎮", "玉里鎮", "新城鄉", "吉安鄉", "壽豐鄉", "光復鄉", "豐濱鄉", "瑞穗鄉", "富里鄉", "秀林鄉", "萬榮鄉", "卓溪鄉"],
    "雲林": ["斗六市", "斗南鎮", "虎尾鎮", "西螺鎮", "土庫鎮", "北港鎮", "古坑鄉", "大埤鄉", "莿桐鄉", "林內鄉", "二崙鄉", "崙背鄉", "麥寮鄉", "東勢鄉", "褒忠鄉", "台西鄉", "元長鄉", "四湖鄉", "口湖鄉", "水林鄉"],
    "南投": ["南投市", "埔里鎮", "草屯鎮", "竹山鎮", "集集鎮", "名間鄉", "鹿谷鄉", "中寮鄉", "魚池鄉", "國姓鄉", "水里鄉", "信義鄉", "仁愛鄉"]
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
BASE_URL = "https://ipickleball.com.tw/places/category"

SHEET_ID = "1Zphr-a547bmb0nTTNxz8p5A1dajAmLSOi-mO1NiRydw"
COURTS_SHEET_GID = os.environ.get("COURTS_SHEET_GID", "")


def parse_district(county_name: str, address: str, court_name: str) -> str:
    """從地址或球場名稱中解析出行政區。"""
    candidates = DISTRICT_MAP.get(county_name, [])

    if address:
        for dist in candidates:
            if dist in address:
                return dist

    if court_name:
        for dist in candidates:
            if dist in court_name:
                return dist
            if len(dist) == 3 and dist[:2] in court_name and dist[:2] not in ["中區", "東區", "南區", "西區", "北區"]:
                return dist

    if address:
        m = re.search(r"([^\d市縣]{1,4}[區鎮鄉市])", address)
        if m:
            extracted = m.group(1).strip()
            for dist in candidates:
                if dist in extracted or extracted in dist:
                    return dist

    return "市區" if candidates else "其他區"


def fetch_court_address(court: dict) -> dict:
    """抓取球場詳細頁面取得地址並判定行政區。"""
    url = court.get("url")
    if not url:
        court["address"] = ""
        return court

    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            addr_el = soup.select_one(".geodir-field-address, .geodir-field-post_address, .geodir_post_address")
            if addr_el:
                addr_text = re.sub(r"^地址\s*[:：]?\s*", "", addr_el.text.strip())
                addr_text = re.sub(r"\(.*?\)", "", addr_text).strip()
                court["address"] = addr_text
            else:
                court["address"] = ""
        else:
            court["address"] = ""
    except Exception:
        court["address"] = ""

    return court


def main():
    print("🚀 開始爬取 ipickleball.com.tw 全台球場資料...")
    all_courts_data = {}

    for name, slug in COUNTIES.items():
        print(f"正在爬取 {name} ({slug})...")
        url = f"{BASE_URL}/{slug}/"
        county_courts = []
        page = 1

        try:
            while True:
                page_url = url if page == 1 else f"{url}page/{page}/"
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
                    title_el = card.select_one(".geodir-entry-title a, h2 a, h3 a")
                    if not title_el:
                        continue

                    court_name = title_el.text.strip()
                    court_url = title_el.get("href")

                    if any(c["url"] == court_url for c in county_courts):
                        continue

                    hours = "未提供"
                    hours_el = card.select_one(".gd-bh-today-range, .gd-bh-expand-range")
                    if hours_el:
                        hours = hours_el.text.strip()

                    price = "未提供"
                    price_box = card.find(lambda tag: tag.name == "div" and tag.get("class") and any("geodir-field-cf1" in c or "geodir-field-price" in c for c in tag.get("class", [])))
                    if not price_box:
                        price_el = card.find(string=re.compile(r"收費"))
                        if price_el and price_el.parent:
                            price_box = price_el.parent

                    if price_box:
                        price_text = price_box.text.strip()
                        price = re.sub(r"收費\s*[:：]?\s*", "", price_text).strip()

                    if price in ["0", ""]:
                        price = "免費" if price == "0" else "未提供"

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
                        "address": "",
                        "district": "市區",
                        "_county_name": name,
                    })

                page += 1

            all_courts_data[slug] = {
                "name": name,
                "url": url,
                "courts": county_courts
            }
            print(f"  ✅ 找到 {len(county_courts)} 個球場")
        except Exception as e:
            print(f"  ❌ 爬取錯誤 {name}: {e}")
            all_courts_data[slug] = {"name": name, "url": url, "courts": []}

        time.sleep(1)

    # 批次萃取地址與行政區
    print("\n🔍 正在並行萃取全台球場之精準地址與行政區...")
    all_flat = []
    for slug, info in all_courts_data.items():
        all_flat.extend(info.get("courts", []))

    with ThreadPoolExecutor(max_workers=10) as executor:
        enriched_list = list(executor.map(fetch_court_address, all_flat))

    for c in enriched_list:
        county_name = c.pop("_county_name", "")
        c["district"] = parse_district(county_name, c.get("address", ""), c.get("name", ""))

    # 1. 寫入本地 data/courts_data.json
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, "courts_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_courts_data, f, ensure_ascii=False, indent=2)
    print(f"🎉 球場快照資料已成功儲存至 {json_path}")

    # 2. 匯出 CSV 檔案
    csv_path = os.path.join(data_dir, "courts_for_sheet.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["縣市", "行政區", "球場名稱", "營業時間", "收費資訊", "LINE群連結", "詳情網址", "詳細地址"])
        for slug, info in all_courts_data.items():
            c_name = info.get("name", slug)
            for c in info.get("courts", []):
                writer.writerow([
                    c_name,
                    c.get("district", "市區"),
                    c.get("name", ""),
                    c.get("hours", "未提供"),
                    c.get("price", "未提供"),
                    c.get("line_url", ""),
                    c.get("url", ""),
                    c.get("address", ""),
                ])
    print(f"📄 球場 CSV 已成功匯出至 {csv_path}")


if __name__ == "__main__":
    main()
