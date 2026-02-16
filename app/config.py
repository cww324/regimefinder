import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

def _opt_float(value: str) -> Optional[float]:
    if value == "":
        return None
    return float(value)


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("DB_PATH", "data/market.sqlite")
    product_id: str = os.getenv("COINBASE_PRODUCT_ID", "BTC-USD")
    candles_url: str = os.getenv("COINBASE_CANDLES_URL", "")
    granularity_sec: int = int(os.getenv("CANDLE_GRANULARITY_SEC", "300"))
    safety_lag_sec: int = int(os.getenv("CANDLE_SAFETY_LAG_SEC", "15"))

    # Coinbase Advanced Trade (CDP)
    api_key: str = os.getenv("COINBASE_KEY_NAME", "")
    api_secret: str = os.getenv("COINBASE_PRIVATE_KEY", "")

    # Coinbase Exchange (classic) - unused for now
    api_passphrase: str = os.getenv("COINBASE_API_PASSPHRASE", "")

    # Paper fill costs (bps)
    half_spread_bps: float = float(os.getenv("HALF_SPREAD_BPS", "5"))
    slippage_bps: float = float(os.getenv("SLIPPAGE_BPS", "5"))

    # Strategy controls
    allow_shorts: bool = os.getenv("ALLOW_SHORTS", "false").lower() == "true"
    cooldown_bars: int = int(os.getenv("COOLDOWN_BARS", "1"))
    breakout_atr_buffer: float = float(os.getenv("BREAKOUT_ATR_BUFFER", "0.2"))
    breakout_requires_close: bool = os.getenv("BREAKOUT_REQUIRES_CLOSE", "false").lower() == "true"
    entry_er_min: float = float(os.getenv("ENTRY_ER_MIN", "0.35"))
    er_no_trade_band_low: Optional[float] = _opt_float(os.getenv("ER_NO_TRADE_BAND_LOW", ""))
    er_no_trade_band_high: Optional[float] = _opt_float(os.getenv("ER_NO_TRADE_BAND_HIGH", ""))
    skip_top_decile_rv: bool = os.getenv("SKIP_TOP_DECILE_RV", "false").lower() == "true"
    rv_quantile_window: int = int(os.getenv("RV_QUANTILE_WINDOW", "2000"))
    freeze_atr_at_entry: bool = os.getenv("FREEZE_ATR_AT_ENTRY", "false").lower() == "true"

    # Entry confirmations
    enable_retest: bool = os.getenv("ENABLE_RETEST", "false").lower() == "true"
    retest_atr_band: float = float(os.getenv("RETEST_ATR_BAND", "0.2"))
    retest_max_bars: int = int(os.getenv("RETEST_MAX_BARS", "6"))
    require_ema_confirm: bool = os.getenv("REQUIRE_EMA_CONFIRM", "false").lower() == "true"
    ema_fast_period: int = int(os.getenv("EMA_FAST_PERIOD", "20"))
    ema_slow_period: int = int(os.getenv("EMA_SLOW_PERIOD", "50"))
    ema_slope_bars: int = int(os.getenv("EMA_SLOPE_BARS", "3"))
    ema_slope_min: float = float(os.getenv("EMA_SLOPE_MIN", "0.0"))

    # Risk sizing (for audit / future sizing)
    initial_equity: float = float(os.getenv("INITIAL_EQUITY", "10000"))
    risk_pct: float = float(os.getenv("RISK_PCT", "0.005"))


def get_settings() -> Settings:
    return Settings()
