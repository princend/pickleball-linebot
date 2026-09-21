import requests
from config import youtube_api_key

def search_youtube_videos(keyword, max_results=3):
    if not youtube_api_key:
        print("未設定 YouTube API Key")
        return None
        
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "regionCode": "TW",
        "maxResults": max_results,
        "order": "relevance",
        "key": youtube_api_key
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        videos = []
        if "items" in data and len(data["items"]) > 0:
            for item in data["items"]:
                video_id = item["id"]["videoId"]
                title = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                # Safe thumbnail extraction
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
                    "thumbnail_url": thumbnail_url
                })
            
            return videos
    except Exception as e:
        print(f"YouTube 關鍵字搜尋失敗: {e}")
        
    return None
