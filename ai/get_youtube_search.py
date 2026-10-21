import html
import requests
from config import youtube_api_key

def search_youtube_videos(keyword, max_results=3, order="date"):
    """透過 YouTube Data API v3 搜尋影片。
    
    完全不限制地區（不帶 regionCode），以全球視野檢索最新公開影片。
    :param keyword: 搜尋關鍵字
    :param max_results: 最大回傳筆數
    :param order: 排序依據，預設為 'date'（最新發布），可選 'relevance' 等
    """
    if not youtube_api_key:
        print("未設定 YouTube API Key")
        return None
        
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "maxResults": max_results,
        "order": order,
        "key": youtube_api_key
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        videos = []
        if "items" in data and len(data["items"]) > 0:
            for item in data["items"]:
                video_id = item["id"]["videoId"]
                title = html.unescape(item["snippet"]["title"])
                channel = item["snippet"]["channelTitle"]
                published_at = item["snippet"].get("publishedAt", "")
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                # 安全解析縮圖
                thumbnails = item["snippet"].get("thumbnails", {})
                thumbnail_url = ""
                if "high" in thumbnails:
                    thumbnail_url = thumbnails["high"]["url"]
                elif "medium" in thumbnails:
                    thumbnail_url = thumbnails["medium"]["url"]
                elif "default" in thumbnails:
                    thumbnail_url = thumbnails["default"]["url"]
                
                videos.append({
                    "title": title,
                    "channel": channel,
                    "url": video_url,
                    "thumbnail_url": thumbnail_url,
                    "published_at": published_at,
                })
            
            return videos
    except Exception as e:
        print(f"YouTube 關鍵字搜尋失敗: {e}")
        
    return None
