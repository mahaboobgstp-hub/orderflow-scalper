"""TradeBridge safety-first configuration. Live execution is disabled by default."""
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class TradeBridgeConfig:
    enabled: bool = os.getenv("TRADEBRIDGE_ENABLED", "false").lower() == "true"
    live_execution_enabled: bool = os.getenv("TRADEBRIDGE_LIVE_EXECUTION", "false").lower() == "true"
    testnet: bool = os.getenv("TRADEBRIDGE_TESTNET", "true").lower() == "true"
    signal_ttl_seconds: int = int(os.getenv("TRADEBRIDGE_SIGNAL_TTL_SECONDS", "90"))
    max_open_positions: int = int(os.getenv("TRADEBRIDGE_MAX_OPEN_POSITIONS", "1"))

    def validate(self) -> None:
        if self.signal_ttl_seconds <= 0:
            raise ValueError("TradeBridge signal TTL must be positive")
        if self.max_open_positions < 1:
            raise ValueError("TradeBridge max open positions must be at least 1")
        if self.live_execution_enabled and self.testnet:
            raise ValueError("Conflicting TradeBridge configuration: live execution enabled while testnet mode is selected")
