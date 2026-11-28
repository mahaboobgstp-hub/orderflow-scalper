"""Fail-closed TradeBridge configuration for Binance Futures Demo only."""
from dataclasses import dataclass
import math
import os
from urllib.parse import urlsplit


_ALLOWED_DEMO_HOST = "demo-fapi.binance.com"


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TradeBridgeConfig:
    enabled: bool = _env_bool("TRADEBRIDGE_ENABLED", False)
    live_execution_enabled: bool = _env_bool("TRADEBRIDGE_LIVE_EXECUTION", False)
    testnet: bool = _env_bool("TRADEBRIDGE_TESTNET", True)
    demo_execution_enabled: bool = _env_bool("DEMO_EXECUTION_ENABLED", False)
    binance_base_url: str = os.getenv("BINANCE_DEMO_BASE_URL", "https://demo-fapi.binance.com")
    signal_ttl_seconds: int = int(os.getenv("TRADEBRIDGE_SIGNAL_TTL_SECONDS", "90"))
    preview_ttl_seconds: int = int(os.getenv("TRADEBRIDGE_PREVIEW_TTL_SECONDS", "60"))
    max_open_positions: int = int(os.getenv("TRADEBRIDGE_MAX_OPEN_POSITIONS", "1"))
    max_order_notional_usdt: float = float(os.getenv("TRADEBRIDGE_MAX_ORDER_NOTIONAL_USDT", "25"))
    max_order_quantity: float = float(os.getenv("TRADEBRIDGE_MAX_ORDER_QUANTITY", "0.001"))
    max_leverage: int = int(os.getenv("TRADEBRIDGE_MAX_LEVERAGE", "3"))

    def validate(self) -> None:
        """Reject any configuration that could route TradeBridge toward live trading."""
        if self.live_execution_enabled:
            raise ValueError("TradeBridge live execution is prohibited; it is Testnet-only.")
        if not self.testnet:
            raise ValueError("TradeBridge requires Testnet mode.")
        parsed = urlsplit(self.binance_base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _ALLOWED_DEMO_HOST
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("TradeBridge Binance endpoint must be the HTTPS Demo Futures host.")
        if not 1 <= self.signal_ttl_seconds <= 300:
            raise ValueError("TradeBridge signal TTL must be between 1 and 300 seconds.")
        if not 1 <= self.preview_ttl_seconds <= 120:
            raise ValueError("TradeBridge preview TTL must be between 1 and 120 seconds.")
        if not 1 <= self.max_open_positions <= 3:
            raise ValueError("TradeBridge max open positions must be between 1 and 3.")
        if not math.isfinite(self.max_order_notional_usdt) or not 0 < self.max_order_notional_usdt <= 100:
            raise ValueError("TradeBridge max order notional must be greater than 0 and at most 100 USDT.")
        if not math.isfinite(self.max_order_quantity) or not 0 < self.max_order_quantity <= 1:
            raise ValueError("TradeBridge max order quantity must be greater than 0 and at most 1.")
        if not 1 <= self.max_leverage <= 3:
            raise ValueError("TradeBridge max leverage must be between 1 and 3.")
        if self.demo_execution_enabled and not self.enabled:
            raise ValueError("Demo execution requires TradeBridge to be explicitly enabled.")

    @property
    def execution_available(self) -> bool:
        if not (self.enabled and self.testnet and self.demo_execution_enabled and not self.live_execution_enabled):
            return False
        try:
            self.validate()
        except (TypeError, ValueError):
            return False
        return True
