import asyncio
import pytest
from fastapi import HTTPException
from unittest.mock import patch

from app.services.risk_management import RiskManagementEngine
from app.main import app, PaperOrderRequest, paper_submit_order, operator_control_state


def valid_book():
    return {
        "synchronized": True,
        "stale": False,
        "integrity_error": None,
        "age_seconds": 0.25,
        "best_bid": 59999.9,
        "best_ask": 60000.1,
    }


def test_synchronized_fresh_book_validator_enforces_safety_boundaries():
    engine = RiskManagementEngine()
    book = valid_book()
    assert engine.is_synchronized_fresh_book(book, 3.0)
    assert engine.is_synchronized_fresh_book({**book, "age_seconds": 3.0}, 3.0)
    invalid_books = [
        None,
        {**book, "synchronized": False},
        {**book, "stale": True},
        {**book, "integrity_error": "gap"},
        {**book, "age_seconds": None},
        {**book, "age_seconds": -0.01},
        {**book, "age_seconds": 3.001},
        {**book, "age_seconds": float("nan")},
        {**book, "age_seconds": float("inf")},
        {**book, "age_seconds": True},
        {**book, "best_bid": 60000.1},
        {**book, "best_bid": 60000.2},
        {**book, "best_bid": float("inf")},
        {**book, "best_ask": float("nan")},
    ]
    for invalid in invalid_books:
        assert not engine.is_synchronized_fresh_book(invalid, 3.0)
    assert not engine.is_synchronized_fresh_book(book, float("nan"))
    assert not engine.is_synchronized_fresh_book(book, True)


class FakeMarketData:
    stale_after_seconds = 3.0

    def __init__(self, book):
        self.book = book

    def get_book(self, exchange, symbol):
        assert exchange == "binance"
        assert symbol == "BTCUSDT"
        return self.book


class FakePaperEngine:
    fee_rate = 0.0

    def __init__(self):
        self.orders = []
        self.closed_trades = []
        self.positions = {}
        self.submitted = []

    def account(self):
        return {"equity": 10000.0, "initial_equity": 10000.0}

    def submit(self, request):
        self.submitted.append(request)
        return {"paper_submission": "accepted"}


def test_manual_paper_order_uses_real_book_synchronization_state():
    risk = RiskManagementEngine()
    paper = FakePaperEngine()
    market = FakeMarketData(None)
    request = PaperOrderRequest(
        symbol="BTCUSDT",
        side="long",
        quantity=0.001,
        price=60000.0,
        leverage=1.0,
        stop_loss_price=59000.0,
    )

    with patch.object(app.state, "risk_management_engine", risk, create=True), \
         patch.object(app.state, "paper_trading_engine", paper, create=True), \
         patch.object(app.state, "unified_market_data", market, create=True), \
         patch.dict(operator_control_state, {"config": {}}, clear=False):
        with pytest.raises(HTTPException) as missing_book:
            asyncio.run(paper_submit_order(request))
        assert missing_book.value.status_code == 409
        assert "SYNCHRONIZED_BOOK_UNAVAILABLE" in missing_book.value.detail["blockers"]
        assert paper.submitted == []

        market.book = valid_book()
        accepted = asyncio.run(paper_submit_order(request))
        assert accepted == {"paper_submission": "accepted"}
        assert len(paper.submitted) == 1
