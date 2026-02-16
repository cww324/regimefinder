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


def get_settings() -> Settings:
    return Settings()
