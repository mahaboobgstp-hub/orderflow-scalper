import math
import pytest

from app.services.nine_layer_decision_engine import NineLayerDecisionEngine
from app.services.risk_management import RiskManagementEngine


def l9(risk):
    result = NineLayerDecisionEngine().evaluate("BTCUSDT", {}, risk=risk)
    return result, result["layers"]["risk_execution"]


@pytest.mark.parametrize("risk", [
    {"allowed": True, "blockers": []},
    {"allowed": True},
    {"allowed": True, "blockers": ()},
])
def test_l9_pass_requires_explicit_permission_and_no_blockers(risk):
    result, layer = l9(risk)
    assert layer["available"] is True
    assert layer["direction"] == "NEUTRAL"
    assert layer["score"] == 100
    assert result["decision"] == "REJECT"  # L6 fail-closed gate; no directional evidence


@pytest.mark.parametrize("risk", [
    None, {}, {"allowed": False}, {"allowed": False, "blockers": []},
    {"allowed": False, "blockers": ["DAILY_LOSS_LIMIT_REACHED"]},
    {"allowed": True, "blockers": ["DUPLICATE_SYMBOL_POSITION"]},
    {"allowed": True, "blockers": ["BOOK_SYNC_REQUIRED", "MAX_OPEN_POSITIONS_REACHED"]},
    {"allowed": 1, "blockers": []}, {"allowed": "true", "blockers": []},
    {"allowed": "false", "blockers": []}, {"allowed": None, "blockers": []},
    {"allowed": True, "blockers": "unexpected string"},
    {"allowed": True, "blockers": 12},
    {"allowed": True, "blockers": {"x": "y"}},
])
def test_l9_blocks_missing_denied_or_malformed_risk_permission(risk):
    result, layer = l9(risk)
    assert layer["available"] is True
    assert layer["direction"] == "BLOCK"
    assert layer["score"] == -100
    assert result["decision"] == "REJECT"
    assert result["entry_eligible"] is False
    assert result["side"] == "NEUTRAL"
    assert result["mode"] == "PAPER_ONLY"
    assert result["live_execution_enabled"] is False


@pytest.mark.parametrize("blocker", [
    "DAILY_LOSS_LIMIT_REACHED", "OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED",
    "MAX_OPEN_POSITIONS_REACHED", "CONSECUTIVE_LOSS_LIMIT_REACHED",
    "DUPLICATE_SYMBOL_POSITION", "SYNCHRONIZED_BOOK_UNAVAILABLE",
    "SESSION_LOSS_LIMIT_REACHED", "SESSION_TRADE_LIMIT_REACHED",
    "SESSION_TIME_LIMIT", "BOOK_SYNC_REQUIRED", "LONG_DISABLED_FOR_SESSION",
    "SHORT_DISABLED_FOR_SESSION",
])
def test_l9_each_known_blocker_rejects(blocker):
    result, layer = l9({"allowed": True, "blockers": [blocker]})
    assert layer["direction"] == "BLOCK"
    assert result["decision"] == "REJECT"
    assert result["entry_eligible"] is False


@pytest.mark.parametrize("risk", [
    {"allowed": True, "blockers": [" " ]},
    {"allowed": True, "blockers": [None]},
    {"allowed": True, "blockers": [False]},
])
def test_l9_does_not_ignore_present_blocker_entries(risk):
    result, layer = l9(risk)
    assert layer["direction"] == "BLOCK"
    assert result["decision"] == "REJECT"


def test_l9_risk_gate_never_becomes_directional_signal():
    for risk in ({"allowed": True, "blockers": []}, {"allowed": False, "blockers": ["risk"]}):
        _, layer = l9(risk)
        assert layer["direction"] == ("NEUTRAL" if risk["allowed"] is True else "BLOCK")


def test_l9_layer_weight_is_bounded_and_configurable():
    result = NineLayerDecisionEngine({"layer_weights": {"risk_execution": 0, "bogus": 900}}).evaluate(
        "ETHUSDT", {}, risk={"allowed": True, "blockers": []}
    )
    assert result["weights"]["risk_execution"] == 0
    assert "bogus" not in result["weights"]


def test_risk_engine_rejects_invalid_position_sizing_inputs():
    engine = RiskManagementEngine()
    base = {"account_equity": 1000, "entry_price": 10, "stop_loss_price": 9, "side": "long"}
    for bad in (None, "nan", "inf", 0, -5):
        with pytest.raises(ValueError):
            engine.calculate({**base, "account_equity": bad})
    for bad in (None, "nan", "inf", 0, -1):
        with pytest.raises(ValueError):
            engine.calculate({**base, "entry_price": bad})


@pytest.mark.parametrize("kwargs,blocker", [
    ({"daily_realized_loss": 200}, "DAILY_LOSS_LIMIT_REACHED"),
    ({"open_risk": 300}, "OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED"),
    ({"open_positions": 3}, "MAX_OPEN_POSITIONS_REACHED"),
    ({"consecutive_losses": 3}, "CONSECUTIVE_LOSS_LIMIT_REACHED"),
])
def test_portfolio_guard_blocks_each_risk_limit(kwargs, blocker):
    result = RiskManagementEngine().evaluate_portfolio(10000, **kwargs)
    assert result["allowed_to_consider_new_trade"] is False
    assert blocker in result["blockers"]


def test_portfolio_guard_passes_within_limits():
    result = RiskManagementEngine().evaluate_portfolio(10000, daily_realized_loss=25, open_risk=25,
        open_positions=1, consecutive_losses=1)
    assert result["allowed_to_consider_new_trade"] is True
    assert result["blockers"] == []


@pytest.mark.parametrize("equity", [0, -1, None, float("nan"), float("inf")])
def test_portfolio_guard_rejects_invalid_equity(equity):
    with pytest.raises(ValueError):
        RiskManagementEngine().evaluate_portfolio(equity)


@pytest.mark.parametrize("risk_value", [-100, -1, float("nan"), float("inf")])
def test_portfolio_guard_sanitizes_negative_or_nonfinite_inputs(risk_value):
    result = RiskManagementEngine().evaluate_portfolio(10000, daily_realized_loss=risk_value, open_risk=risk_value)
    assert result["daily_realized_loss"] >= 0
    assert result["open_risk"] >= 0
    assert isinstance(result["allowed_to_consider_new_trade"], bool)
