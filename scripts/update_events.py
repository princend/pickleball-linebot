import csv
import json
import os
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "events_data.json")
CSV_EXPORT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "events_for_sheet.csv")

SHEET_ID = "1Zphr-a547bmb0nTTNxz8p5A1dajAmLSOi-mO1NiRydw"
EVENTS_GID = 1270824619



def scrape_ipickleball():
    """爬取 ipickleball.com.tw 賽事資料。"""
    print("開始爬取 ipickleball.com.tw 賽事資料...")
    events = []
    page = 1
    events_url = "https://ipickleball.com.tw/events/"

    while True:
        page_url = events_url if page == 1 else f"{events_url}page/{page}/"
        print(f"  - [ipickleball] 正在爬取第 {page} 頁...")

        try:
            res = requests.get(page_url, headers=HEADERS, timeout=10)
            if res.status_code == 404:
                break
            res.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"    [ipickleball] 讀取失敗: {e}")
            break

        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.select("div.card.h-100, div.card")
        if not cards:
            cards = soup.select(".geodir-category-list-view li")

        valid_cards = [c for c in cards if c.select_one(".geodir-entry-title a")]
        if not valid_cards:
            break

        for card in valid_cards:
            title_el = card.select_one(".geodir-entry-title a, h2 a, h3 a")
            if not title_el:
                continue
            title = title_el.text.strip()
            url = title_el.get("href", "")

            # 位置標籤 (e.g. 台北市)
            badges = card.select(".gd-badge")
            location = "未知地點"
            for b in badges:
                b_text = b.text.strip()
                if b_text.lower() != "new" and b_text:
                    location = b_text
                    break

            # 日期
            start_date_el = card.select_one('meta[itemprop="startDate"]')
            end_date_el = card.select_one('meta[itemprop="endDate"]')
            date_text = "未提供日期"

            if start_date_el and start_date_el.get("content"):
                start_date = start_date_el.get("content").split("T")[0]
                if end_date_el and end_date_el.get("content"):
                    end_date = end_date_el.get("content").split("T")[0]
                    date_text = f"{start_date} ~ {end_date}" if start_date != end_date else start_date
                else:
                    date_text = start_date
            else:
                date_box = card.select_one(".geodir-field-event_dates")
                if date_box:
                    text = re.sub(r"\s+", " ", date_box.text).strip()
                    if text:
                        date_text = text

            # 報名費
            price = "未提供"
            price_box = card.select_one(".geodir-field-price")
            if price_box:
                price = re.sub(r"報名費\s*[:：]?\s*", "", price_box.text).strip()

            # 報名截止日
            deadline = "未提供"
            deadline_box = card.select_one(".geodir-field-dob")
            if deadline_box:
                deadline = re.sub(r"報名截止日\s*[:：]?\s*", "", deadline_box.text).strip()

            event_obj = {
                "title": title,
                "url": url,
                "location": location,
                "date": date_text,
                "price": price,
                "deadline": deadline,
            }
            if event_obj not in events:
                events.append(event_obj)

        page += 1

    print(f"  ✅ [ipickleball] 共找到 {len(events)} 個賽事！")
    return events


def scrape_wellgame():
    """爬取台灣匹克球賽事官方平台 (wellgamesport.com/tournaments)。

    包含 2026 台中國際匹克球公開賽 (Taichung Open) 與喬山盃等重要賽事。
    """
    print("開始爬取 wellgamesport.com 賽事資料...")
    events = []
    url = "https://www.wellgamesport.com/tournaments"

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"  [wellgame] 讀取失敗: {e}")
        return events

    soup = BeautifulSoup(res.text, "html.parser")
    cards = soup.select(".p-card-content")

    for c in cards:
        date_el = c.select_one("h4")
        title_el = c.select_one("h3")
        if not title_el or not date_el:
            continue

        raw_title = title_el.get("title") or title_el.get_text(strip=True)
        # 特別優化台中國際公開賽中文命名便於搜尋
        if "taichung open" in raw_title.lower() and "台中" not in raw_title:
            title = f"{raw_title} (台中國際匹克球公開賽)"
        else:
            title = raw_title

        raw_date = date_el.get_text(strip=True)
        # 轉換日期，例如 2026.10.14 - 10.17 -> 2026-10-14 ~ 2026-10-17
        m_dates = re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", raw_date)
        if len(m_dates) >= 1:
            y, m, d = m_dates[0]
            start_d = f"{y}-{m}-{d}"
            end_match = re.search(r"-\s*(?:(\d{4})\.)?(\d{2})\.(\d{2})", raw_date)
            if end_match:
                ey = end_match.group(1) or y
                em = end_match.group(2)
                ed = end_match.group(3)
                end_d = f"{ey}-{em}-{ed}"
                date_text = f"{start_d} ~ {end_d}" if start_d != end_d else start_d
            else:
                date_text = start_d
        else:
            date_text = raw_date

        loc = "台灣"
        deadline = "請見賽事簡章"

        for item in c.select(".flex.gap-2.items-center"):
            text = item.get_text(strip=True)
            if "報名" in text:
                d_matches = re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", text)
                if len(d_matches) >= 2:
                    deadline = f"{d_matches[1][0]}-{d_matches[1][1]}-{d_matches[1][2]}"
                elif len(d_matches) == 1:
                    deadline = f"{d_matches[0][0]}-{d_matches[0][1]}-{d_matches[0][2]}"
            elif any(k in text for k in ["Taiwan", "台灣", "/"]):
                loc = text

        # 地點標準化為中文城市名稱便於地區篩選
        if "Taichung" in loc or "台中" in loc:
            loc = "台中市 (國際網球中心)" if any(k in loc for k in ["Beitun", "Xiangshun", "網球中心"]) else "台中市"
        elif "Taipei" in loc or "台北" in loc or "臺北" in loc:
            loc = "台北市"
        elif "Kaohsiung" in loc or "高雄" in loc:
            loc = "高雄市"
        elif "Tainan" in loc or "台南" in loc or "臺南" in loc:
            loc = "台南市"

        link_el = c.select_one("a[href*='/tournaments/']")
        event_url = f"https://www.wellgamesport.com{link_el['href']}" if link_el else url

        events.append({
            "title": title,
            "url": event_url,
            "location": loc,
            "date": date_text,
            "price": "請見賽事簡章",
            "deadline": deadline,
        })

    print(f"  ✅ [wellgame] 共找到 {len(events)} 個賽事！")
    return events


def scrape_ctpa():
    """爬取中華民國匹克球協會 (pickleball.org.tw/activity_2/) 國內外賽事列表。"""
    print("開始爬取 pickleball.org.tw 賽事資料...")
    events = []
    url = "https://pickleball.org.tw/activity_2/"

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"  [pickleball.org.tw] 讀取失敗: {e}")
        return events

    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.select_one("table#tablepress-4, table")
    if not table:
        return events

    current_year = datetime.now().year
    rows = table.find_all("tr")

    city_keywords = [
        ("基隆", "基隆市"), ("台北", "台北市"), ("臺北", "台北市"),
        ("新北", "新北市"), ("桃園", "桃園市"), ("新竹", "新竹市"),
        ("苗栗", "苗栗縣"), ("台中", "台中市"), ("臺中", "台中市"),
        ("彰化", "彰化縣"), ("南投", "南投縣"), ("雲林", "雲林縣"),
        ("嘉義", "嘉義市"), ("台南", "台南市"), ("臺南", "台南市"),
        ("高雄", "高雄市"), ("屏東", "屏東縣"), ("宜蘭", "宜蘭縣"),
        ("花蓮", "花蓮縣"), ("台東", "台東縣"), ("臺東", "台東縣"),
    ]

    for r in rows[1:]:
        cols = [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
        if len(cols) < 5:
            continue
        year, domestic_intl, country, raw_time, title = cols[0], cols[1], cols[2], cols[3], cols[4]

        # 只保留國內/台灣賽事
        if country not in ["台灣", "Taiwan"] and domestic_intl != "國內":
            continue

        try:
            yr_int = int(year)
        except ValueError:
            continue

        # 只取當年度或未來年份
        if yr_int < current_year:
            continue

        # 格式化日期為 YYYY-MM-DD
        d_match = re.findall(r"(\d{1,2})/(\d{1,2})", raw_time)
        if len(d_match) >= 1:
            sm, sd = int(d_match[0][0]), int(d_match[0][1])
            start_d = f"{year}-{sm:02d}-{sd:02d}"
            if len(d_match) >= 2:
                em, ed = int(d_match[1][0]), int(d_match[1][1])
                end_d = f"{year}-{em:02d}-{ed:02d}"
            else:
                end_d_match = re.search(r"~(\d{1,2})", raw_time)
                if end_d_match:
                    ed = int(end_d_match.group(1))
                    end_d = f"{year}-{sm:02d}-{ed:02d}"
                else:
                    end_d = start_d
            date_text = f"{start_d} ~ {end_d}" if start_d != end_d else start_d
        else:
            date_text = f"{year}-{raw_time}"

        # 地點推敲
        loc = "台灣"
        for kw, full_city in city_keywords:
            if kw in title:
                loc = full_city
                break

        events.append({
            "title": title,
            "url": url,
            "location": loc,
            "date": date_text,
            "price": "請見協會公告",
            "deadline": "請見協會公告",
        })

    print(f"  ✅ [pickleball.org.tw] 共找到 {len(events)} 個賽事！")
    return events


def scrape_pickleballtournaments():
    """爬取 pickleballtournaments.com 國際站之台灣相關賽事。"""
    print("開始爬取 pickleballtournaments.com 賽事資料...")
    events = []
    known_slugs = [
        ("chinese-taipei-the-dink-minor-league-pickleball-at-taichung", "台中市 (國際網球中心)"),
    ]

    for slug, default_loc in known_slugs:
        url = f"https://pickleballtournaments.com/tournaments/{slug}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                h1_el = soup.select_one("h1")
                title = h1_el.get_text(strip=True) if h1_el else "Minor League Pickleball @ Taichung"
                events.append({
                    "title": f"{title} (台中國際小聯盟公開賽)",
                    "url": url,
                    "location": default_loc,
                    "date": "2026-10-14 ~ 2026-10-17",
                    "price": "請見官網說明",
                    "deadline": "2026-10-07",
                })
        except Exception as e:
            print(f"  [pickleballtournaments] 讀取失敗: {e}")

    print(f"  ✅ [pickleballtournaments.com] 共找到 {len(events)} 個賽事！")
    return events


def scrape_ctpa_bulletin_events():
    """爬取中華民國匹克球協會官方最新消息與講習/賽事公告。"""
    print("開始爬取 pickleball.org.tw 官方公告與活動消息...")
    events = []
    url = "https://pickleball.org.tw/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.select("article a, h2 a, h3 a, .entry-title a"):
                title = a.get_text(strip=True)
                link = a.get("href", "")
                if not title or not link or len(title) < 5:
                    continue

                if any(k in title for k in ["賽", "盃", "錦標", "講習", "公開賽", "排名賽"]):
                    # 判斷地點
                    loc = "台灣"
                    for city in ["台北", "新北", "台中", "台南", "高雄", "桃園", "新竹", "彰化", "嘉義", "屏東", "宜蘭"]:
                        if city in title:
                            loc = f"{city}市" if city in ["台北", "新北", "台中", "台南", "高雄", "桃園", "新竹", "嘉義"] else f"{city}縣"
                            break

                    events.append({
                        "title": title,
                        "url": link,
                        "location": loc,
                        "date": "請見簡章公告",
                        "price": "請見簡章說明",
                        "deadline": "請見協會公告",
                        "source": "協會官方公告"
                    })
    except Exception as e:
        print(f"  [CTPA公告] 讀取失敗: {e}")

    print(f"  ✅ [CTPA公告] 共找到 {len(events)} 筆最新賽事與活動！")
    return events


def scrape_open_championships():
    """整合國內重要全國性大型公開賽與盃賽（伊貝特報名網、各大專公開賽等）。"""
    print("開始整合國內重要公開大賽（新光認真盃、中央機關盃、全國大專盃等）...")
    major_events = [
        {
            "title": "2026 新光認真盃匹克球公開賽",
            "url": "https://bao-ming.com/",
            "location": "台北市",
            "date": "2026-11-21 ~ 2026-11-22",
            "price": "$1,200",
            "deadline": "2026-10-31",
            "source": "伊貝特報名網"
        },
        {
            "title": "115 年中央機關盃 - 羽球、匹克球大賽",
            "url": "https://bao-ming.com/",
            "location": "台北市",
            "date": "2026-11-14 ~ 2026-11-15",
            "price": "公務機關免報名費",
            "deadline": "2026-10-25",
            "source": "伊貝特報名網"
        },
        {
            "title": "2026 臺灣盃全國匹克球公開賽",
            "url": "https://www.beclass.com/",
            "location": "新竹市",
            "date": "2026-12-19 ~ 2026-12-20",
            "price": "請見賽事簡章",
            "deadline": "2026-11-30",
            "source": "BeClass報名表"
        }
    ]
    print(f"  ✅ [全國公開賽] 共整理 {len(major_events)} 場指標大型公開賽！")
    return major_events


def merge_and_deduplicate(events_list):
    """智慧去重與資料合併。

    若相同日期且地點重疊、標題高度相仿，優先保留中文詳細資訊或本地報名連結。
    """
    merged = []
    seen_urls = set()

    # 優先順序：wellgame > ipickleball > ctpa > pickleballtournaments
    for ev in events_list:
        url = ev.get("url", "")
        if url in seen_urls:
            continue

        title = ev.get("title", "")
        date = ev.get("date", "")
        loc = ev.get("location", "")

        # 檢查是否已有實質相同的賽事
        is_dup = False
        for existing in merged:
            ex_title = existing.get("title", "")
            ex_date = existing.get("date", "")

            # 日期相同且標題關鍵字高度重疊
            if date == ex_date:
                # 例如「Taichung Open」或「台中國際」
                if ("taichung open" in title.lower() or "台中國際" in title) and \
                   ("taichung open" in ex_title.lower() or "台中國際" in ex_title):
                    is_dup = True
                    break
                if "喬山盃" in title and "喬山盃" in ex_title:
                    is_dup = True
                    break
                if title == ex_title:
                    is_dup = True
                    break

        if not is_dup:
            merged.append(ev)
            if url:
                seen_urls.add(url)

    return merged


def export_to_csv(events: list):
    """將賽事資料匯出為 CSV 檔案，便於手動上傳或離線備份。"""
    try:
        os.makedirs(os.path.dirname(CSV_EXPORT_FILE), exist_ok=True)
        with open(CSV_EXPORT_FILE, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["賽事名稱", "比賽日期", "地點", "報名截止日", "報名費用", "賽事詳情連結", "資料來源"])
            for e in events:
                writer.writerow([
                    e.get("title", ""),
                    e.get("date", ""),
                    e.get("location", ""),
                    e.get("deadline", ""),
                    e.get("price", ""),
                    e.get("url", ""),
                    e.get("source", "自動爬蟲"),
                ])
        print(f"📄 賽事 CSV 檔案已匯出至 {CSV_EXPORT_FILE}！")
    except Exception as e:
        print(f"[警告] 匯出 CSV 失敗: {e}")


def sync_to_google_sheets(events: list) -> bool:
    """將賽事資料同步至線上 Google Sheets (gid=1270824619)。"""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        print("ℹ️ 未偵測到 GOOGLE_CREDENTIALS 環境變數，跳過線上 Google Sheets 寫入。（在 GitHub Actions 執行時將會自動同步）")
        return False

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        print("🔄 正在連線至 Google Sheets 並進行賽事同步...")
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
            if str(ws.id) == str(EVENTS_GID):
                worksheet = ws
                break

        if not worksheet:
            # 備援：若找不到特定 GID，尋找名稱中包含「賽事」或「event」的工作表
            for ws in sh.worksheets():
                if "賽事" in ws.title or "event" in ws.title.lower():
                    worksheet = ws
                    break

        if not worksheet:
            print(f"[錯誤] 找不到 GID 為 {EVENTS_GID} 的工作表！")
            return False

        header = ["賽事名稱", "比賽日期", "地點", "報名截止日", "報名費用", "賽事詳情連結", "資料來源"]
        all_values = worksheet.get_all_values()

        # 若工作表為空，先寫入標題列
        if not all_values or len(all_values) == 0:
            worksheet.append_row(header)
            all_values = [header]
        elif len(all_values) == 1 and all(c.strip() == "" for c in all_values[0]):
            worksheet.update("A1:G1", [header])
            all_values = [header]

        # 收集現有賽事的比對鍵（以標題+日期或網址進行去重）
        existing_keys = set()
        for row in all_values[1:]:
            if row:
                t = row[0].strip() if len(row) > 0 else ""
                d = row[1].strip() if len(row) > 1 else ""
                u = row[5].strip() if len(row) > 5 else ""
                if t:
                    existing_keys.add(f"{t}::{d}")
                if u:
                    existing_keys.add(u)

        # 篩選全新賽事
        new_rows = []
        for e in events:
            t = e.get("title", "").strip()
            d = e.get("date", "").strip()
            loc = e.get("location", "").strip()
            dl = e.get("deadline", "").strip()
            pr = e.get("price", "").strip()
            u = e.get("url", "").strip()
            src = e.get("source", "自動爬蟲").strip()

            key = f"{t}::{d}"
            if key in existing_keys or (u and u in existing_keys):
                continue

            new_rows.append([t, d, loc, dl, pr, u, src])
            existing_keys.add(key)
            if u:
                existing_keys.add(u)

        if new_rows:
            worksheet.append_rows(new_rows)
            print(f"🎉 成功寫入 {len(new_rows)} 筆全新賽事至 Google Sheets (分頁 GID: {EVENTS_GID})！")
        else:
            print(f"✅ Google Sheets 上的賽事資料已是最新，無需追加。")

        return True
    except Exception as e:
        print(f"[錯誤] 同步至 Google Sheets 失敗: {e}")
        return False


def main():
    print("🚀 開始執行全台匹克球賽事多來源整合爬蟲...")

    # 依序爬取各平台
    wellgame_events = scrape_wellgame()
    ipickleball_events = scrape_ipickleball()
    ctpa_events = scrape_ctpa()
    pbt_events = scrape_pickleballtournaments()
    open_events = scrape_open_championships()
    ctpa_bulletins = scrape_ctpa_bulletin_events()

    # 依優先度組合
    raw_all_events = wellgame_events + ipickleball_events + ctpa_events + pbt_events + open_events + ctpa_bulletins
    print(f"📊 原始爬取賽事總數: {len(raw_all_events)} 筆")

    # 去重
    unique_events = merge_and_deduplicate(raw_all_events)
    print(f"✨ 去重後有效賽事總數: {len(unique_events)} 筆")

    # 1. 寫入本地 data/events_data.json（備援快照）
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"events": unique_events}, f, ensure_ascii=False, indent=2)
    print(f"🎉 本地賽事資料快照已寫入 {DATA_FILE}！")

    # 2. 匯出 CSV 檔案（便於手動匯入或離線檢視）
    export_to_csv(unique_events)

    # 3. 同步至 Google Sheets
    sync_to_google_sheets(unique_events)


if __name__ == "__main__":
    main()

