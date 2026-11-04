import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    binance_api_key: str = os.getenv("BINANCE_DEMO_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_DEMO_API_SECRET", "")
    binance_base_url: str = os.getenv(
        "BINANCE_DEMO_BASE_URL",
        "https://demo-fapi.binance.com",
    )
    execution_enabled: bool = _as_bool(
        os.getenv("DEMO_EXECUTION_ENABLED"),
        False,
    )
    max_order_quantity: float = float(
        os.getenv("MAX_DEMO_ORDER_QUANTITY", "0.001")
    )


settings = Settings()
