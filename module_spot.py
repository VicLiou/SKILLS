import logging
import requests

logger = logging.getLogger(__name__)

def fetch_spot_data(date_str: str) -> dict:
    """
    Fetch spot market data including open, high, low, close, volume, 
    institutional net buy, margin balance, etc.
    """
    data = {
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "volume_100M": 0.0,
        "institutional_net_buy_100M": {
            "foreign": 0.0,
            "investment_trust": 0.0,
            "dealer": 0.0
        },
        "margin_balance_100M": 0.0,
        "short_selling_balance_lots": 0
    }
    
    try:
        # Placeholder for TWSE API / FinMind API call
        # Mocking processing
        data["open"] = 21000.5
        data["high"] = 21150.0
        data["low"] = 20950.0
        data["close"] = 21100.2
        data["volume_100M"] = 4500.5
        data["institutional_net_buy_100M"]["foreign"] = 125.4
        data["institutional_net_buy_100M"]["investment_trust"] = 30.5
        data["institutional_net_buy_100M"]["dealer"] = -15.2
        data["margin_balance_100M"] = 2800.0
        data["short_selling_balance_lots"] = 150000
        
        logger.info(f"Successfully fetched spot market data for {date_str}")
    except Exception as e:
        logger.error(f"Error fetching spot market data for {date_str}: {e}")
        
    return data
