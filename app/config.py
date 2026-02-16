import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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


def get_settings() -> Settings:
    return Settings()
