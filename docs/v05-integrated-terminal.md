# CHAT83 v0.5 — 整合測試候選版

> **狀態：原始碼、編譯及自動化測試完成後才能交付實機驗收。尚未在使用者的 Uno + TI-83 Plus 實測此新版韌體／Z80 組合。**
>
> 穩定版仍是 main 上的 v0.3.2；v0.4 是實機驗證的合作式 RX / 48 行快取版本。本 v0.5 分支不覆蓋它們。

## 架構

```text
Original TI-83 Plus
  C83V5.8xp -- Z80, _GetCSC, 48×13B ring, 6×12B staged CRC8,
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

## 第一次安裝

1. 在 Windows 安裝 Python 3.9+、TiLP 與 Arduino IDE。
2. 備份之前 v0.4 的 SQLite 資料庫及 Uno 上游 `serial2ti83.ino`。
3. 暫時拔下計算機的 Link 插頭；用 Arduino IDE 開啟
   `arduino/CHAT83_Uno_v05/CHAT83_Uno_v05.ino`，板子選
   **Arduino Uno**，序列埠選 Uno 的 COM 埠，按 Upload。
   上傳完成後關閉 Arduino IDE Serial Monitor。
4. 以 TiLP 傳入 **`C83V5.8xp`**，完全關閉 TiLP。
5. 確認沿用原本已經驗證的 Link 接線：**Uno D2 → TIP**、
   **Uno D3 → RING**、**GND → 插頭 sleeve**。
   Uno 輸出腳只會拉 LOW 或放開成 INPUT_PULLUP，不會主動將
   5V 強制輸出 HIGH；禁止在未知硬體線路上直接外加電壓。
6. Windows PowerShell 在套件資料夾執行：

   ```powershell
   py -m pip install -r requirements-v05.txt
   .\start-chat83-v05.ps1 -Port COM2 -Provider demo -GapMs 35
   ```

7. 看到 `CHAT83 Uno v0.5 handshake OK`、`Listening...` 後，
   在原版 TI-83 Plus 執行 `Asm(prgmC83V5)`。

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

## 操作

**歷史瀏覽**
- ↑／↓：本機 48 行 Ring Buffer 捲動；靠近前後 1/3 時預取六行。
  若在資料尚未下載的邊界連續按方向鍵，可暫存最多 12 次的方向意圖。
- ENTER：進入四行文字編輯器。
- MODE：模型正在生成時要求取消；若在 LINK ERROR 畫面，重新 SYNC。
- CLEAR：退出程式。

**文字編輯器**
- 預設 ALPHA ON，按計算機印有 A–Z 的實體按鍵可輸入英文字母。
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

## 開發驗證

GitHub Actions 同時執行：

- Python 3.11 unittest 全部歷史回歸，COBS/CRC8/USB-credit、LLM 串流
  和 48 行 Ring Buffer 隨機換頁測試。
- Arduino IDE/CLI **arduino:avr:uno** 韌體編譯。
- SPASM-ng Z80 組譯 `C83V5.8xp`。
- 最終 CI 把三者與說明、PowerShell 腳本打包為 Windows 測試套件。

這些可自動化項目**不能替代實體 Uno 的 bit-level 時序測試**。
