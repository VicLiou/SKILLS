from pydantic import BaseModel, Field
from typing import Optional

class InstitutionalNetBuy(BaseModel):
    foreign: Optional[float] = 0.0
    investment_trust: Optional[float] = 0.0
    dealer: Optional[float] = 0.0

class SpotMarket(BaseModel):
    open: Optional[float] = 0.0
    high: Optional[float] = 0.0
    low: Optional[float] = 0.0
    close: Optional[float] = 0.0
    volume_100M: Optional[float] = 0.0
    institutional_net_buy_100M: InstitutionalNetBuy = InstitutionalNetBuy()
    margin_balance_100M: Optional[float] = 0.0
    short_selling_balance_lots: Optional[int] = 0

class FuturesOptions(BaseModel):
    foreign_tx_net_oi: Optional[int] = 0
    top10_specific_tx_net_oi: Optional[int] = 0
    options_pc_ratio: Optional[float] = 0.0
    retail_mtx_long_short_ratio: Optional[float] = 0.0

class MacroCrossMarket(BaseModel):
    tsm_adr_premium_percent: Optional[float] = 0.0
    usd_twd_rate: Optional[float] = 0.0
    vix_index: Optional[float] = 0.0
    us_10y_yield: Optional[float] = 0.0
    tx_night_session_close: Optional[float] = 0.0

class TechnicalIndicators(BaseModel):
    ma_5: Optional[float] = 0.0
    ma_10: Optional[float] = 0.0
    ma_20: Optional[float] = 0.0
    ma_60: Optional[float] = 0.0
    bias_20_percent: Optional[float] = 0.0
    kd_k: Optional[float] = 0.0
    kd_d: Optional[float] = 0.0
    rsi_14: Optional[float] = 0.0
    macd: Optional[float] = 0.0
    macd_signal: Optional[float] = 0.0
    macd_hist: Optional[float] = 0.0

class DailyReport(BaseModel):
    date: str
    spot_market: SpotMarket = SpotMarket()
    futures_options: FuturesOptions = FuturesOptions()
    macro_cross_market: MacroCrossMarket = MacroCrossMarket()
    technical_indicators: TechnicalIndicators = TechnicalIndicators()

def format_report(date_str: str, spot_data: dict, chips_data: dict, macro_data: dict, tech_data: dict) -> str:
    report = DailyReport(
        date=date_str,
        spot_market=SpotMarket(**spot_data) if spot_data else SpotMarket(),
        futures_options=FuturesOptions(**chips_data) if chips_data else FuturesOptions(),
        macro_cross_market=MacroCrossMarket(**macro_data) if macro_data else MacroCrossMarket(),
        technical_indicators=TechnicalIndicators(**tech_data) if tech_data else TechnicalIndicators()
    )
    return report.model_dump_json(indent=2)
