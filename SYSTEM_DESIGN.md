# 台灣股市與期貨報價腳本 - 系統分析與架構設計書 (System Design Document)

## 1. 需求概述
開發一支 Python 腳本（Script），用於精準抓取台股現貨、期貨、選擇權籌碼、總體經濟數據與跨市場指標，並具備計算技術指標之功能。
系統需支援傳入特定日期參數（`--date YYYYMMDD`），以利歷史資料查詢與回測，最終將所有彙整資料以標準結構化 JSON 格式輸出，確保與其他系統對接時不產生解析錯誤（避免 AI 幻覺）。

## 2. 資料來源評估 (Data Sources Assessment)

為確保穩定性與歷史查詢能力，優先選擇官方 OpenAPI，輔以成熟的開源套件庫：

| 資料類型 | 資料項目 | 推薦來源 / 套件 | 理由與備註 |
| :--- | :--- | :--- | :--- |
| **期權籌碼** | 三大法人期貨未平倉(外資淨未平倉)、十大特法、P/C Ratio、小台多空比 | **TAIFEX 台灣期交所 OpenAPI** / **FinMind** | 期交所官方資料最精準；若需快速串接歷史，FinMind 提供了極為穩定的開源 API 封裝。散戶小台多空比需由「小台指未平倉」與「三大法人小台未平倉」推算。 |
| **現貨大盤** | 三大法人現貨買賣超、信用交易(融資券)、大盤量價(開高低收、成交量值) | **TWSE 台灣證交所 OpenAPI** / **FinMind** | 證交所 API (如 `MI_INDEX`, `MI_MARGN`, `BFI82U`) 提供完整日報；FinMind 同樣可作為備援。 |
| **總經跨市場** | TSM ADR、美元/台幣匯率、VIX、美債10年殖利率 | **Yahoo Finance (`yfinance`)** | 針對美股與匯率，`yfinance` Python 套件免費且極度穩定，適合抓取 TSM, TWD=X, ^VIX, ^TNX。 |
| **台指夜盤** | 台指期夜盤收盤價 | **TAIFEX 盤後交易資訊** / **FinMind** | 期交所盤後交易統計表。 |
| **技術指標** | MA(5/10/20/60)、BIAS、KD、RSI、MACD | **`pandas-ta`** + **大盤歷史資料** | 利用歷史的大盤量價資料，透過 `pandas-ta` (或 `TA-Lib`) 進行矩陣運算，確保公式標準化且無誤差。 |

## 3. 模組拆解與架構規劃

腳本預計採用模組化 (Modular) 設計，包含一個 Controller 負責排程與參數解析，以及五個對應的 Worker 模組。

- **`main.py` (Controller)**: 
  - 解析命令列參數 `--date` (預設為當日)。
  - 初始化非同步 (AsyncIO) 或多執行緒池，併發呼叫各資料模組。
  - 將各模組回傳的 `dict` 進行合併，並轉儲為 JSON。
- **`module_chips.py` (期權籌碼模組)**: 封裝對期交所/FinMind的請求，計算小台多空比。
- **`module_spot.py` (現貨大盤模組)**: 封裝對證交所的請求，清洗大盤數據與三大法人現貨買賣超。
- **`module_macro.py` (總經跨市場模組)**: 封裝 `yfinance` 查詢，計算 TSM 溢價率 (需結合 TSM ADR 收盤價與 台積電 2330.TW 收盤價與匯率)。
- **`module_technical.py` (技術指標模組)**: 從資料庫或透過 API 往前多抓取 60~100 天的大盤資料，餵入 `pandas-ta` 計算當日（`--date`）的指標數值。
- **`module_formatter.py` (資料輸出模組)**: 驗證所有資料欄位與型別，處理 `NaN`/`Null`，輸出嚴謹的 JSON。

## 4. 執行流程 (Execution Flow)

1. **參數輸入**: 接收 `--date 20260506`。如果遇到假日，程式可自動尋找「前一個交易日」或直接回傳空資料（依後續實作細節而定）。
2. **併發請求**: 
   - 同時向 TWSE, TAIFEX, Yahoo Finance 發出資料請求。
   - 針對技術指標，額外抓取所需的回溯區間 (如 `--date` 往前 90 天)。
3. **資料清洗與計算**:
   - 統一金額單位 (例如：億元)。
   - 計算 TSM 溢價率 = `((TSM * 匯率) / (台積電股價 * 5) - 1) * 100%`。
   - 計算 小台散戶多空比 = `(-三大法人小台淨未平倉) / 全市場小台未平倉`。
   - 計算並抽取 `--date` 當日的 TA 指標。
4. **組裝驗證**: 確保無遺漏，組裝為 Pydantic Model 或標準 Dictionary，序列化為 JSON。
5. **輸出**: 列印至標準輸出 (stdout) 或寫入 `output_{date}.json`。

## 5. JSON Schema 定義範例

為避免後續其他系統（或 LLM）解析錯誤，採用單層或雙層的扁平/結構化設計：

```json
{
  "date": "2026-05-06",
  "spot_market": {
    "open": 21000.5,
    "high": 21150.0,
    "low": 20950.0,
    "close": 21100.2,
    "volume_100M": 4500.5,
    "institutional_net_buy_100M": {
      "foreign": 125.4,
      "investment_trust": 30.5,
      "dealer": -15.2
    },
    "margin_balance_100M": 2800.0,
    "short_selling_balance_lots": 150000
  },
  "futures_options": {
    "foreign_tx_net_oi": 12000,
    "top10_specific_tx_net_oi": 5000,
    "options_pc_ratio": 115.5,
    "retail_mtx_long_short_ratio": -0.15
  },
  "macro_cross_market": {
    "tsm_adr_premium_percent": 12.5,
    "usd_twd_rate": 32.50,
    "vix_index": 14.2,
    "us_10y_yield": 4.25,
    "tx_night_session_close": 21150.0
  },
  "technical_indicators": {
    "ma_5": 20800.0,
    "ma_10": 20500.0,
    "ma_20": 20100.0,
    "ma_60": 19500.0,
    "bias_20_percent": 4.97,
    "kd_k": 85.2,
    "kd_d": 80.5,
    "rsi_14": 72.5,
    "macd": 150.5,
    "macd_signal": 120.0,
    "macd_hist": 30.5
  }
}
```

## 6. 後續開發建議
1. **快取機制**: 建議在本地實作 SQLite 或檔案快取 (Cache)，避免因測試期間頻繁抓取而遭 API 限流 (尤其是 Yahoo Finance 或 FinMind)。
2. **異常處理 (Retry)**: 網路請求需加上 Retry 機制，若 TWSE/TAIFEX 網站短暫無法連線，應延遲重試。
3. **依賴套件**: 開發環境準備 `requirements.txt` (包含 `requests`, `yfinance`, `pandas`, `pandas-ta`, `pydantic`)。
