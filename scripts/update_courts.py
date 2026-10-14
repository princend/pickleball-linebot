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
COURTS_SHEET_GID = os.environ.get("COURTS_SHEET_GID", "1386987707")


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


def scrape_sa_iplay_courts() -> List[dict]:
    """從教育部體育署 iplay 官方 API 爬取全台公立匹克球場與國民運動中心。"""
    import urllib.parse
    import urllib3
    urllib3.disable_warnings()

    print("🏛️ 正在向教育部體育署 (iplay) API 爬取全台運動中心與公立匹克球場...")
    sa_headers = {"User-Agent": "Mozilla/5.0"}
    new_courts = []

    # 1. 搜尋「匹克球」公立場館
    u1 = "https://iplay.sa.gov.tw/api/GymSearchAllList?$format=application/json;odata.metadata=none&Keyword=匹克球"
    try:
        r = requests.get(u1, headers=sa_headers, verify=False, timeout=8)
        if r.status_code == 200:
            for item in r.json():
                name = item.get("Name", "").strip()
                addr = item.get("Address", "").strip()
                web = item.get("WebUrl", "") or f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name)}"
                new_courts.append({
                    "name": name,
                    "address": addr,
                    "hours": "全天開放" if "公園" in name else "06:00 – 22:00",
                    "price": "免費" if "公園" in name else "請見中心臨租公告",
                    "line_url": None,
                    "url": web,
                })
    except Exception as e:
        print(f"  [體育署 iplay] 查詢匹克球場失敗: {e}")

    # 2. 搜尋「國民運動中心」
    u2 = "https://iplay.sa.gov.tw/api/GymSearchAllList?$format=application/json;odata.metadata=none&Keyword=國民運動中心"
    try:
        r = requests.get(u2, headers=sa_headers, verify=False, timeout=8)
        if r.status_code == 200:
            for item in r.json():
                name = item.get("Name", "").strip()
                addr = item.get("Address", "").strip()
                web = item.get("WebUrl", "") or f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(name)}"
                new_courts.append({
                    "name": name,
                    "address": addr,
                    "hours": "06:00 – 22:00",
                    "price": "請見中心臨租公告",
                    "line_url": None,
                    "url": web,
                })
    except Exception as e:
        print(f"  [體育署 iplay] 查詢運動中心失敗: {e}")

    # 補充重要新落成場館
    extras = [
        {
            "name": "豐原國民暨兒童運動中心",
            "address": "臺中市豐原區豐裕路8號",
            "hours": "06:00 – 22:00",
            "price": "請見中心臨租公告",
            "line_url": None,
            "url": "https://www.facebook.com/FYCSC04/",
        },
        {
            "name": "臺中市清水國民暨兒童運動中心",
            "address": "臺中市清水區鎮政路",
            "hours": "06:00 – 22:00",
            "price": "請見中心臨租公告",
            "line_url": None,
            "url": "https://www.taichung.gov.tw/",
        }
    ]
    new_courts.extend(extras)
    print(f"  ✅ [體育署 iplay] 共取得 {len(new_courts)} 筆公立场館資料！")
    return new_courts


def merge_sa_courts_into_data(all_courts_data: dict, sa_courts: list):
    """將體育署運動場館去重合併至各縣市球場資料中。"""
    added_count = 0
    for court in sa_courts:
        addr = court.get("address", "")
        name = court.get("name", "")
        norm_addr = addr.replace("臺", "台")
        norm_name = name.replace("臺", "台")

        target_slug = None
        target_county_name = None
        for c_name, slug in COUNTIES.items():
            short_name = c_name.replace("市", "").replace("縣", "")
            if c_name in norm_addr or short_name in norm_addr or c_name in norm_name or short_name in norm_name:
                target_slug = slug
                target_county_name = c_name
                break

        if not target_slug:
            continue

        if target_slug not in all_courts_data:
            all_courts_data[target_slug] = {
                "name": target_county_name,
                "url": f"{BASE_URL}/{target_slug}/",
                "courts": []
            }

        existing_courts = all_courts_data[target_slug]["courts"]
        is_dup = False
        for ex in existing_courts:
            if name in ex["name"] or ex["name"] in name:
                is_dup = True
                break
            if addr and ex.get("address") and addr == ex.get("address"):
                is_dup = True
                break

        if not is_dup:
            court["district"] = parse_district(target_county_name, norm_addr, norm_name)
            existing_courts.append(court)
            added_count += 1

    print(f"  ✨ 去重後共補充合併 {added_count} 所公立體育館/國民運動中心至各縣市資料中！")


TAICHUNG_VERIFIED_COURTS = [
    # 西屯區
    {
        "name": "Pickzone 匹克球場（朝馬館）",
        "district": "西屯區",
        "address": "台中市西屯區環中路三段98-2A號",
        "hours": "24小時營業",
        "price": "約 $300~$600/時，臨打約 $150~$200",
        "line_url": "https://line.me/R/ti/p/@336xlhhb",
        "url": "https://www.google.com/maps/search/?api=1&query=Pickzone%E6%9C%9D%E9%A6%AC%E9%A4%A8",
    },
    {
        "name": "Pickzone 匹克球場（凱旋館）",
        "district": "西屯區",
        "address": "台中市西屯區環中路二段300-4號",
        "hours": "24小時營業",
        "price": "約 $300~$600/時，臨打約 $150~$200",
        "line_url": "https://line.me/R/ti/p/@336xlhhb",
        "url": "https://www.google.com/maps/search/?api=1&query=Pickzone%E5%87%B1%E6%97%8B%E9%A4%A8",
    },
    {
        "name": "GooDink 匹克球俱樂部",
        "district": "西屯區",
        "address": "台中市西屯區甘河路108號",
        "hours": "09:00 – 23:00",
        "price": "場租/臨打收費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=GooDink%E5%8C%B9%E5%85%8B%E7%90%83%E4%bf%B1%E6%a8%82%E9%83%a8",
    },
    {
        "name": "臺中市朝馬國民運動中心",
        "district": "西屯區",
        "address": "臺中市西屯區朝貴路199號",
        "hours": "06:00 – 22:00",
        "price": "綜合球場依中心公告",
        "line_url": None,
        "url": "https://cmcsc.cyc.org.tw/",
    },
    {
        "name": "西大墩兒童運動中心",
        "district": "西屯區",
        "address": "臺中市西屯區福科二路111號",
        "hours": "06:00 – 22:00",
        "price": "依中心公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%A5%BF%E5%A4%A7%E5%A2%A9%E5%85%92%E7%AB%A5%E9%81%8B%E5%8B%95%E4%B8%AD%E5%BF%83",
    },
    {
        "name": "優漾複合運動會館",
        "district": "西屯區",
        "address": "臺中市西屯區福科路207號",
        "hours": "06:00 – 23:00",
        "price": "會員/租場收費",
        "line_url": None,
        "url": "https://www.allyoungsports.com/",
    },
    {
        "name": "逢甲大學體育館（綜合球場）",
        "district": "西屯區",
        "address": "台中市西屯區文華路100號",
        "hours": "依校方開放時間",
        "price": "依校方公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%80%A2%E7%94%B2%E5%A4%A7%E5%AD%B8%E9%AB%94%E8%82%B2%E9%A4%A8",
    },
    {
        "name": "西苑高中匹克球場",
        "district": "西屯區",
        "address": "台中市西屯區西苑路268號",
        "hours": "06:30 – 22:30",
        "price": "100~200",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%A5%BF%E8%8B%91%E9%AB%98%E4%B8%AD",
    },
    {
        "name": "福雅里社區活動中心",
        "district": "西屯區",
        "address": "台中市西屯區福雅路111號",
        "hours": "依社區公告",
        "price": "100~200",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E7%A6%8F%E9%9B%85%E9%87%8C%E6%B4%BB%E5%8B%95%E4%B8%AD%E5%BF%83",
    },
    # 南屯區
    {
        "name": "日落匹克球 (Sunset Pickleball)",
        "district": "南屯區",
        "address": "台中市南屯區嶺東路109-12號",
        "hours": "24小時營業",
        "price": "24H預約制（附借拍與球）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=Sunset+Pickleball+%E6%97%A5%E8%90%BD%E5%8C%B9%E5%85%8B%E7%90%83",
    },
    {
        "name": "LaLa Dink 匹克球俱樂部",
        "district": "南屯區",
        "address": "台中市南屯區文心南三路996巷1號",
        "hours": "24小時營業 / 預約制",
        "price": "Open Play約 $200~$250",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=LaLa+Dink+Pickleball",
    },
    {
        "name": "匹克王 (PICKLE KING)",
        "district": "南屯區",
        "address": "台中市南屯區環中路四段2號",
        "hours": "10:00 – 00:00",
        "price": "依低消與場租公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%8C%B9%E5%85%8B%E7%8E%8B+PICKLE+KING",
    },
    {
        "name": "嗨賴運動俱樂部 (Hi-Light)",
        "district": "南屯區",
        "address": "台中市南屯區龍富二路298號",
        "hours": "08:00 – 22:00",
        "price": "依館內公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%97%A8%E8%B3%B4%E9%81%8B%E5%8B%95%E4%bf%B1%E6%a8%82%E9%83%a8",
    },
    {
        "name": "臺中市南屯國民運動中心",
        "district": "南屯區",
        "address": "臺中市南屯區黎明路一段998號",
        "hours": "06:00 – 22:00",
        "price": "請見中心臨租公告",
        "line_url": None,
        "url": "https://hbsc.cyc.org.tw/",
    },
    {
        "name": "文心森林公園戶外運動場",
        "district": "南屯區",
        "address": "台中市南屯區文心路一段289號",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E6%96%87%E5%BF%83%E6%A3%AE%E6%9E%97%E5%85%AC%E5%9C%92",
    },
    # 北屯區
    {
        "name": "Pickle Park 匹克公園（北屯場）",
        "district": "北屯區",
        "address": "台中市北屯區敦和路125號",
        "hours": "08:00 – 22:00",
        "price": "依場租預約公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=Pickle+Park+%E5%8C%B9%E5%85%8B%E5%85%AC%E5%9C%92",
    },
    {
        "name": "臺中市國際網球中心（匹克球專用場）",
        "district": "北屯區",
        "address": "台中市北屯區祥順二路224號",
        "hours": "06:00 – 22:00",
        "price": "約 100~200元",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%87%BA%E4%B8%AD%E5%B8%82%E5%9C%8B%E9%9A%9B%E7%b6%b2%E7%90%83%E4%b8%ad%e5%bf%83",
    },
    {
        "name": "舊社公園匹克球場",
        "district": "北屯區",
        "address": "台中市北屯區松竹路二段59巷5號",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%88%8A%E7%A4%BE%E5%85%AC%E5%9C%92",
    },
    {
        "name": "四張犁公園匹克球場",
        "district": "北屯區",
        "address": "台中市北屯區松竹路一段1000號",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%9B%9B%E5%BC%B5%E7%A2%81%E5%85%AC%E5%9C%92",
    },
    {
        "name": "台中市游泳訓練中心綜合球場",
        "district": "北屯區",
        "address": "台中市北屯區景賢南一路26號",
        "hours": "06:00 – 22:00",
        "price": "依中心公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%8F%B0%E4%B8%AD%E5%B8%82%E6%B8%B8%E6%B3%B3%E8%A8%93%E7%B7%B4%E4%B8%AD%E5%BF%83",
    },
    # 東區
    {
        "name": "西雅圖室內匹克球俱樂部 (Seattle Pickleball Club)",
        "district": "東區",
        "address": "台中市東區環中東路五段52號",
        "hours": "24小時營業 / 線上預約制",
        "price": "線上場租（附免費借球拍與球）",
        "line_url": None,
        "url": "https://www.booknow.com.tw/seattlepickleball",
    },
    # 西區
    {
        "name": "PiCKLE & CHiLL（誠星勤美高空球場）",
        "district": "西區",
        "address": "台中市西區公益路68號15樓",
        "hours": "10:00 – 22:00",
        "price": "線上預約 / 房客優惠",
        "line_url": None,
        "url": "https://www.starhostelparklane.com/",
    },
    # 北區
    {
        "name": "臺中市北區國民運動中心",
        "district": "北區",
        "address": "臺中市北區崇德路一段55號",
        "hours": "06:00 – 22:00",
        "price": "依中心臨租公告（現場可租借球具）",
        "line_url": None,
        "url": "https://tndcsc.com.tw/",
    },
    {
        "name": "健行國小匹克球場",
        "district": "北區",
        "address": "台中市北區健行路201號",
        "hours": "課後及假日開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%81%A5%E8%A1%8C%E5%9C%8B%E5%B0%8F",
    },
    # 南區
    {
        "name": "長春國民暨兒童運動中心",
        "district": "南區",
        "address": "臺中市南區合作街46號",
        "hours": "06:00 – 22:00",
        "price": "依中心臨租公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%95%B7%E6%98%A5%E5%9C%8B%E6%B0%91%E6%9A%A8%E5%85%92%E7%AB%A5%E9%81%8B%E5%8B%95%E4%B8%AD%E5%BF%83",
    },
    {
        "name": "國立中興大學綜合體育館",
        "district": "南區",
        "address": "台中市南區興大路145號",
        "hours": "依校方公告開放時間",
        "price": "校內/社團租借公告",
        "line_url": None,
        "url": "https://osa.nchu.edu.tw/",
    },
    # 大里區
    {
        "name": "大里康橋匹克球場（國光公園 / 二二八公園內）",
        "district": "大里區",
        "address": "台中市大里區興大南街43號",
        "hours": "06:00 – 22:00",
        "price": "免費（台中示範基地）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%A4%A7%E9%87%8C%E5%8C%B9%E5%85%8B%E7%90%83%E5%A0%B4",
    },
    {
        "name": "大里國民暨兒童運動中心",
        "district": "大里區",
        "address": "臺中市大里區國光路一段258號",
        "hours": "06:00 – 22:00",
        "price": "依中心臨租公告",
        "line_url": None,
        "url": "https://dlcsc.cyc.org.tw/",
    },
    {
        "name": "大里樹王里橋下運動場地",
        "district": "大里區",
        "address": "台中市大里區中投西路三段橋下",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E4%B8%AD%E6%8A%95%E5%85%AC%E8%B7%AF%E6%A9%8B%E4%B8%8B",
    },
    {
        "name": "霧社公園運動場",
        "district": "大里區",
        "address": "台中市大里區東昇路591巷",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%9C%A7%E7%A4%BE%E5%85%AC%E5%9C%92",
    },
    # 太平區
    {
        "name": "太平國民暨兒童運動中心",
        "district": "太平區",
        "address": "台中市太平區中山路二段433號",
        "hours": "06:00 – 22:00",
        "price": "依中心公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%A4%AA%E5%B9%B3%E5%9C%8B%E6%B0%91%E6%9A%A8%E5%85%92%E7%AB%A5%E9%81%8B%E5%8B%95%E4%B8%AD%E5%BF%83",
    },
    {
        "name": "坪林森林公園綜合運動場",
        "district": "太平區",
        "address": "台中市太平區中山路二段418號",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%9D%AA%E6%9E%97%E6%A3%AE%E6%9E%97%E5%85%AC%E5%9C%92",
    },
    # 豐原區
    {
        "name": "豐原國民暨兒童運動中心",
        "district": "豐原區",
        "address": "臺中市豐原區豐裕路8號",
        "hours": "06:00 – 22:00",
        "price": "請見中心臨租公告",
        "line_url": None,
        "url": "https://www.facebook.com/FYCSC04/",
    },
    {
        "name": "豐原武明山公園球場",
        "district": "豐原區",
        "address": "臺中市豐原區南陽路59巷3-2號",
        "hours": "19:30 – 22:00",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%B1%90%E5%8E%9F%E6%AD%A6%E6%98%8E%E5%B1%B1%E5%85%AC%E5%9C%92%E7%90%83%E5%A0%B4",
    },
    {
        "name": "豐原國四高架橋下球場",
        "district": "豐原區",
        "address": "台中市豐原區國道四號高架橋下",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%9C%8B%E9%81%93%E5%9B%9B%E8%99%9F%E9%AB%98%E6%9E%B6%E6%A9%8B%E4%B8%8B%E7%90%83%E5%A0%B4",
    },
    # 后里區
    {
        "name": "NAPA Pickleball 麗寶館（室內旗艦館）",
        "district": "后里區",
        "address": "台中市后里區福容路201號（麗寶OUTLET MALL A區 2F）",
        "hours": "10:00 – 21:30",
        "price": "依時段場租/臨打約 $200~$300",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=NAPA+Pickleball+%E9%BA%97%E5%AF%B6%E9%A4%A8",
    },
    # 潭子區
    {
        "name": "一一匹克 (YIYI PICKLE)",
        "district": "潭子區",
        "address": "台中市潭子區大富路三段165巷12-18號",
        "hours": "24小時營業",
        "price": "場租約 $300~$500/時",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E4%B8%80%E4%B8%80%E5%8C%B9%E5%85%8B+YIYI+PICKLE",
    },
    {
        "name": "潭子國民暨兒童運動中心",
        "district": "潭子區",
        "address": "台中市潭子區勝利路140號",
        "hours": "06:00 – 22:00",
        "price": "請見中心臨租公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E6%BD%AD%E5%AD%90%E5%9C%8B%E6%B0%91%E9%81%8B%E5%8B%95%E4%B8%AD%E5%BF%83",
    },
    # 烏日區
    {
        "name": "匹克領域 (PB-Club)",
        "district": "烏日區",
        "address": "台中市烏日區溪南路一段348巷33號",
        "hours": "08:00 – 23:00 / 預約制",
        "price": "依預約場租公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%8C%B9%E5%85%8B%E9%A0%98%E5%9F%9F+PB-Club",
    },
    {
        "name": "Hype Pick Club 熱潮匹克球俱樂部",
        "district": "烏日區",
        "address": "台中市烏日區溪南路一段680巷450弄12號",
        "hours": "09:00 – 23:00",
        "price": "依場租/臨打公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=Hype+Pick+Club+%E7%86%B1%E6%BD%AE%E5%8C%B9%E5%85%8B%E7%90%83",
    },
    # 霧峰區
    {
        "name": "霧峰國道三號橋下匹克球場",
        "district": "霧峰區",
        "address": "台中市霧峰區四德路498巷旁（國道三號高架橋下）",
        "hours": "全天開放",
        "price": "免費公立場地（共3面球場）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%9C%A7%E5%B3%B0%E5%9C%8B%E9%81%93%E4%B8%89%E8%99%9F%E6%A9%8B%E4%B8%8B%E5%8C%B9%E5%85%8B%E7%90%83%E5%A0%B4",
    },
    {
        "name": "朝陽科技大學綜合體育館",
        "district": "霧峰區",
        "address": "台中市霧峰區吉峰東路168號",
        "hours": "依校方公告",
        "price": "校內/社團租借公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E6%9C%9D%E9%99%BD%E7%A7%91%E6%8A%80%E5%A4%A7%E5%AD%B8%E9%AB%94%E8%82%B2%E9%A4%A8",
    },
    # 清水區
    {
        "name": "臺中市清水國民暨兒童運動中心",
        "district": "清水區",
        "address": "台中市清水區鎮政路358號",
        "hours": "06:00 – 22:00",
        "price": "請見中心臨租公告（3F綜合球場）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%87%BA%E4%B8%AD%E5%B8%82%E6%B8%85%E6%B0%B4%E5%9C%8B%E6%B0%91%E6%9A%A8%E5%85%92%E7%AB%A5%E9%81%8B%E5%8B%95%E4%B8%AD%E5%BF%83",
    },
    # 沙鹿區
    {
        "name": "XC.Pickleball 沙鹿室內匹克球俱樂部",
        "district": "沙鹿區",
        "address": "台中市沙鹿區東英路56巷60號",
        "hours": "08:00 – 22:00",
        "price": "約 $150~$250 / 臨打或包場",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=XC.Pickleball+%E6%B2%99%E9%B9%BF",
    },
    {
        "name": "臺中市港區運動公園",
        "district": "沙鹿區",
        "address": "台中市沙鹿區自強路301號",
        "hours": "06:00 – 22:00",
        "price": "依園區公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%87%BA%E4%B8%AD%E5%B8%82%E6%B8%AF%E5%8D%80%E9%81%8B%E5%8B%95%E5%85%AC%E5%9C%92",
    },
    {
        "name": "靜宜大學若望保祿二世體育館",
        "district": "沙鹿區",
        "address": "台中市沙鹿區臺灣大道七段200號",
        "hours": "依校方公告",
        "price": "校內/社團租借公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%9D%9C%E5%AE%9C%E5%A4%A7%E5%AD%B8%E9%AB%94%E8%82%B2%E9%A4%A8",
    },
    # 梧棲區
    {
        "name": "梧棲文高8公有匹克球場",
        "district": "梧棲區",
        "address": "台中市梧棲區文昌路與民安路口",
        "hours": "全天開放（附夜間照明）",
        "price": "免費（海線首座公有專用球場）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E6%A2%A7%E6%A3%B2%E6%96%87%E9%AB%988%E5%8C%B9%E5%85%8B%E7%90%83%E5%A0%B4",
    },
    {
        "name": "優選港合運動會館",
        "district": "梧棲區",
        "address": "台中市梧棲區港埠路一段888號",
        "hours": "06:00 – 00:00",
        "price": "100~200",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%84%AA%E9%81%B8%E6%B8%AF%E5%90%88%E9%81%8B%E5%8B%95%E6%9C%83%E9%A4%A8",
    },
    # 龍井區
    {
        "name": "龍井匹克球場",
        "district": "龍井區",
        "address": "台中市龍井區竹師路二段112巷附近",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E9%BE%8D%E4%BA%95%E5%8C%B9%E5%85%8B%E7%90%83%E5%A0%B4",
    },
    # 大安區
    {
        "name": "大安西濱橋下匹克球場",
        "district": "大安區",
        "address": "台中市大安區西濱快速公路高架橋下",
        "hours": "全天開放",
        "price": "免費（橋下遮蔭避雨，2面球場）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%A4%A7%E5%AE%89%E8%A5%BF%E6%BF%B1%E6%A9%8B%E4%B8%8B%E5%8C%B9%E5%85%8B%E7%90%83%E5%A0%B4",
    },
    # 大甲區
    {
        "name": "大甲體育場匹克球場",
        "district": "大甲區",
        "address": "台中市大甲區大安港路2號",
        "hours": "06:00 – 21:00",
        "price": "免費公立場地（大甲獅子盃主場）",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%A4%A7%E7%94%B2%E9%AB%94%E8%82%B2%E5%A0%B4",
    },
    # 神岡區
    {
        "name": "神岡國四高架橋下匹克球場",
        "district": "神岡區",
        "address": "台中市神岡區三民路/國道四號高架橋下",
        "hours": "全天開放",
        "price": "免費",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E7%A5%9E%E5%B2%A1%E5%9C%8B%E5%9B%9B%E6%A9%8B%E4%B8%8B%E7%90%83%E5%A0%B4",
    },
    {
        "name": "豐神 AI 智能運動館",
        "district": "神岡區",
        "address": "台中市神岡區神洲路130巷21弄5號",
        "hours": "24小時營業",
        "price": "智慧預約場租",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E8%B1%90%E7%A5%9EAI%E6%99%BA%E8%83%BD%E7%BE%BD%E7%90%83%E9%A4%A8",
    },
    # 大雅區
    {
        "name": "水舞酷動匹克球基地",
        "district": "大雅區",
        "address": "台中市大雅區民生路三段492號",
        "hours": "08:00 – 22:00",
        "price": "依會館公告",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E6%B0%B4%E8%88%9E%E9%85%B7%E5%8B%95",
    },
    # 大肚區
    {
        "name": "大肚文昌匹克球活動中心",
        "district": "大肚區",
        "address": "台中市大肚區文昌路二段770號",
        "hours": "依開放公告",
        "price": "100~200",
        "line_url": None,
        "url": "https://www.google.com/maps/search/?api=1&query=%E5%A4%A7%E8%82%9A%E5%8D%80%E6%96%87%E6%98%8C%E8%B7%AF%E4%BA%8C%E6%AE%B5770%E8%99%9F",
    },
]


def merge_verified_taichung_courts(all_courts_data: dict):
    """將全面完善的台中市各區指標球場清單合併至台中資料中。"""
    if "taichung" not in all_courts_data:
        all_courts_data["taichung"] = {
            "name": "台中",
            "url": f"{BASE_URL}/taichung/",
            "courts": []
        }

    existing_courts = all_courts_data["taichung"]["courts"]
    added_count = 0
    updated_count = 0

    for item in TAICHUNG_VERIFIED_COURTS:
        name = item["name"]
        addr = item.get("address", "")
        found_idx = -1

        for idx, ex in enumerate(existing_courts):
            ex_name = ex.get("name", "")
            ex_addr = ex.get("address", "")
            if (name in ex_name or ex_name in name) and len(set(name) & set(ex_name)) >= 3:
                found_idx = idx
                break
            if addr and ex_addr and addr == ex_addr:
                found_idx = idx
                break

        if found_idx >= 0:
            existing = existing_courts[found_idx]
            existing["district"] = item.get("district", existing.get("district"))
            if "maps" in item.get("url", "") or not existing.get("url"):
                existing["url"] = item.get("url", existing.get("url"))
            if item.get("line_url") and not existing.get("line_url"):
                existing["line_url"] = item.get("line_url")
            if item.get("hours") and existing.get("hours") in ["未提供", "Closed", "12:00 上午 – 12:00 上午"]:
                existing["hours"] = item.get("hours")
            if item.get("price") and existing.get("price") in ["未提供", "100~200"]:
                existing["price"] = item.get("price")
            if item.get("address") and (not existing.get("address") or len(item["address"]) > len(ex_addr)):
                existing["address"] = item["address"]
            updated_count += 1
        else:
            existing_courts.append(dict(item))
            added_count += 1

    print(f"  🏆 [台中球場深度完善] 新增 {added_count} 筆、優化更新 {updated_count} 筆，台中目前共計 {len(existing_courts)} 所球場！")


def save_courts_data(all_courts_data: dict):
    """儲存快照 json 與 csv 檔案。"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    json_path = os.path.join(data_dir, "courts_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_courts_data, f, ensure_ascii=False, indent=2)
    print(f"🎉 球場快照資料已成功儲存至 {json_path}")

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

    # 補充合併教育部體育署公立運動場館與全台國民運動中心
    sa_courts = scrape_sa_iplay_courts()
    merge_sa_courts_into_data(all_courts_data, sa_courts)

    # 深度完善台中市各區球場
    merge_verified_taichung_courts(all_courts_data)

    # 1. 寫入本地快照與 CSV
    save_courts_data(all_courts_data)

    # 2. 同步至 Google Sheets
    sync_to_google_sheets(all_courts_data)


def sync_to_google_sheets(all_courts_data: dict) -> bool:
    """將球場資料同步至 Google Sheets (gid=1386987707)。"""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        print("ℹ️ 未偵測到 GOOGLE_CREDENTIALS 環境變數，跳過線上 Google Sheets 寫入。（在 GitHub Actions 執行時將會自動同步）")
        return False

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        print(f"🔄 正在連線至 Google Sheets 並進行球場資料同步 (GID: {COURTS_SHEET_GID})...")
        creds_dict = json.loads(creds_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(SHEET_ID)

        # 根據 GID 尋找目標工作表
        worksheet = None
        for ws in sh.worksheets():
            if str(ws.id) == str(COURTS_SHEET_GID):
                worksheet = ws
                break

        if not worksheet:
            # 備援：尋找名稱中包含「球場」或「court」的工作表
            for ws in sh.worksheets():
                if "球場" in ws.title or "court" in ws.title.lower():
                    worksheet = ws
                    break

        if not worksheet:
            print(f"[錯誤] 找不到 GID 為 {COURTS_SHEET_GID} 的工作表！")
            return False

        header = ["縣市", "行政區", "球場名稱", "營業時間", "收費資訊", "LINE群連結", "詳情網址", "詳細地址"]
        all_values = worksheet.get_all_values()

        # 若工作表為空，先寫入標題列
        if not all_values or len(all_values) == 0:
            worksheet.append_row(header)
            all_values = [header]
        elif len(all_values) == 1 and all(c.strip() == "" for c in all_values[0]):
            worksheet.update("A1:H1", [header])
            all_values = [header]

        # 收集現有球場比對鍵（以「縣市::球場名稱」或「詳情網址」）
        existing_keys = set()
        for row in all_values[1:]:
            if row:
                c_name = row[0].strip() if len(row) > 0 else ""
                t_name = row[2].strip() if len(row) > 2 else ""
                u_link = row[6].strip() if len(row) > 6 else ""
                if c_name and t_name:
                    existing_keys.add(f"{c_name}::{t_name}")
                if u_link:
                    existing_keys.add(u_link)

        # 整理所有要寫入的球場
        new_rows = []
        for slug, info in all_courts_data.items():
            county_display = info.get("name", slug)
            for c in info.get("courts", []):
                court_name = c.get("name", "").strip()
                dist_name = c.get("district", "市區").strip()
                hours_val = c.get("hours", "未提供").strip()
                price_val = c.get("price", "未提供").strip()
                line_val = c.get("line_url", "") or ""
                url_val = c.get("url", "") or ""
                addr_val = c.get("address", "") or ""

                key = f"{county_display}::{court_name}"
                if key in existing_keys or (url_val and url_val in existing_keys):
                    continue

                new_rows.append([
                    county_display,
                    dist_name,
                    court_name,
                    hours_val,
                    price_val,
                    line_val,
                    url_val,
                    addr_val
                ])
                existing_keys.add(key)
                if url_val:
                    existing_keys.add(url_val)

        if new_rows:
            # 若為首次全量寫入或批次寫入
            worksheet.append_rows(new_rows)
            print(f"🎉 成功寫入 {len(new_rows)} 筆球場資料至 Google Sheets (分頁 GID: {COURTS_SHEET_GID})！")
        else:
            print(f"✅ Google Sheets 上的球場資料已是最新，無需新增。")

        return True
    except Exception as e:
        print(f"[錯誤] 同步球場資料至 Google Sheets 失敗: {e}")
        return False


if __name__ == "__main__":
    import sys
    if "--sync-only" in sys.argv:
        # 直接讀取本機快照同步到 Google Sheets
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        json_path = os.path.join(data_dir, "courts_data.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            print(f"已讀取本地快照 {json_path}...")
            # 輕量即時更新體育署場館
            sa_courts = scrape_sa_iplay_courts()
            merge_sa_courts_into_data(cached_data, sa_courts)
            # 深度完善台中市各區球場
            merge_verified_taichung_courts(cached_data)
            save_courts_data(cached_data)
            sync_to_google_sheets(cached_data)
        else:
            print(f"找不到本地快照 {json_path}！")
    else:
        main()

