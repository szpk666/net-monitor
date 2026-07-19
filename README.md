# NetMon — 家用網路監控

輕量的家用網路品質監控工具,幫你抓出「網路怪怪的」到底是路由器問題、Wi-Fi 問題,還是 ISP 問題。定時檢查連線狀態、跑測速、記錄斷線,異常時透過 Telegram 通知你。


## 為什麼做這個?

社區共享網路或有問題的 ISP 上,常常會遇到「下載遠低於上傳」、「明明訊號滿格但網頁跑不動」這種難以描述的狀況。想跟客服申訴,他們一句「我們這邊測試正常」就打發你。這個工具就是為此而生——長期記錄你家網路的實際狀況,拿數據跟他們談。

## 特色

- **內外分層檢測**:分開 ping 路由器 (gateway) 跟外部端點,一眼看出是家裡問題還是對外 ISP 問題
- **測速趨勢**:用 Cloudflare 的公開 speedtest endpoint(無需第三方套件、不會被 Ookla 擋)
- **可自訂異常條件**:延遲門檻、下載速度門檻、下載/上傳不對稱比例都可以在設定頁勾選啟用並調整數值
- **即時 Telegram 告警**:網路異常的當下就推播,恢復也推播
- **系統匣圖示**(Windows):圖示顏色即時反映狀態(綠/紅/暫停灰)
- **可視化 Dashboard + 下載報表**:即時狀態、延遲/測速趨勢圖、斷線紀錄表,一鍵下載靜態 HTML 報表 (適合寄給 ISP 客服當佐證)
- **跨平台**:同一份 code 可以在 Windows、Linux、Termux (Android) 執行
- **輕量**:純 Python 標準庫為主,SQLite 存資料,無 DB server、無雲端依賴

## 異常判定條件

打開設定頁可以看到清楚的說明。判定邏輯只有「正常」跟「異常」兩種狀態,異常時會在 Dashboard 顯示原因,並推播 Telegram。

**一定會偵測**(無法關閉):

- 路由器 ping 不到 → 異常 (通常是 Wi-Fi 或路由器問題)
- 所有對外連線都失敗 → 異常 (通常是 ISP 問題)

**選用門檻**(可勾選啟用並調整數值):

- 路由器延遲 > `N` ms → 異常 (預設 100ms)
- 下載速度 < `N` Mbps → 異常 (預設 50 Mbps)
- 下載 < 上傳 × `比例` → 異常 (預設 0.5,偵測不對稱)

不對稱偵測特別適合社區共享網路——常見狀況是上傳一路暢通但下載被壓縮,這種問題單看 up/down 二元狀態抓不出來。

## 快速開始

### Windows

需求:Python 3.9+ 已安裝並加入 PATH。

```powershell
git clone https://github.com/szpk666/net-monitor.git
cd netmon
pip install -r requirements.txt
python tray_app.py
```

第一次執行後工作列會出現一個灰色圓點圖示,同時瀏覽器會自動打開設定精靈——gateway IP 已自動偵測填好(偵測失敗會留空欄位讓你自行輸入),填入 Telegram token(選填)、勾選要啟用的異常判定條件,按「開始監控」就完成。之後右鍵工作列圖示看選單。

想不用另外裝 Python、雙擊就跑?打包成單一 exe:

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name NetMon tray_app.py
```

執行檔會出現在 `dist\NetMon.exe`。想要開機自動啟動,把這個檔案的**捷徑**丟進 `shell:startup` 資料夾(Win+R 打開輸入 `shell:startup`)。

## Telegram 通知設定

1. 在 Telegram 找 `@BotFather` 開一個 bot,拿到 Token
2. 傳訊息給你的 bot,然後打開 `https://api.telegram.org/bot<TOKEN>/getUpdates` 找到自己的 `chat.id`
3. 把 Token 跟 Chat ID 填進 NetMon 設定頁,按「測試 Telegram 通知」確認能收到

## Dashboard 說明

- **狀態徽章**:網路狀態(正常/異常)跟監控狀態(監控中/已暫停)分開顯示
- **即時數據**:路由器/對外延遲、下載/上傳 Mbps,狀態卡片直接看得到
- **異常原因**:當狀態變成異常時,會顯示是哪個條件被觸發
- **倒數計時**:下次自動檢查還有幾秒
- **可用率統計**:總可用率、近 24h、近 7 天 (有資料才顯示)
- **趨勢圖**:延遲 (ms) 跟測速 (Mbps) 的歷史走勢
- **斷線紀錄**:每次斷線的開始/結束時間、持續時間、異常原因(**這張表拿去申訴 ISP 最有用**)
- **下載報表按鈕**:一鍵匯出當下的所有資料成一份 HTML 檔案

## 專案結構

| 檔案 | 用途 |
|---|---|
| `tray_app.py` | Windows 系統匣入口 |
| `app.py` | 常駐 web server 入口(Termux / Linux 用) |
| `main.py` | CLI 入口(給偏好 cron 排程的人用) |
| `engine.py` | 核心邏輯:連線檢查、測速、異常判定 |
| `checker.py` | 底層工具:ping、HTTP、gateway 偵測(跨平台) |
| `report.py` | Dashboard HTML 產生器 |
| `db.py` | SQLite schema |
| `notifier.py` | Telegram 推播 |

## 疑難排解

**Windows Defender 警告 exe**  
PyInstaller 打包的 exe 常被誤判。要嘛加入信任清單,要嘛直接用 `python tray_app.py` 執行原始碼。

**首次執行防火牆跳出詢問**  
NetMon 會開一個本機 HTTP server(port 8787)給你打開 Dashboard 用。**選「允許私人網路」就好**,不用允許公用網路。

**Dashboard 顯示「上次測速失敗」**  
會直接寫失敗原因。常見:網路不穩(重試看看)、防火牆擋出向 HTTPS、公司網路擋 Cloudflare。

**路由器延遲數字沒顯示**  
先確認你在設定頁填的 gateway IP 是對的(可以在 CMD 打 `ipconfig` 查「預設閘道」)。如果 gateway 完全 ping 不到,可能是路由器擋了 ICMP。

**測速太頻繁讓其他人受影響**  
預設每 60 秒檢查+測速一次可能太頻繁,可以在設定頁調長間隔(例如 300 秒 = 5 分鐘)。

## 進階:cron 模式

不想要常駐 web server 的話,用 `main.py`:

```bash
crontab -e
```

```cron
*/5 * * * * cd ~/netmon && python main.py --mode check >> ~/netmon/check.log 2>&1
0 * * * *   cd ~/netmon && python main.py --mode speedtest >> ~/netmon/speed.log 2>&1
0 8 * * *   cd ~/netmon && python main.py --mode report >> ~/netmon/report.log 2>&1
```

需要手動從 `config.example.json` 複製一份 `config.json` 並編輯。這個模式沒有即時 Dashboard,要另外跑 `python main.py --mode report` 產生 HTML。

