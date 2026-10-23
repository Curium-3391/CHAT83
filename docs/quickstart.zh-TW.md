# CHAT83 v0.6.0｜繁體中文快速安裝指南

[← 返回 README](../README.md) · [下載正式版](https://github.com/Curium-3391/CHAT83/releases/tag/v0.6.0) · [完整技術與除錯說明](v05-integrated-terminal.md)

CHAT83 讓 **原版 TI-83 Plus** 透過 **Arduino Uno + Windows Python Bridge** 與 Gemini API 進行真正的多輪文字聊天。按鍵輸入、歷史瀏覽與顯示由計算機處理；Gemini API 呼叫、模型推論與 SQLite 聊天紀錄都在電腦端。

> **相容性限制：** 目前僅支援**原版 TI-83 Plus**，不支援 TI-83 Plus Silver Edition 或 TI-84 系列。本版已在原版 TI-83 Plus 上驗證 Gemini 實際問答與獨立 `GEMINI>` 顯示，但長時間穩定性、重啟後自動恢復捲動位置仍未完整驗證。

## 一、你需要準備

| 項目 | 說明 |
| --- | --- |
| 原版 TI-83 Plus | 安裝 `CHAT83.8xk`（App）或 `C83V5.8xp`（組語程式） |
| Arduino Uno | 使用套件內的 `CHAT83_Uno_v05.ino`；執行時不是 TiLP 傳檔模式 |
| 2.5 mm TI Link 線 | `TIP→D3`、`RING→D6`、`sleeve→GND` |
| Windows 電腦 + USB 線 | Python 3；目前實機使用 `COM2`、USB 序列埠 115200 baud |
| 安裝計算機檔案的工具 | TiLP 相容傳輸裝置，或獨立原廠／相容 TI 傳輸線 |
| Gemini API Key | 從 [Google AI Studio](https://aistudio.google.com/app/apikey) 建立；只保留在 Windows |

**重要電氣事項：** TI Link 的 TIP／RING 是雙向握手訊號，不是一般 UART。應用韌體採取拉低或釋放的方式，不要把外部電壓或 MCU 推挽輸出直接接到訊號線。

## 二、下載與安裝計算機 App

從 [v0.6.0 發行頁](https://github.com/Curium-3391/CHAT83/releases/tag/v0.6.0) 下載 **`CHAT83-v0.6.0-Windows.zip`** 並解壓縮，取得：

- `CHAT83.8xk`：建議安裝的 Flash App，從 **APPS** 開啟。
- `C83V5.8xp`：同一個 Z80 客戶端的 PRGM／`Asm(` 程式版本。
- `CHAT83_Uno_v05.ino`：Arduino Uno 執行聊天時的韌體。
- `bridge_v05.py`、`usb_v05.py`、`providers_v05.py` 等：Windows Bridge。
- `requirements-v05-gemini.txt`：Python 套件需求。

**同一塊 Uno 如果同時負責 TiLP 傳檔和 CHAT83：**

1. 先刷入 [上游 `serial2ti83`](https://github.com/jw0k/serial2ti83)，並且依實際接線將 TIP、RING 常數**都**設為 `3`、`6`（原廠範例腳位不同）。
2. 使用 TiLP 將 `CHAT83.8xk` 傳送至計算機；完成後**關閉 TiLP**。
3. **暫時拔下 TI Link 插頭**，再刷入套件內的 `CHAT83_Uno_v05.ino`。刷好後關閉 Arduino Serial Monitor，重新接上 Link 線。

CHAT83 的 Uno 韌體**沒有 TiLP 相容傳輸功能**，所以步驟不能顛倒。若有獨立的 TI 傳輸線，可以直接用那條線傳送 App，Uno 就不需要來回換韌體。

## 三、Windows 設定 Gemini API

在 PowerShell 執行（假設 ZIP 解壓在 Downloads）：

```powershell
cd "$HOME\Downloads\CHAT83-v0.6.0-Windows"
py -m pip install -r .\requirements-v05-gemini.txt
```

打開 [Google AI Studio](https://aistudio.google.com/app/apikey) 建立金鑰，並在 Windows 搜尋「**編輯系統環境變數**」→「環境變數」→ 上方「**使用者變數**」新增：

| 名稱 | 值 |
| --- | --- |
| `GEMINI_API_KEY` | 你自己的 Gemini API Key |

**設定完重開 PowerShell。** 不要把 Key 寫入 Arduino、計算機、GitHub、程式碼或公開的除錯紀錄。若金鑰曾曝光，請先撤銷並更換。

## 四、啟動與操作

先啟動 Windows Bridge，再打開計算機 App：

```powershell
py .\bridge_v05.py --port COM2 --provider gemini --model gemini-3.5-flash-lite --gap-ms 35 --reply-delay-ms 250
```

`COM2` 要依你的 Windows 裝置管理員實際埠號調整。看到 `CHAT83 Uno v0.5 handshake OK` 和 `Listening for TI-83 Plus` 後，在計算機按 **APPS → CHAT83**；如果裝的是 `C83V5.8xp`，改用 `Asm(prgmC83V5)` 啟動。

現在輸入一段問題，按 ENTER，就會出現獨立 `GEMINI>` 標頭，回答從下一行最左邊開始（每一行文字可使用 12 格）。範例：

```text
YOU: HELLO
GEMINI>
HELLO WORLD!
```

按鍵對照：

| 按鍵 | 功能 |
| --- | --- |
| ENTER | 在歷史畫面開啟輸入介面；在輸入畫面送出訊息 |
| ALPHA | 切換英文／數字輸入 |
| 2nd | 輸入空格 |
| 左右方向鍵、DEL | 移動游標、刪除游標前方的字 |
| 上下方向鍵 | 捲動對話；需要時向 Windows 取得舊紀錄 |
| GRAPH | 跳到最新訊息 |
| MODE | 取消模型生成；在 LINK ERROR 畫面重新同步 |
| CLEAR | 離開輸入畫面或結束 App |

單次最多輸入 **48 個 ASCII 字元**；完整對話存在 Windows 的 SQLite 資料庫中。

## 五、更新舊測試版與疑難排解

若之前已在使用 `CHAT83_v05` 測試套件，更新前先**備份原本 `chat83.sqlite3` 和 `bridge_v05.py`**。新版本的輸入殘影修正包含 Z80 程式碼，所以**不能只更新 Windows 的 Python 檔**，還必須換新的 `CHAT83.8xk` 或 `C83V5.8xp`。不要刪除舊的 SQLite 資料庫。如果你的資料庫放在其他位置，可用 `--db "完整路徑"` 指定。

- **無法連線 Uno：** 確認 COM 埠、USB 線、是否刷對 CHAT83 Uno 韌體，並關閉 TiLP 與 Arduino Serial Monitor。
- **TiLP 不能傳 App：** CHAT83 Uno 韌體本來就不支援 TiLP；要先切回相容的傳檔韌體或改用獨立傳輸線。
- **重新連線後停在 LOADING／LINK ERROR：** Windows Bridge 新版不會因過期的 `R` 重傳要求而立即退出。計算機若進入 LINK ERROR，按 **MODE** 重新 SYNC；必要時關閉再重新啟動 App。**目前不會自動恢復舊捲動位置。**
- **向上翻頁 FETCH OLDER 偶發逾時：** 先保留 `--gap-ms 35 --reply-delay-ms 250`。`--batch-pause-ms 150` 只是診斷實驗參數，不是已確認的根因修復。
- **英文分行不理想：** 可額外加 `--word-wrap`，Gemini 的獨立標頭仍會保留。
- **模型/API 出錯：** 檢查金鑰、網路、模型是否可用、配額或收費設定。離線測試可改用 `--provider demo`。

**建議的保守實機設定仍是 gap 35 ms、reply delay 250 ms。** 不要在同一輪測試同時更動多個時序選項。

想看 Z80、Arduino、TI Link 的協定和除錯細節，可讀 [技術文件](v05-wire-protocol.md)、[原始安裝紀錄](v05-integrated-terminal.md) 與 [v0.6.0 Release Notes](releases/v0.6.0.md)。本專案使用 [MIT License](../LICENSE)。
