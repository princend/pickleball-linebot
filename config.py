import os
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

line_channel_access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
line_channel_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
tracknet_worker_url = os.environ.get(
    "TRACKNET_WORKER_URL",
    "https://b10009046--pickleball-tracknet-worker-web-app.us-east.modal.run",
)
# AI 軌跡分析功能總開關：預設關閉，上傳影片不會觸發分析；設定 TRAJECTORY_ENABLED=1 才會開啟
trajectory_enabled = os.environ.get("TRAJECTORY_ENABLED", "0") == "1"
tracknet_worker_secret = os.environ.get(
    "TRACKNET_WORKER_SECRET",
    "pb_worker_v2_8f4a9c2e1b7d6035a9e2f4c8d1b3a5e7",
)
