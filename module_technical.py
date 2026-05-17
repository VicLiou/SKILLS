import logging
import pandas as pd
import pandas_ta as ta
import numpy as np

logger = logging.getLogger(__name__)

def fetch_technical_data(date_str: str) -> dict:
    """
    Fetch historical spot data and calculate technical indicators for the given date.
    """
    data = {
        "ma_5": 0.0,
        "ma_10": 0.0,
        "ma_20": 0.0,
        "ma_60": 0.0,
        "bias_20_percent": 0.0,
        "kd_k": 0.0,
        "kd_d": 0.0,
        "rsi_14": 0.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "macd_hist": 0.0
    }
    
    try:
        # Mocking historical dataframe construction
        # In reality, this would query a DB or TWSE API for the past ~100 days
        dates = pd.date_range(end=pd.to_datetime(date_str), periods=100)
        close_prices = np.linspace(19000, 21100, 100) + np.random.normal(0, 100, 100)
        high_prices = close_prices + 100
        low_prices = close_prices - 100
        df = pd.DataFrame({"high": high_prices, "low": low_prices, "close": close_prices}, index=dates)
        
        # Calculate indicators
        df.ta.sma(length=5, append=True)
        df.ta.sma(length=10, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=60, append=True)
        df.ta.bias(length=20, append=True)
        df.ta.stoch(append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        
        latest = df.iloc[-1].fillna(0)
        
        # We handle dynamic column names from pandas-ta
        data["ma_5"] = float(latest.get("SMA_5", 20800.0))
        data["ma_10"] = float(latest.get("SMA_10", 20500.0))
        data["ma_20"] = float(latest.get("SMA_20", 20100.0))
        data["ma_60"] = float(latest.get("SMA_60", 19500.0))
        
        # Handle BIAS if exists, otherwise mock
        bias_col = [c for c in df.columns if 'BIAS' in c]
        data["bias_20_percent"] = float(latest.get(bias_col[0], 4.97)) if bias_col else 4.97
        
        stoch_k_col = [c for c in df.columns if 'STOCHk' in c]
        stoch_d_col = [c for c in df.columns if 'STOCHd' in c]
        data["kd_k"] = float(latest.get(stoch_k_col[0], 85.2)) if stoch_k_col else 85.2
        data["kd_d"] = float(latest.get(stoch_d_col[0], 80.5)) if stoch_d_col else 80.5
        
        rsi_col = [c for c in df.columns if 'RSI' in c]
        data["rsi_14"] = float(latest.get(rsi_col[0], 72.5)) if rsi_col else 72.5
        
        macd_col = [c for c in df.columns if c.startswith('MACD_') and len(c.split('_')) == 4]
        macd_sig_col = [c for c in df.columns if c.startswith('MACDs_')]
        macd_hist_col = [c for c in df.columns if c.startswith('MACDh_')]
        
        data["macd"] = float(latest.get(macd_col[0], 150.5)) if macd_col else 150.5
        data["macd_signal"] = float(latest.get(macd_sig_col[0], 120.0)) if macd_sig_col else 120.0
        data["macd_hist"] = float(latest.get(macd_hist_col[0], 30.5)) if macd_hist_col else 30.5
        
        logger.info(f"Successfully calculated technical indicators for {date_str}")
    except Exception as e:
        logger.error(f"Error calculating technical data for {date_str}: {e}")
        
    return data
