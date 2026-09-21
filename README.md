# Pickleball LINE Bot (匹克球小幫手)

這是一個專為「匹克球 (Pickleball)」愛好者打造的 LINE Bot 開源專案。
主要提供功能：
- **隨機分組與對戰表生成**：輸入名單自動排出對戰表（支援場地限制、候補遞補機制）。
- **開團文產生器**：引導式對話生成漂亮的報名格式。
- **AI 智能名單擷取**：透過 Google Gemini 處理口語化報名。
- **賽事精華**：透過 YouTube API 即時抓取賽事。
- **球場查詢**：即時抓取並提供各地匹克球場地資訊。
- **匹克球規則**：一鍵產生規則與計分說明。

## 部署與安裝 (How to setup)

1. **複製專案**
   ```bash
   git clone https://github.com/princend/pickleball-linebot.git
   cd pickleball-linebot
   ```

2. **安裝依賴套件**
   ```bash
   pip install -r requirements.txt
   ```

3. **環境變數設定**
   複製一份環境變數檔案，並填入你的金鑰：
   ```bash
   cp .env.example .env
   ```
   請在 `.env` 中填寫以下參數：
   - `LINE_CHANNEL_ACCESS_TOKEN`：LINE Developer Console 取得。
   - `LINE_CHANNEL_SECRET`：LINE Developer Console 取得。
   - `GEMINI_API_KEY` (可選)：用於 AI 智能擷取名單。
   - `YOUTUBE_API_KEY` (可選)：用於賽事精華推薦。

4. **執行伺服器**
   ```bash
   python app.py
   ```
   伺服器預設會跑在 `0.0.0.0:8080`。請使用 ngrok 或直接部署至 Render / Heroku，並將網址設定到 LINE Webhook。

## 專案結構
- `app.py`: LINE Webhook 與 Flask 主程式入口。
- `handlers/`: 處理 LINE 的 TextMessage 與 Postback 事件。
- `pickleball/`: 核心邏輯（分組、排版、AI 解析、球場爬蟲等）。
- `config.py`: 環境變數與設定讀取。
