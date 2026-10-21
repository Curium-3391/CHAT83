# CHAT83 v0.5 — 整合測試候選版

> **狀態：原始碼、編譯及自動化測試完成後才能交付實機驗收。尚未在使用者的 Uno + TI-83 Plus 實測此新版韌體／Z80 組合。**
>
> 穩定版仍是 main 上的 v0.3.2；v0.4 是實機驗證的合作式 RX / 48 行快取版本。本 v0.5 分支不覆蓋它們。

## 架構

```text
Original TI-83 Plus
  CHAT83.8xk App (or C83V5.8xp) -- Z80, _GetCSC, 48×13B ring, 6×12B staged CRC8,
  4×12B editor, 16-row predictive trigger, polling for live LLM rows
       | TIP / RING / GND (2.5mm link)
Arduino Uno ATmega328P
  D2 = TIP, D3 = RING, GND = sleeve
  Open-drain bit handshake; cooperative FSM; <=16-byte USB TX credit
       | USB COM2, 115200 baud, COBS+CRC8 frames
Windows PC
  Python 3.9+, pyserial, SQLite, OpenAI / Ollama / demo provider
  Worker thread generates; main thread owns serial and SQLite
       | optional HTTPS
LLM API
```

**重要：刷寫新版 Uno 後，舊 `serial2ti83` 的 9600-baud
`bridge_v03.py`／`bridge_v04.py` 無法直接通訊。** 若要回去使用
v0.4，請重新刷回原版 `serial2ti83.ino`。TI 端的 `C83V5` 與
`C83V4` 是不同程式名稱，可以同時保留。

實驗版只支援**原版 TI-83 Plus**；不要在 TI-83 Plus Silver Edition
或 TI-84 系列運行讀 Port 05h 的程式，該 I/O port 定義不同。

## 第一次安裝：先傳 TI 程式，最後才刷 Uno v0.5

**⚠️ 安裝順序極其重要：同一塊 Uno 使用兩種互不相容的韌體。**
原版 `serial2ti83.ino` 是之前用來連接 TiLP 的 9600-baud 橋接器；
新的 `CHAT83_Uno_v05.ino` 則是 115200-baud COBS/CRC8 橋接器。
**後者並未實作 TiLP 相容模式。先刷 v0.5 再執行 TiLP，
會出現「timeout occurred while reading from the device」；
這不代表 TI-83 Plus 或連接線故障。**

1. 安裝 Python 3.9+、TiLP 與 Arduino IDE。備份之前 v0.4 的 SQLite
   資料庫及先前能正常與 TiLP 通訊的 Uno 韌體。
2. **保留或暫時刷回原版 `serial2ti83`**，來源：
   [jw0k/serial2ti83/serial2ti83.ino](https://github.com/jw0k/serial2ti83/blob/master/serial2ti83.ino)。
   若你的 Uno 已經刷成 CHAT83 v0.5，先關閉 Python Bridge／TiLP 與
   Arduino 序列監控器，再用 Arduino IDE 將上游原版 sketch 重新上傳。
3. 用之前驗證過的 Uno TIP=D2／RING=D3／GND 接線，**在原版韌體下
   使用 TiLP 傳入 `CHAT83.8xk`**（建議，Flash App），確認計算機的
   **APPS** 選單出現 `CHAT83`。也可以改傳 `C83V5.8xp`，它會出現在
   PRGM 清單。兩者功能相同，可同時保留。完整關閉 TiLP，釋放 COM 埠。
4. 暫時拔下計算機的 Link 插頭，再用 Arduino IDE 開啟
   `CHAT83_Uno_v05.ino`，板子選 Arduino Uno，重新上傳新的 v0.5
   韌體。上傳完成後關閉 Arduino IDE 的 Serial Monitor，重新接上
   計算機原本的 Link 接線。
5. 確認接線：**Uno D2 → TIP、D3 → RING、GND → sleeve**。
   Arduino 只會把線路拉 LOW 或放開成 INPUT_PULLUP，
   不會主動強推 HIGH；禁止在未知硬體線路外加電壓。
6. 在解壓縮套件的 PowerShell 工作目錄執行：

   ```powershell
   py -m pip install -r requirements-v05.txt
   .\start-chat83-v05.ps1 -Port COM2 -Provider demo -GapMs 35
   ```

7. 看到 `CHAT83 Uno v0.5 handshake OK` 與 `Listening...` 後，
   在**原版** TI-83 Plus 按 **APPS** 選 `CHAT83`；如果裝的是程式版，
   則執行 `Asm(prgmC83V5)`。

**如果手邊另有原廠 TI USB／Graph Link 傳輸線**，可以直接用那條線
透過 TiLP 傳入 `CHAT83.8xk` 或 `C83V5.8xp`，之後只需刷一次 Uno v0.5。這是獨立
傳輸線的替代做法，不代表 v0.5 Uno 韌體本身支援 TiLP。

**如果日後要再更新計算機端 `.8xk`／`.8xp`**，使用同一 Uno 時仍須切回
`serial2ti83` 來傳檔，再刷回 `CHAT83_Uno_v05`；除非使用獨立
TI 傳輸線。這是目前 v0.5 安裝工具鏈的限制。

### 啟動 LLM

OpenAI Responses API 需另外的 API Key（ChatGPT 訂閱不等於 API 憑證）。
安裝 `py -m pip install -r requirements-v05-openai.txt`，
在 PowerShell 設定環境變數 `OPENAI_API_KEY`，然後：

```powershell
.\start-chat83-v05.ps1 -Provider openai -Model gpt-4.1-mini
```

金鑰**不要**寫入 Arduino、Z80、GitHub、SQLite 或測試紀錄；不要上傳
`.env`／秘密值。可改 `-Model` 指定帳戶能用的模型。

本機 Ollama：
```powershell
.\start-chat83-v05.ps1 -Provider ollama -Model llama3.2
```

需先在 PC 安裝 Ollama 並拉取模型。模型推論全在 PC／服務端完成，
TI-83 Plus 不會儲存 API Key，也不會執行模型。

### App 版與程式版

- `CHAT83.8xk` 是用公開的 0104 金鑰簽章的 Flash App，存在 Flash 裡，
  不佔 RAM，從 APPS 選單啟動，不受 `Asm(` 程式約 8.8 KB 的大小限制。
  更新時直接用 TiLP 傳新版覆蓋。刪除方式：MEM → Mem Mgmt/Del → Apps。
- `C83V5.8xp` 是同一份原始碼的 `Asm(` 程式版，保留作為備用。
- 兩者執行時都會借用系統的 `plotSScreen`（圖形緩衝區）和
  `appBackUpScreen` 存放快取與變數，所以離開後圖形畫面會重新繪製，
  這是正常現象。

## 操作

畫面配置（16 欄 × 8 列）：

```text
█ CHAT83 V0.5  AI█   標題列；右側 AI＝模型生成中、ERR＝模型錯誤、...＝等待 PC 回覆
YOU: HELLO      ┊    歷史 6 列，每列 12 字
█PC: WORLD    █ ┃    選取的列以反白顯示
...             ┊    右側捲動條：位置與長度對應 48 行快取
█ ENTER:ASK      █   按鍵提示；生成中 MODE:STOP、預取中 LOADING...、
                     沒選在最新一列時 ENTER GRAPH:END
```

**歷史瀏覽**
- ↑／↓：本機 48 行 Ring Buffer 捲動；靠近前後 1/3 時預取六行。
  若在資料尚未下載的邊界連續按方向鍵，可暫存最多 12 次的方向意圖。
- ENTER：進入四行文字編輯器。
- GRAPH：跳到最新一列。最新幾列還在快取時直接跳過去；已被淘汰時
  送出 SYNC 重新載入，等待期間歷史畫面保留，提示列顯示 LOADING...。
- MODE：模型正在生成時要求取消；若在 LINK ERROR 畫面，重新 SYNC。
- CLEAR：退出程式。ON 鍵在傳送中按下也會正常離開。

**連線錯誤不再跳出程式**：送出資料時如果 Uno／PC 沒有完成握手，
ROM 會產生 ERR:LINK。新版 CHAT83 會攔截這個錯誤，顯示自己的
`LINK ERROR` 畫面，不會再出現原廠的 `ERR:LINK / 1:Quit / 2:Goto`。
畫面文字會區分原因：
- `Could not send to the PC/Uno.`：計算機送不出去（握手失敗）。
- `No valid reply from the PC.`：送出了，但回覆三次 CRC 錯誤或逾時。

按 MODE 重新同步，修好連線後不必重新啟動程式。
如果 Python Bridge 因為收到不完整的請求而停止，要先重新啟動 Bridge。

**文字編輯器**
- 第 2 列右側顯示已輸入字數（例如 `12/48`）；插入點是反白方塊，
  方塊內的字仍看得到；最下方提示列顯示目前輸入模式（`A-Z`／`0-9`）
  與 ENTER 的作用（`ENTER:SEND`，模型生成中為 `AI WORKING`）。
- 預設 ALPHA ON，按計算機鍵帽上方印有 A–Z 的實體按鍵可輸入英文
  字母（例如 x⁻¹ 是 D、SIN 是 E）；`.` 鍵輸入 `:`、`(-)` 鍵輸入 `?`。
- ALPHA：切換英文字母／數字符號模式。
- 2nd：插入空格；在 ALPHA 模式按 0 也輸入空格。
- ←／→：移動插入游標；DEL：刪除游標左側字元。
- ENTER：送出最長 48 個 ASCII 字元；若上一題 AI 仍在生成，
  保留輸入內容，直到模型完成才允許送出。
- CLEAR：放棄輸入，返回歷史。
- 輸入時背景更新仍可繼續，但保護四行編輯畫面。

### 載入和串流機制

每次 PC 回覆最長**六行 × 12 bytes**。計算機收到 CRC8 正確的完整
`C` 封包才更新 Ring Buffer，不修改還在閱讀的六行；舊資料超出 48 行
後才淘汰，並保護游標位置。接收與按鍵掃描協作式交錯運行。

Python LLM 在背景執行，只有**確定不會被後續 token 改寫的完整 12 字元行**
才寫入 SQLite 的 `display_lines`；末尾不足一行在完成時補空白。
TI 端使用短 `U` 查詢拉取新行，不接收未要求的資料。中文／其他
不支援的字元目前替換成 ASCII 字元，不是原生中文字型。

### 速度／可靠性

- Uno 每個 USB `T` 批次上限 16 bytes；只在完成 TI Link 位元
  握手後回覆 `A`。CRC8 用於 USB 層與 Z80 應用層，各自檢查。
- 問題封包 `Q + LEN + ASCII + LATEST + CRC8` 會在 Windows 端驗證完畢才寫入 SQLite；CRC 不符的文字不會儲存。
- `-GapMs 35` 初始保守值：一個六行封包 81×35ms≈2.835 秒
  （**未含**位元握手及其他延遲），不代表實測吞吐量。
- 驗證原版硬體穩定後才開 `-Adaptive`，會每八個成功的指令交易
  減少 2ms，最低 12ms；一旦發生應用層 CRC 重傳就增大 5ms。
  **仍不能保證**六行 1 秒內。
- 單次應用層 CRC 錯誤可請求重傳原回覆，避免重複儲存問題。
  Z80 最多重試三次，再顯示 LINK ERROR。連線中途拔除、異常
  位元丟失導致無法判斷封包邊界時，可能仍需 MODE 或兩端重啟。
- USB/Arduino 協定互不相容舊版；雙方必須一同更新。

## 已知硬體問題：USB 已連線，但計算機顯示 ERR:LINK

**2026-10-21 實機觀察：** 使用者的 COM2 (USB-SERIAL CH340) 已成功出現
`CHAT83 Uno v0.5 handshake OK`、`Listening for TI-83 Plus`，
但 TI 執行 `Asm(prgmC83V5)` 後顯示原廠 ROM 的
`ERR:LINK / 1:Quit / 2:Goto`，PC 沒有出現 `SYNC`。
這是 **PC↔Uno USB 已確認、Uno↔TI Link 尚未驗證** 的狀況。
不要因為 Python 的 USB handshake OK 就宣稱整條電纜正常。

**使用新版 CHAT83.8xk／C83V5.8xp 時**，同樣的故障會改成顯示 CHAT83
自己的 `LINK ERROR`／`Could not send to the PC/Uno.` 畫面，程式不會
結束，可以一邊看 `[UNO-DIAG]` 一邊按 MODE 重試。

此候選版已新增 **Uno RX_ACK_SETTLE** 狀態：接收一個 bit 並釋放 ACK 後，
暫時等待線路經弱上拉回升，避免把自己的 ACK 殘留低電位誤讀成下一個 bit。
這是根據原始碼分析的可疑原因修正，並加入 60µs 線路延遲的
C++ 原韌體模擬回歸測試；**尚未有實機驗證它確實解決問題**。

如果已傳入 C83V5.8xp，只需**更新 Uno 韌體 + Python**
（`CHAT83_Uno_v05.ino`、`usb_v05.py`、`bridge_v05.py`）；
不需要再次開 TiLP 傳送相同的 C83V5.8xp。

1. 在 PowerShell 按 Ctrl+C，關閉 Arduino Serial Monitor。
2. 拔下計算機的 Link 插頭，將套件中更新後的
   `CHAT83_Uno_v05.ino` 使用 Arduino IDE 重新上傳，之後把 Link
   插頭接回原 D2/TIP、D3/RING、GND 接線。
3. 使用**新版** `bridge_v05.py` 搭配 `usb_v05.py`，用原本
   COM2 啟動：

   ```powershell
   py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider demo --gap-ms 35 --debug-link
   ```

4. 等到顯示 `handshake OK`、`[UNO-DIAG] enabled`、
   `Listening`，再在 TI-83 Plus 執行 `Asm(prgmC83V5)`。
5. 將 `[UNO-DIAG]`、`SYNC`、`LINK ERROR` 或 TI ERR 畫面
   的輸出回報。診斷每約半秒輸出一次：

   ```text
   [UNO-DIAG] start=8 ack=8 rx_bytes=1 rx_to=0 tx_to=0 state=0 TIP=H RING=H last_rx=0x53
   ```

   上面是**成功接收到 'S' 的示例，不是實測結果**。
   `start` 表示偵測到低電位的次數、`ack` 是完成位元握手次數，
   `rx_bytes` 是收到完整 byte 的次數；`TIP/RING` 是取樣狀態。
   `0x53` 就是 ASCII `S`。

**注意：** 線路仍有問題時，可能只出現
`start=0 ack=0 rx_bytes=0`，或在某一個 bit 卡住。
最終仍須實機驗收，不能只依賴模擬測試。

## 一次性完整硬體驗收表

請**先安裝整套，再照順序在同一次工作階段測完**。不要在步驟中更換
`.8xp` 或刷寫 Uno：

1. **版本握手**：Python 明確出現 `Uno v0.5 handshake OK`；
   計算機同步顯示 `CHAT83 V0.5`，不報錯。
2. **鍵盤編輯**：輸入 `HELLO`；測 ALPHA/數字、2nd 空格、
   ←/→ 插入、DEL，送出 `HELLO`。
3. **DEMO 模型**：預期 `PC: WORLD`、`DEMO` 長回覆正常出現，
   SQLite 同時有 USER 和 ASSISTANT 訊息。
4. **串流輪詢**：PowerShell `UPDATE @...`、`Q...` 依序出現；
   在模型生成過程中可以捲動及預先輸入下一個問題，不亂碼。
5. **長歷史環繞**：反覆 DEMO 直到超過 48 行；往上／往下捲，
   確認沒有字串重複、列錯位、游標跳動或覆蓋六行可視區。
6. **快速反轉**：在預取中連續按 ↑/↓；應盡量保持可操作，
   額外按鍵會依佇列重播；到達尚未載入資料不要求零延遲。
7. **中斷／錯誤復原**：生成中按 MODE 取消；
   如有 LINK ERROR，MODE 可以重新同步；再用 CLEAR 正常離開。
8. **OpenAI 或 Ollama**：僅在有正確憑證或本地模型時選用。
   確認真實模型回答、逐行輸出、上下文與重啟後 SQLite 歷史可讀。
9. **量測速度**：先使用固定 35ms；前述項目穩定才開 Adaptive，
   記錄當時 gap、封包耗時、CRC 重試次數與任何亂碼。

**驗收以前禁止把 v0.5 Draft PR 合併 main。** 此版本有從舊工程中沿用的
TI ROM `_SendAByte` 發送路徑，發送短命令／最多 48 字元輸入時仍會短暫
阻塞；接收、歷史與鍵盤主循環則是合作式非阻塞。不中斷鍵盤的程度需要
在實機量測，而不是單憑 CI 推估。

## 用模擬器預覽 UI（不需要 PC 或 Uno）

`C83DEMO.8xk`（或 `C83DEMO.8xp`）是**離線示範版**：內建一段假的對話，
提問時在計算機端直接回覆，完全不使用連線埠。適合在模擬器裡看介面、
練習按鍵，或在 ERR:LINK 解決前先檢查畫面。

1. 安裝支援原版 TI-83 Plus 的模擬器，例如 Windows 上的 Wabbitemu。
2. 需要**你自己的 ROM 檔**（有版權，無法隨專案提供）。可以在原版
   serial2ti83 韌體下用 TiLP 從自己的計算機傾印 ROM。
3. 把 `C83DEMO.8xk` 拖進模擬器，按 APPS 選 `C83DEMO`。標題列會顯示
   `CHAT83 DEMO`。

示範版和正式版共用同一份 UI 程式碼，只差在不連線。

## 開發驗證

GitHub Actions 同時執行：

- Python 3.11 unittest 全部歷史回歸，COBS/CRC8/USB-credit、LLM 串流
  和 48 行 Ring Buffer 隨機換頁測試。
- Arduino IDE/CLI **arduino:avr:uno** 韌體編譯。
- SPASM-ng（含 GMP/OpenSSL，可簽章）組譯 `C83V5.8xp`、`CHAT83.8xk`、
  `C83DEMO.8xk`、`C83DEMO.8xp`，並用 RabbitSign 驗證 App 簽章。
- **Z80 模擬測試**（`tests/test_v05_z80_emulator.py`）：在 Z80 核心上
  執行實際組譯出的程式版、App 版和示範版，攔截 ROM 呼叫並模擬
  Port 00h/05h 與 LCD，連接真正的 `bridge_v05.ConversationEngine`。
  涵蓋 SYNC、提問與串流回覆、MODE 取消、48 行快取環繞、反白選取、
  捲動條像素與 A–Z 鍵位；截圖上傳為 `CHAT83-v05-ui-screenshots`。
- 最終 CI 把上述檔案與說明、PowerShell 腳本打包為 Windows 測試套件。

這些可自動化項目**不能替代實體 Uno 的 bit-level 時序測試**。Z80 模擬
測試沒有真正的 TI ROM：`_PutMap` 的字形、`LCD_BUSY_QUICK` 的延遲、
中斷、APD 和連線電氣時序都不在測試範圍內。
