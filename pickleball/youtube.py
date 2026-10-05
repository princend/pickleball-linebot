"""匹克球 YouTube 影片搜尋模組。

透過 YouTube Data API 即時搜尋教學影片，並封裝成精美的 Flex Message 供使用者觀看。
具備優雅降級機制：若無 API 金鑰或呼叫失敗，將提供一般搜尋連結。
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexImage,
    FlexMessage,
    FlexText,
    URIAction,
)

import csv
import io
import time
import requests
from config import youtube_api_key

SHEET_URL = "https://docs.google.com/spreadsheets/d/1Zphr-a547bmb0nTTNxz8p5A1dajAmLSOi-mO1NiRydw/export?format=csv&gid=1618436444"
VIDEO_CACHE = {}
LAST_FETCH_TIME = 0

def _get_video_from_sheet(query: str) -> Optional[Dict[str, str]]:
    """優先從 Google Sheets 查詢精選影片。"""
    global VIDEO_CACHE, LAST_FETCH_TIME
    current_time = time.time()
    
    # 5 分鐘快取
    if current_time - LAST_FETCH_TIME > 300:
        try:
            r = requests.get(SHEET_URL, timeout=5)
            r.encoding = 'utf-8'
            reader = csv.reader(io.StringIO(r.text))
            rows = list(reader)
            
            new_cache = {}
            if len(rows) > 1:
                # 假設第一列為標題，資料從第二列開始
                # 欄位順序預設：A(關鍵字), B(標題), C(網址)
                for row in rows[1:]:
                    if len(row) >= 3:
                        kw = row[0].strip().lower()
                        if kw:
                            title = row[1].strip()
                            url = row[2].strip()
                            
                            video_id = ""
                            if "v=" in url:
                                video_id = url.split("v=")[1].split("&")[0]
                            elif "youtu.be/" in url:
                                video_id = url.split("youtu.be/")[1].split("?")[0]
                                
                            thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
                            
                            new_cache[kw] = {
                                "title": title,
                                "video_id": video_id,
                                "video_url": url,
                                "thumbnail_url": thumb_url
                            }
            VIDEO_CACHE = new_cache
            LAST_FETCH_TIME = current_time
        except Exception as e:
            print(f"[警告] 讀取影片表單失敗: {e}", flush=True)

    query_lower = query.lower()
    for kw, data in VIDEO_CACHE.items():
        if kw in query_lower:
            return data
            
    return None

def search_youtube_video(query: str) -> Optional[Dict[str, str]]:
    """透過 Google Sheets 或 YouTube Data API v3 搜尋影片。
    
    回傳字典包含:
        - title: 影片標題
        - video_id: 影片 ID
        - video_url: 影片完整網址
        - thumbnail_url: 影片縮圖網址
    若失敗或無設定 API Key 則傳回 None。
    """
    # 1. 優先查表
    sheet_data = _get_video_from_sheet(query)
    if sheet_data:
        return sheet_data

    # 2. 找不到則降級回 YouTube API
    if not youtube_api_key:
        return None
        
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults=1&q={encoded_query}&key={youtube_api_key}"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            
        items = data.get("items", [])
        if not items:
            return None
            
        item = items[0]
        snippet = item.get("snippet", {})
        
        title = snippet.get("title", "")
        # 反轉義常見的 HTML entities
        title = title.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        
        video_id = item.get("id", {}).get("videoId", "")
        if not video_id:
            return None
            
        thumbnails = snippet.get("thumbnails", {})
        # 優先取用 high 畫質，否則 medium 或 default
        thumb_url = ""
        for quality in ["high", "medium", "default"]:
            if quality in thumbnails and "url" in thumbnails[quality]:
                thumb_url = thumbnails[quality]["url"]
                break
                
        return {
            "title": title,
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_url": thumb_url
        }
    except Exception as e:
        print(f"[警告] YouTube 搜尋失敗: {e}", flush=True)
        return None


def create_video_flex(query: str, video_data: Optional[Dict[str, str]]) -> FlexMessage:
    """產生精美的 YouTube 影片 Flex Message。
    
    若 video_data 有值，將顯示縮圖與該影片的專屬播放連結；
    若為 None (容錯模式)，則產生一個包含 YouTube 搜尋結果頁面連結的通用卡片。
    """
    if video_data:
        title = video_data["title"]
        video_url = video_data["video_url"]
        thumb_url = video_data["thumbnail_url"]
        
        hero = FlexImage(
            url=thumb_url,
            size="full",
            aspect_ratio="16:9",
            aspect_mode="cover",
            action=URIAction(uri=video_url)
        )
        
        body = FlexBox(
            layout="vertical",
            contents=[
                FlexText(
                    text="精選教學影片",
                    weight="bold",
                    color="#FF0000",
                    size="sm"
                ),
                FlexText(
                    text=title,
                    weight="bold",
                    size="md",
                    margin="md",
                    wrap=True,
                    max_lines=2
                )
            ]
        )
        
        footer = FlexBox(
            layout="vertical",
            spacing="sm",
            contents=[
                FlexButton(
                    style="primary",
                    color="#FF0000",
                    action=URIAction(
                        label="觀看影片",
                        uri=video_url
                    )
                ),
                FlexButton(
                    style="secondary",
                    action=URIAction(
                        label="更多搜尋結果",
                        uri=f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
                    )
                )
            ]
        )
    else:
        # Fallback 模式
        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        hero = None
        
        body = FlexBox(
            layout="vertical",
            contents=[
                FlexText(
                    text="影片搜尋建議",
                    weight="bold",
                    color="#FF0000",
                    size="sm"
                ),
                FlexText(
                    text=f"為您推薦關鍵字：「{query}」",
                    weight="bold",
                    size="md",
                    margin="md",
                    wrap=True
                ),
                FlexText(
                    text="您可以點擊下方按鈕，直接在 YouTube 觀看相關教學影片。",
                    size="xs",
                    color="#aaaaaa",
                    margin="md",
                    wrap=True
                )
            ]
        )
        
        footer = FlexBox(
            layout="vertical",
            contents=[
                FlexButton(
                    style="primary",
                    color="#FF0000",
                    action=URIAction(
                        label="前往 YouTube 搜尋",
                        uri=search_url
                    )
                )
            ]
        )

    bubble = FlexBubble(
        hero=hero,
        body=body,
        footer=footer
    )
    
    return FlexMessage(
        alt_text="匹克球教學影片",
        contents=bubble
    )
