import argparse
import json
import sqlite3
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import requests
import time
import os

# Configuration
DB_PATH = "market_cache.db"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Table for TWSE OHLC (Spot)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spot_history (
            date TEXT PRIMARY KEY,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
    ''')
    conn.commit()
    conn.close()

def get_spot_data(date_str):
    """Fetch TWSE spot data. Uses cache if available."""
    conn = sqlite3.connect(DB_PATH)
    df_cache = pd.read_sql(f"SELECT * FROM spot_history WHERE date <= '{date_str}' ORDER BY date DESC LIMIT 100", conn)
    
    if len(df_cache) < 100:
        # Fetch from yfinance (as fallback/primary for history)
        # ^TWII is TAIEX
        ticker = yf.Ticker("^TWII")
        end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        start_date = end_date - timedelta(days=200)
        hist = ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
        
        if not hist.empty:
            hist.reset_index(inplace=True)
            hist['Date'] = hist['Date'].dt.strftime("%Y-%m-%d")
            for _, row in hist.iterrows():
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO spot_history (date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (row['Date'], row['Open'], row['High'], row['Low'], row['Close'], row['Volume']))
            conn.commit()
            df_cache = pd.read_sql(f"SELECT * FROM spot_history WHERE date <= '{date_str}' ORDER BY date DESC LIMIT 100", conn)
    
    conn.close()
    return df_cache.iloc[::-1].reset_index(drop=True) # Return in ascending order

def get_finmind_data(date_str):
    """Fetch Futures Institutional Investors from FinMind."""
    dl = DataLoader()
    # TaiwanFuturesInstitutionalInvestors
    df = dl.taiwan_futures_institutional_investors(
        futures_id="TX",
        start_date=(datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
        end_date=date_str
    )
    if not df.empty:
        # Filter for the specific date
        df_target = df[df['date'] == date_str]
        if not df_target.empty:
            # Foreign investors are usually in the rows
            foreign = df_target[df_target['institutional_investors'] == 'ForeignInvestors']
            if not foreign.empty:
                # Based on help: long_open_interest_balance_volume - short_open_interest_balance_volume
                net_oi = int(foreign.iloc[0]['long_open_interest_balance_volume']) - int(foreign.iloc[0]['short_open_interest_balance_volume'])
                return net_oi
    return 0

def get_pc_ratio(date_str):
    """Calculate P/C Ratio from Put/Call Volume/OI (Simulated or via API if possible)."""
    # In a real scenario, we'd fetch from Taifex. For now, we simulate or use placeholders.
    # TAIFEX API is not trivial, often requires scraping or specific Open Data CSVs.
    return 1.0 # Placeholder

def calculate_technical(df):
    if df.empty or len(df) < 60:
        return {}
    
    # Use pandas_ta
    # ma is not directly on ta attribute in newer versions sometimes, or needs different call
    df['MA_5'] = ta.sma(df['close'], length=5)
    df['MA_10'] = ta.sma(df['close'], length=10)
    df['MA_20'] = ta.sma(df['close'], length=20)
    df['MA_60'] = ta.sma(df['close'], length=60)
    
    # RSI
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    
    # MACD
    macd = ta.macd(df['close'])
    df = pd.concat([df, macd], axis=1)
    
    # KD
    kd = ta.stoch(df['high'], df['low'], df['close'])
    df = pd.concat([df, kd], axis=1)
    
    # BIAS (manual calculation or custom)
    df['BIAS_20'] = (df['close'] - df['MA_20']) / df['MA_20'] * 100
    
    latest = df.iloc[-1]
    
    # MACD columns usually look like MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9
    # STOCH columns usually look like STOCHk_14_3_3, STOCHd_14_3_3
    
    # API rate limit handling (simple sleep)
    time.sleep(1)

    return {
        "ma": {
            "ma5": round(float(latest['MA_5']), 2),
            "ma10": round(float(latest['MA_10']), 2),
            "ma20": round(float(latest['MA_20']), 2),
            "ma60": round(float(latest['MA_60']), 2)
        },
        "bias": {
            "bias_20": round(float(latest['BIAS_20']), 2)
        },
        "indicators": {
            "kd": {
                "k": round(float(latest.filter(like='STOCHk').iloc[0]), 2),
                "d": round(float(latest.filter(like='STOCHd').iloc[0]), 2)
            },
            "rsi_14": round(float(latest['RSI_14']), 2),
            "macd": {
                "dif": round(float(latest.filter(regex='^MACD_').iloc[0]), 2),
                "dea": round(float(latest.filter(regex='^MACDs_').iloc[0]), 2),
                "histogram": round(float(latest.filter(regex='^MACDh_').iloc[0]), 2),
                "divergence_warning": False
            }
        }
    }

def get_macro_data(date_str):
    """Fetch Macro data from yfinance."""
    # TSM ADR Premium calculation
    # Formula: (TSM/5 * rate) / 2330_close - 1
    tsm = yf.Ticker("TSM").history(start=date_str, end=(datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
    twd = yf.Ticker("TWD=X").history(start=date_str, end=(datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
    vix = yf.Ticker("^VIX").history(start=date_str, end=(datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
    tnx = yf.Ticker("^TNX").history(start=date_str, end=(datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
    
    # For TSM ADR Premium, we need 2330.TW as well
    tw2330 = yf.Ticker("2330.TW").history(start=date_str, end=(datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"))
    
    premium = 0
    if not tsm.empty and not twd.empty and not tw2330.empty:
        tsm_price = tsm.iloc[0]['Close']
        rate = twd.iloc[0]['Close']
        tw2330_price = tw2330.iloc[0]['Close']
        premium = ((tsm_price / 5 * rate) / tw2330_price - 1) * 100

    return {
        "tsm_adr_premium_percent": round(float(premium), 2),
        "usd_twd_rate": round(float(twd.iloc[0]['Close']), 2) if not twd.empty else 0,
        "vix": round(float(vix.iloc[0]['Close']), 2) if not vix.empty else 0,
        "us_10y_yield": round(float(tnx.iloc[0]['Close']), 2) if not tnx.empty else 0,
        "night_session_close": 0 # Placeholder
    }

def main():
    parser = argparse.ArgumentParser(description="Taiwan Market Data API")
    parser.add_argument("--date", type=str, help="Target date in YYYY-MM-DD format", required=True)
    args = parser.parse_args()
    
    target_date = args.date
    init_db()
    
    result = {
        "query_date": target_date,
        "status": "success",
        "data": {
            "chips": {},
            "spot": {},
            "macro": {},
            "technical": {}
        },
        "errors": []
    }
    
    try:
        # 1. Chips
        foreign_oi = get_finmind_data(target_date)
        result["data"]["chips"] = {
            "foreign_futures_oi": foreign_oi,
            "top10_specific_oi": 0, # Placeholder
            "pc_ratio": get_pc_ratio(target_date),
            "retail_mtx_long_short_ratio": 0 # Placeholder
        }
        
        # 2. Spot & Technical
        df_spot = get_spot_data(target_date)
        if not df_spot.empty:
            latest_spot = df_spot[df_spot['date'] == target_date]
            if not latest_spot.empty:
                row = latest_spot.iloc[0]
                result["data"]["spot"] = {
                    "institutional_net_buy": 0, # Placeholder
                    "margin_balance": 0, # Placeholder
                    "short_balance": 0, # Placeholder
                    "ohlc": {
                        "open": float(row['open']),
                        "high": float(row['high']),
                        "low": float(row['low']),
                        "close": float(row['close'])
                    },
                    "total_volume": float(row['volume'])
                }
            
            # Technical Indicators
            result["data"]["technical"] = calculate_technical(df_spot)
            
        # 3. Macro
        result["data"]["macro"] = get_macro_data(target_date)
        
    except Exception as e:
        result["status"] = "partial_success"
        result["errors"].append(str(e))
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
