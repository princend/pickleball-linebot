import json
import os
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
}
EVENTS_URL = "https://ipickleball.com.tw/events/"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "events_data.json")

def main():
    print("開始爬取 ipickleball.com.tw 賽事資料...")
    events = []
    page = 1
    
    while True:
        page_url = EVENTS_URL if page == 1 else f"{EVENTS_URL}page/{page}/"
        print(f"  - 正在爬取第 {page} 頁...")
        
        try:
            res = requests.get(page_url, headers=HEADERS, timeout=10)
            if res.status_code == 404:
                break
            res.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"    讀取失敗: {e}")
            break
            
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.select("div.card.h-100, div.card")
        if not cards:
            cards = soup.select(".geodir-category-list-view li")
            
        # 排除可能不是賽事的卡片
        valid_cards = [c for c in cards if c.select_one('.geodir-entry-title a')]
        if not valid_cards:
            break
            
        for card in valid_cards:
            title_el = card.select_one('.geodir-entry-title a, h2 a, h3 a')
            if not title_el:
                continue
            title = title_el.text.strip()
            url = title_el.get('href', '')
            
            # 位置標籤 (e.g. 台北市)
            badge = card.select_one('.gd-badge')
            location = badge.text.strip() if badge else "未知地點"
            
            # 日期
            # <meta itemprop="startDate" content="...">
            start_date_el = card.select_one('meta[itemprop="startDate"]')
            end_date_el = card.select_one('meta[itemprop="endDate"]')
            date_text = "未提供日期"
            
            if start_date_el and start_date_el.get('content'):
                start_date = start_date_el.get('content').split('T')[0]
                if end_date_el and end_date_el.get('content'):
                    end_date = end_date_el.get('content').split('T')[0]
                    date_text = f"{start_date} ~ {end_date}" if start_date != end_date else start_date
                else:
                    date_text = start_date
            else:
                # 嘗試找字面上的日期
                date_box = card.select_one('.geodir-field-event_dates')
                if date_box:
                    # e.g. 2026-07-25 - 2026-07-26
                    text = re.sub(r'\s+', ' ', date_box.text).strip()
                    if text:
                        date_text = text
            
            # 報名費
            price = "未提供"
            price_box = card.select_one('.geodir-field-price')
            if price_box:
                price = re.sub(r"報名費\s*[:：]?\s*", "", price_box.text).strip()
                
            # 報名截止日
            deadline = "未提供"
            deadline_box = card.select_one('.geodir-field-dob')
            if deadline_box:
                deadline = re.sub(r"報名截止日\s*[:：]?\s*", "", deadline_box.text).strip()
                
            event_obj = {
                "title": title,
                "url": url,
                "location": location,
                "date": date_text,
                "price": price,
                "deadline": deadline
            }
            if event_obj not in events:
                events.append(event_obj)
            
        page += 1

    print(f"✅ 共找到 {len(events)} 個賽事！")
    
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"events": events}, f, ensure_ascii=False, indent=2)
    
    print(f"🎉 爬取完成！資料已儲存至 {DATA_FILE}")

if __name__ == "__main__":
    main()
