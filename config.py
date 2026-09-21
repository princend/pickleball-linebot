import os
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

line_channel_access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
line_channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
