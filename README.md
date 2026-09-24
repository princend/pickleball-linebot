# Pickleball LINE Bot (匹克球小幫手) 🏓

這是一個專為「匹克球 (Pickleball)」愛好者打造的 LINE Bot 開源專案。無論你是球團團長、教練，還是剛接觸匹克球的新手，這個機器人都能幫你省下大量處理庶務的時間！

本專案經過特別設計，**即使你完全不會寫程式，也能透過以下教學在 10 分鐘內免費建立屬於你自己的匹克球機器人！**

## 🌟 核心功能

只需要在聊天室輸入對應指令，就能啟動功能（指令前面請加驚嘆號 `!`）：

- **`!指令` (主選單)**：一鍵呼叫精緻的功能面板，不用死記指令。
- **`!分組` (隨機分組與對戰表生成)**：只要貼上報名名單，自動幫你排出公平的對戰表（支援自訂場地數量、候補遞補機制）。
- **`!開團` (開團文產生器)**：引導式對話，一步步幫你生成排版漂亮的報名文章。
- **`!查球場` (球場查詢)**：即時抓取並提供全台灣各地區的匹克球場地資訊。
- **`!匹克球規則` (規則說明)**：一鍵產生新手必備的規則與計分說明卡片。
- **`!匹克球精華` (賽事精華)**：透過 YouTube 即時抓取最新、最精彩的匹克球賽事。
- **`!ai:問題` (AI 匹克球專屬問答)**：專為匹克球打造的 AI 知識庫，解答規則、技巧、裝備與賽事等問題（非匹克球問題不予回答，精準俐落）。
- **🤖 AI 智能名單擷取**：內建串接 Google Gemini，能自動看懂群組裡大家亂七八糟的接龍報名名單。

---

## 🚀 零基礎免費部署教學 (Deploy to Vercel)

我們將使用 [Vercel](https://vercel.com/) 進行免費部署，它不僅免費，而且**不會像其他免費伺服器一樣有 15 分鐘休眠的問題**。

### 步驟 1：準備好你的專案
1. 註冊一個 [GitHub](https://github.com/) 帳號。
2. 點擊本專案右上角的 **「Fork」**，將這個專案複製到你自己的 GitHub 帳號底下。

### 步驟 2：取得 LINE 機器人金鑰
1. 前往 [LINE Developers Console](https://developers.line.biz/console/) 並登入你的 LINE 帳號。
2. 點擊 **Create a new provider**，隨便取個名字。
3. 點擊 **Create a Messaging API channel**，填寫你的機器人名稱、大頭貼、類別等資訊。
4. 建立完成後，找到兩個非常重要的金鑰（請先複製貼到記事本）：
   - 在 **Basic settings** 頁籤的底部，找到 **`Channel secret`**。
   - 在 **Messaging API** 頁籤的底部，點擊 **Issue** 按鈕，產生一長串的 **`Channel access token`**。

### 步驟 3：部署到 Vercel
1. 前往 [Vercel 官方網站](https://vercel.com/)，使用你的 GitHub 帳號登入。
2. 點擊右上角的 **"Add New..."** -> **"Project"**。
3. 找到你剛剛 Fork 的 `pickleball-linebot` 專案，點擊旁邊的 **"Import"**。
4. 往下捲動找到 **"Environment Variables (環境變數)"** 區塊，點開並輸入以下四組資料（一組輸入完按 Add）：
   - 名稱：`LINE_CHANNEL_ACCESS_TOKEN` / 值：*(填入步驟 2 取得的 Token)*
   - 名稱：`LINE_CHANNEL_SECRET` / 值：*(填入步驟 2 取得的 Secret)*
   - 名稱：`GEMINI_API_KEY` / 值：*(選填，至 Google AI Studio 免費取得，用於 AI 解析名單)*
   - 名稱：`YOUTUBE_API_KEY` / 值：*(選填，至 Google Cloud Console 取得，用於影片推薦)*
5. 點擊最下方的 **"Deploy"**，等待約 1~2 分鐘直到畫面噴灑彩帶 🎉。
6. 點擊跳出來的網址，這就是你的專屬伺服器網址（例如：`https://你的專案名.vercel.app`）。

### 步驟 4：設定 LINE Webhook 與關閉預設回覆
1. 回到 [LINE Developers Console](https://developers.line.biz/console/) 的 **Messaging API** 頁籤。
2. 找到 **Webhook URL**，將 Vercel 給你的網址貼上去，**並且記得在最後面加上 `/callback`**。
   *(範例：`https://你的專案名.vercel.app/callback`)*
3. 點擊 **Update**，然後點擊 **Verify**，顯示 Success 代表成功連線！
4. 點擊網頁上方的 **"LINE Official Account Manager"** 連結進入官方帳號後台。
5. 點擊右上角齒輪「設定」 -> 左側「回應設定」：
   - 回應模式：選擇 **聊天機器人**
   - 歡迎訊息：選擇 **停用**
   - 自動回覆訊息：選擇 **停用** (這非常重要，否則機器人會一直回覆預設文字)
   - Webhook：選擇 **啟用**

**恭喜！你的匹克球機器人已經正式上線啦！快去 LINE 裡面對它輸入 `!指令` 試試看吧！**

---

## 💻 本地開發與自架伺服器 (For Developers)

如果你熟悉 Python 且想要在本地開發或部署到其他伺服器（如 Render, GCP, AWS）：

1. **複製專案**
   ```bash
   git clone https://github.com/你的帳號/pickleball-linebot.git
   cd pickleball-linebot
   ```

2. **安裝環境與套件**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **設定環境變數**
   ```bash
   cp .env.example .env
   ```
   請在 `.env` 中填寫你的各項 API 金鑰。

4. **執行伺服器**
   ```bash
   python app.py
   ```
   伺服器預設會跑在 `0.0.0.0:8080`。你可以使用 ngrok 進行本地測試。

## 📂 專案結構說明
- `app.py`: LINE Webhook 與 Flask 主程式入口。
- `handlers/`: 處理 LINE 的文字指令 (`text_handler.py`) 與按鈕點擊事件 (`postback_handler.py`)。
- `pickleball/`: 核心邏輯（分組演算法、Flex 卡片排版、AI 解析、球場爬蟲等）。
- `config.py`: 環境變數與設定讀取。
- `vercel.json`: Vercel 無伺服器 (Serverless) 部署設定檔。
