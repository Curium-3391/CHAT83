# CHAT83 v0.5 — 整合實機測試與安裝說明

> **狀態（2026-10-21）：真機已驗證一輪 demo 問答！** TI-83 Plus 上實際看到 `PC: WORLD`，Windows 收到 `Q 'HELLO'`，而 SYNC 與 Q 回覆都由 Uno 確認完成 45 + 33 bytes 傳輸，零回報錯誤。使用者已批准合併 v0.5。
>
> **目前有效實機設定：** Uno TIP=D3、RING=D6、GND=sleeve，COM2／115200 baud，`--provider demo --gap-ms 35 --reply-delay-ms 250`。這不代表 250ms 可省略，也不代表重複長時間測試、長答與實際 OpenAI/Ollama 已完成。以下「尚未驗證／Draft」字句若位於較早期的診斷紀錄，請視為當時狀態，非現在的專案總結。

## 架構

```text
Original TI-83 Plus
  CHAT83.8xk App (or C83V5.8xp) -- Z80, _GetCSC, 48×13B ring, 6×12B staged CRC8,
  4×12B editor, 16-row predictive trigger, polling for live LLM rows
       | TIP / RING / GND (2.5mm link)
Arduino Uno ATmega328P
  D3 = TIP, D6 = RING, GND = sleeve
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

**使用者已再次確認實際接線：TIP 接 D3，RING 接 D6，GND 接 sleeve。
新版 v0.5 原始碼已同時採用 TIP=3、RING=6。上游 `serial2ti83` 預設
TIP=2、RING=3；如果使用上游韌體配合這條線傳送 TiLP 檔案，必須
**兩個常數一起改成 TIP=3、RING=6**，或者把實際接線改回上游標準。
絕不能只改 RING。**

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
3. 用之前驗證過的 Uno TIP=D3／RING=D6／GND 接線，**在原版韌體下
   使用 TiLP 傳入 `CHAT83.8xk`**（建議，Flash App），確認計算機的
   **APPS** 選單出現 `CHAT83`。也可以改傳 `C83V5.8xp`，它會出現在
   PRGM 清單。兩者功能相同，可同時保留。完整關閉 TiLP，釋放 COM 埠。
4. 暫時拔下計算機的 Link 插頭，再用 Arduino IDE 開啟
   `CHAT83_Uno_v05.ino`，板子選 Arduino Uno，重新上傳新的 v0.5
   韌體。上傳完成後關閉 Arduino IDE 的 Serial Monitor，重新接上
   計算機原本的 Link 接線。
5. 確認接線：**Uno D3 → TIP、D6 → RING、GND → sleeve**。
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
   插頭接回原 D3/TIP、D6/RING、GND 接線。
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


### 2026-10-21 補充：確認 Uno E5 逾時與診斷修復

最終由使用者更正實際接線：**D3=TIP、D6=RING**，與上游預設的 D2=TIP、D3=RING 都不同。
先前刷的 Uno／Python 可正常 `handshake OK`，但在計算機 Link
嘗試後，Python 最後報 `Arduino error code 5`（Uno 的
`RX_WAIT_RELEASE` 等待 TI 釋放其起始位元的線路超過 30ms）。
錯誤前的多行 `start=0 ack=0` 是逾時以前的取樣，
不代表逾時瞬間沒有接到電氣訊號；該錯誤本身證明 Uno 進過 RX 等待狀態。
原版 Python 一收到 E5 就退出，導致無法取得接下來的 J 診斷封包。

**新版診斷：** 使用 `--debug-link` 時，USB 層只將 `E5`
視為應記錄的 RX 逾時並繼續讀取 `J`，使用者可於計算機報錯後
保留 Python 約兩秒、取得 `start/ack/rx_to/TIP/RING`，
最後按 Ctrl+C。**其他錯誤仍會中止，平常未開 debug 仍對 E5 fail-fast。**
新的 ZIP 中 Uno 韌體與原始碼預設 TIP=3、RING=6；如果實際 Uno 已自行修改並
重新上傳採用 **兩個正確腳位**，僅需替換新版 `usb_v05.py` 即可先做診斷，
不必重燒、也不必重傳計算機 App。實際握手仍未通過驗收。


### 2026-10-21 第二次實機診斷：E5 後的計數器與最終腳位更正

使用者在修正版 Python `--debug-link` 下取得成功保留的故障後數據：
`start=84, ack=3, rx_bytes=0, rx_to=81, tx_to=0`，中途曾見
`state=1 TIP=L RING=L`，最終閒置時兩線為 HIGH。
這證明 Uno 的接收 FSM 多次進入等待並逾時、沒有收到完整的第一個 byte；
不像是 LLM、SQLite 或 Windows USB 連線錯誤。

**關鍵更正：使用者在這份紀錄後明確聲明實際腳位為
`const int TIP = 3;`、`const int RING = 6;`。**
上一輪工程與文件誤以為 TIP=2、RING=6，本分支現已改為
TIP=3、RING=6，加入 native C++ `static_assert` 防止將來倒退。
但仍須分辨：產生上述 E5 的**當時實際燒錄的 Uno 韌體**是否已
同時採用這兩個腳位。如果已經使用正確的 3/6，則 E5 仍是真實握手
失敗，需要進一步量測；不能直接宣告修改腳位已經解決故障。
換上正確韌體之前先移除 TI 2.5mm 插頭，刷完再接回。


### 2026-10-21 新突破：D3/D6 後完成 TI→PC SYNC，首次觀察到 PC→TI TX timeout

**使用者的真機證據（TIP D3、RING D6，Uno v0.5，COM2，`--debug-link`）：**

```text
[UNO-DIAG] start=8 ack=8 rx_bytes=1 rx_to=0 tx_to=0 state=0 TIP=H RING=H last_rx=0x53
SYNC -> 0 rows, flags=04, 9 bytes
[UNO-DIAG] start=16 ack=16 rx_bytes=2 rx_to=0 tx_to=0 state=0 TIP=H RING=H last_rx=0x53
SYNC -> 0 rows, flags=04, 9 bytes
Uno link statistics: {'tx': 18, 'rx': 12, 'errors': 0, 'gap_ms': 35, 'rx_timeout_events': 0}
LINK ERROR: Uno TI TX failed at 0: b'A\\x03\\x01'
```

**結論與限制：** 前兩次 `S` (0x53) 各完成 8-bit 接收，
Windows 應用確實處理了兩個 SYNC，且 Uno 對兩筆 9-byte 返信批次
回報成功（共 18 bytes）。第三筆 USB TX `A,seq=3,status=1`
表示 **TI Link 發送逾時**；`at 0` 是該批次相對回覆的起始位址，
**不能推斷第一個 byte 就失敗**，可能是在 16-byte 批次內某個
較後面的 bit。Python 此時不會印 `SYNC/Q` 成功行，
因為目前 `link.write` 回傳之後才會印出標籤。
`rx=12` 包含兩個 SYNC 的 2 bytes，加上 10 bytes 其他 TI 請求，
但未有故障前原始內容紀錄，尚不能確定第三個請求為何。

**待證假說：** Z80 的 `input_send` 在發送完 `Q` 後
`enable_rx` 隨即 `call draw_history`；PC 可能在畫面重繪期間
開始送出較長的 C reply，導致未即時讀取 Port 05h 的單位元組
接收緩衝，從而讓 Uno TX bit handshake 逾時。Z80 emulator
沒有模擬實體 LCD/ROM 接收時序，CI 不能證明此假說。
也不能排除 Uno TX FSM 自身的 ACK 時序問題。

**無須更新 Uno/TI 的測試：** 僅替換新版本 `bridge_v05.py`，
使用 `--reply-delay-ms 250` 在所有 PC→TI 回覆開始前延遲
250ms，保持 `--gap-ms 35 --debug-link`。
現在 bridge 會在真正 USB `T` 發送前記錄
`[TX-BEGIN] Q '...': N bytes (M batches), turnaround=250ms`，
有助確認失敗的命令與封包大小。若仍失敗，
回報 `[TX-BEGIN]`、發生失敗時的 `[UNO-DIAG]`、
計算機畫面及 `Uno TI TX failed...`；無須重複整份 idle 日誌。

```powershell
py "$HOME\\Downloads\\CHAT83_v05\\bridge_v05.py" --port COM2 --provider demo --gap-ms 35 --debug-link --reply-delay-ms 250
```

注意：250ms 是暫時診斷參數，預設仍是 0；若有效，
應正式修正計算機端「接收時不可重畫完整 LCD」的時序，
不能把人工延遲視為最終可靠性解決方案。


### 2026-10-21 實機 250ms 成功驗證：SYNC 與 HELLO 的 Link 往返完成

使用者依照上述命令測試了正確接線 **TIP=D3、RING=D6** 與
`--reply-delay-ms 250 --gap-ms 35 --debug-link`，第一次觀察到
**兩組實際 PC→TI 回覆完全送完，且 TI→PC 完整接收 Q 'HELLO'**：

```text
[TX-BEGIN] SYNC: 45 bytes (3 batches), turnaround=250ms
[UNO-DIAG] start=8 ack=8 rx_bytes=1 rx_to=0 tx_to=0 state=0 TIP=H RING=H last_rx=0x53
SYNC -> 3 rows, flags=04, 45 bytes
[TX-BEGIN] Q 'HELLO': 33 bytes (3 batches), turnaround=250ms
[UNO-DIAG] start=80 ack=80 rx_bytes=10 rx_to=0 tx_to=0 state=0 TIP=H RING=H last_rx=0xDE
Q 'HELLO' -> 2 rows, flags=01, 33 bytes
Uno link statistics: {'tx': 78, 'rx': 10, 'errors': 0, 'gap_ms': 35, 'rx_timeout_events': 0}
Stopped
```

**計數解釋：** PC→TI 成功確認傳送 45+33=78 bytes；
TI→PC 完成 1-byte S 與 9-byte Q（Q、LEN、5-byte HELLO、
LATEST、CRC8），共 10 bytes，80 次 bit-start 和 ACK 配對。
USB、Uno 以及實體 Link 傳送層在這一次測試**沒有回報錯誤**。
`SYNC` 帶 3 行歷史表示 SQLite 中已有先前對話；不是異常。

**尚未在使用者畫面確認：** 計算機是否正確解析 C frame 並顯示
`PC: WORLD`，以及連續提問、長答、捲動、重試功能是否可靠。
「整條傳輸鏈有一次正確完成」不等於 UI/應用層全部實機驗收通過。
尤其這是 **帶 250ms turnaround 的單次成功**，
還不能斷言時間延遲就是唯一根因，也不應刪除這個參數或直接
將 PR #7 合併 main。

**下一步：** 保持所有韌體與現有延遲設定不變，先確認 TI 顯示
`PC: WORLD`，再重複 HELLO 與其他簡短問題測穩定度。
如 UI 確認正確，才比較 `--reply-delay-ms 250`、100、0 的結果，
並研究 Z80 `input_send` 畫面重繪是否讓接收緩衝溢位。


### 2026-10-21 最終實機驗收：HELLO → PC: WORLD

使用者補充確認：在先前成功送出完整 `Q 'HELLO'`、成功回傳
33-byte 兩行 C frame 的紀錄之後，**TI-83 Plus 螢幕確實顯示
`PC: WORLD`**。這補足了之前僅有 USB／Uno 端計數器、
卻尚未確認 Z80 UI 的最後一項證據。使用者也已**明確授權合併到 main**。

此次驗證精確涵蓋的內容：
- 由原始 TI-83 Plus 送出 ASCII `S`、`Q HELLO`；
- Uno 以 TIP=D3、RING=D6 正確接收並透過 USB 傳給 Python；
- Python Demo Provider 產生 `WORLD` 回覆；
- Uno 分批傳送 45-byte SYNC、33-byte Q 回覆，回報全數完成；
- 計算機端實際顯示 `PC: WORLD`。

**尚未驗收：** 取消 250ms turnaround、低於 35ms 的 inter-byte gap、
高負載長串流、連續問答多次與實際雲端 LLM provider。
這些可在後續獨立 PR 改進，不影響將已通過的
**v0.5 demo 端到端驗收里程碑**納入 main。


### 2026-10-21 第三次實機待測：重開編輯器殘影與縮短 turnaround

**使用者回報（Gemini API 已在真機上運作）：** 送出訊息後再次按
ENTER 進入「NEW MESSAGE」，畫面上還能看到先前送出的文字，
卻不能按 DEL 刪掉，也無法用 LEFT/RIGHT 移動游標。

**已從原始碼找到可重現的成因：** `input_screen` 重設
`input_len=0`、`input_cursor=0`，卻只清掉 `input_buf` 的
**第一個 byte**；`draw_input` 直接畫滿 48 個字元格，
使以前內容殘留，且因為長度與游標已為 0，DEL／RIGHT 都視為
空輸入而不動。修正版在進入編輯器時用 `zero_fill`
將 **49-byte buffer（48 字 + NUL）完整清零**。

**同時將 Q 傳送和畫面重繪重新排序：**
先離開輸入模式、關閉 RX assist、把 `request_kind` 設成 Q、
**先畫好「等待回覆」的 HISTORY 畫面**，再呼叫
`send_bytes` 送出 Q；最後 reset RX 並 enable RX，
其後不再呼叫完整 `draw_history`。這個修改是為了避免
PC→TI 回覆已開始，而 Z80 卻被 LCD 重繪阻塞，造成
Uno TX timeout。注意：這是**實機時序假說**，仍須在真機驗證。

#### 安裝與安全回退

- 本分支只修改 `calculator/CHAT83_v05_chat.asm`，
  及加入針對 App + ASM program 的 Z80 模擬回歸測試。
  **Uno 使用 TIP=D3、RING=D6，不修改韌體或接線。**
- 測試包中新的 `CHAT83.8xk`（或 `C83V5.8xp`）
  必須**重新傳到 TI-83 Plus**，替換原版 Z80 程式。
  **只替換 Python 並無法修復 83 端的輸入編輯器。**
- 若用同一塊 Uno + TiLP 傳檔，必須先刷回
  `serial2ti83` 並將它的腳位常數也改成
  `TIP=3; RING=6;`，完成傳輸後再刷回 CHAT83 v0.5
  韌體（TIP=D3、RING=D6；115200 baud）。
  重新刷韌體之前先拔下 TI 的 2.5mm 插頭。
- 正式穩定版仍在 `main`；本次修改在
  `fix/ti83-editor-reset-and-turnaround` **Draft PR**，
  若不順利可以傳回原版 `CHAT83.8xk` 恢復舊版。

#### 分兩階段測試

1. **先維持已證實的設定：**

   ```powershell
   py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider gemini --model gemini-3.5-flash-lite --gap-ms 35 --reply-delay-ms 250 --debug-link
   ```

   在計算機提問 `HELLO`，等回覆完成；再按 ENTER。
   此時 NEW MESSAGE 內容應當是空白（只有空的反白游標），
   DEL／RIGHT 不會移動是正常的，因為長度等於 0。
   輸入 `HELLO`、按 LEFT、DEL，必須看到文字與游標確實更新，
   並能送出第二次問題。再測 Gemini UPDATE 長答及捲動。

2. **僅在第一階段成功後**，保持 Uno、App 不變，
   比較 `--reply-delay-ms 100`、`50`、`0`。
   每次都重新啟動 Bridge、在 TI 問至少兩次短問題，
   確認 LCD 內容與 `[UNO-DIAG] tx_to=0, rx_to=0`。
   若出現任何 `Uno TI TX failed`、亂碼或卡住，
   立即退回 250ms；**模擬器無法證明 0ms 實機安全**。
   運作穩定時，再單獨量測 `--gap-ms` 的縮減，
   不要在同一輪同時調整兩個參數。

CI 的 App/Program Z80 emulator 已驗證完整清空、
重開後按鍵、第二次發送與在第一個 Q byte 前完成重畫，
但物理 UART/Link 的時序測試仍由真機補足。

#### Gemini 長篇閱讀實驗（獨立於 Link 時序）

Python Bridge 新增可選的 `--word-wrap`（預設關閉），在
12 字元寬度下**盡量不拆開英文單字**，並正確跨越 Gemini
streaming token 分界來暫存未完成的詞。超過單行的長詞仍可分行。
已提交到 SQLite 的行保持不可變，避免拉取舊歷史時文字位移。
原有 `StableRows` 不變，沒啟用 `--word-wrap` 的顯示結果
與之前完全相同。

此功能只需替換套件內的 `bridge_v05.py`，
**不需要再刷 Uno 或另裝 App**（但上面的輸入殘影修正
必須更新 App）。請在 250ms 穩定驗證後才另測：

```powershell
py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider gemini --model gemini-3.5-flash-lite --gap-ms 35 --reply-delay-ms 250 --word-wrap
```

測試完成再考慮降低回覆延遲，避免把分行 Bug 和位元握手時序混為一談。


#### 2026-10-21 第二階段真機回報：FETCH OLDER @1 (6) 的 TX_WAIT_ACK

使用者回報（新 App／250ms turnaround、35ms inter-byte gap）
在上捲讀取 SQLite 較舊紀錄時：

```text
[TX-BEGIN] FETCH OLDER @1 (6): 81 bytes (6 batches), turnaround=250ms
[UNO-DIAG] start=248 ack=248 rx_bytes=31 rx_to=0 tx_to=0 state=3 TIP=L RING=H last_rx=0x19
Uno link statistics: {'tx': 196, 'rx': 31, 'errors': 0, 'gap_ms': 35, 'rx_timeout_events': 0}
LINK ERROR: Uno TI TX failed at 16: b'A\\x10\\x01'
```

**已確認的物理意義：** `state=3` 是 Uno 韌體
`TX_WAIT_ACK`。此時 Uno 在 TIP 拉低等待對方在 RING 回應，
但目前沒有偵測到 ACK；`A seq=0x10 status=1` 是
Uno 在 `BIT_TIMEOUT_US=50000` us 內沒等到 TI ACK。
`at 16` 指 **81-byte reply 的第二個 16-byte USB 批次起始偏移**
（第一批已獲 ACK）；不能說第 17 個 byte 肯定失敗，
也不能假設 `errors=0` 意味著沒有傳送逾時
（那是 Python `E` event 統計，與 `A status=1` 不同）。
資料來自實機，源頭不是 Gemini API 或 Uno 物理腳位設定；
但 **TI 為什麼沒有 ACK 尚未證明**，可能涉及接收 assist、
歷史按鍵的 LCD 刷新、跨 batch 時序或特定負載。

**暫定安全測試，不要繼續降低回覆延遲：**

1. 先保留舊、已成功的 `--reply-delay-ms 250`，先把
   `--gap-ms 35` 改成 `--gap-ms 50`，不改其他設定，
   以同樣流程（提問兩次、按 UP 捲到上界、等 FETCH OLDER）
   觀察是否仍於第 16 byte 批次附近失敗。
2. 若 50 ms 仍失敗，可改用此新測試包的 Python
   `--batch-pause-ms 150`，對每個**已成功 ACK 的 16-byte**
   分組之間加上 150ms 休息（**不是**位元或單 byte ACK timeout
   的自動重試）。建議先使用 `--gap-ms 35` 維持可比性：
   ```powershell
   py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider gemini --model gemini-3.5-flash-lite --gap-ms 35 --reply-delay-ms 250 --batch-pause-ms 150 --debug-link
   ```
   在輸出中會有 `[UNO-TX] batch boundary @16: pause 150ms`。
3. **不要同時改 250ms、35ms 和 batch pause。** 每次只調一項，
   才能判斷改善是否有效。若再次 TX timeout，
   應保留 `TX-BEGIN`／`UNO-DIAG`／`failed at N`，
   並說明計算機畫面（仍在 HISTORY、顯示 LINK ERROR、或卡住）。
   TX timeout 後需先重啟 bridge／App、必要時重同步，切勿盲目
   重送剩餘 65 bytes；在 C reply 中途重送會破壞協定框架。

`--batch-pause-ms` 預設為 0，不影響原本已確認的 Demo／Gemini
路徑。它屬於診斷變因，不應當作已證明的根因修復。
