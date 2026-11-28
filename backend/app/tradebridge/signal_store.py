"""Small in-memory signal registry. Persistence will be added before production use."""
from threading import RLock
from .models import OpportunitySignal


class SignalStore:
    def __init__(self) -> None:
        self._signals: dict[str, OpportunitySignal] = {}
        self._lock = RLock()

    def register(self, signal: OpportunitySignal) -> OpportunitySignal:
        with self._lock:
            self._signals[signal.signal_id] = signal
            return signal

    def get(self, signal_id: str) -> OpportunitySignal | None:
        with self._lock:
            return self._signals.get(signal_id)

    def latest(self) -> OpportunitySignal | None:
        with self._lock:
            return next(reversed(self._signals.values()), None) if self._signals else None

    def clear(self) -> None:
        with self._lock:
            self._signals.clear()
