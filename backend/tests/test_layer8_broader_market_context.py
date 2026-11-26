import math
import pytest

from app.services.nine_layer_decision_engine import NineLayerDecisionEngine


def evaluate_context(context, config=None):
    return NineLayerDecisionEngine(config).evaluate(
        "BTCUSDT",
        {"broader_context": context},
        risk={"allowed": True, "blockers": []},
    )["layers"]["broader_market_context"]


@pytest.mark.parametrize(("score", "direction"), [
    (15, "BUY"), (100, "BUY"), (14.99, "NEUTRAL"),
    (0, "NEUTRAL"), (-14.99, "NEUTRAL"), (-15, "SELL"), (-100, "SELL"),
])
def test_l8_score_direction_threshold_and_clamping(score, direction):
    layer = evaluate_context({"score": score, "confidence": 75, "reasons": ["BTC trend"]})
    expected_score = max(-100, min(100, score))
    assert layer["available"] is True
    assert layer["score"] == expected_score
    assert layer["direction"] == direction


@pytest.mark.parametrize("score", [None, "invalid", float("nan"), float("inf"), float("-inf")])
def test_l8_missing_or_nonfinite_score_is_unavailable(score):
    layer = evaluate_context({"score": score, "confidence": 80, "reasons": ["test"]})
    assert layer["available"] is False
    assert layer["score"] is None
    assert layer["direction"] == "NEUTRAL"


@pytest.mark.parametrize("context", [None, {}, [], "bad-shape", {"confidence": 99}, {"score": "NaN"}])
def test_l8_missing_or_malformed_context_is_unavailable(context):
    layer = evaluate_context(context)
    assert layer["available"] is False
    assert layer["score"] is None


@pytest.mark.parametrize("confidence", [-20, 0, 45.55, 100, 150, "bad", float("nan")])
def test_l8_confidence_is_safely_bounded(confidence):
    layer = evaluate_context({"score": 20, "confidence": confidence, "reasons": ["ok"]})
    assert 0 <= layer["confidence"] <= 100
    assert math.isfinite(layer["confidence"])


def test_l8_reasons_and_data_are_preserved_for_a_valid_context():
    context = {"score": -65, "confidence": 92, "reasons": ["BTC weakness", "ETH underperforming"],
               "data": {"btc_change_pct": -2.1, "eth_change_pct": -3.2}}
    layer = evaluate_context(context)
    assert layer["reasons"] == context["reasons"]
    assert layer["data"]["btc_change_pct"] == -2.1
    assert layer["data"]["eth_change_pct"] == -3.2


def test_l8_score_is_clamped_at_upper_bound():
    layer = evaluate_context({"score": 9999, "confidence": 101, "reasons": ["extreme"]})
    assert layer["score"] == 100
    assert layer["confidence"] == 100


def test_l8_score_is_clamped_at_lower_bound():
    layer = evaluate_context({"score": -9999, "confidence": -10, "reasons": ["extreme"]})
    assert layer["score"] == -100
    assert layer["confidence"] == 0


def test_l8_does_not_claim_available_when_score_is_missing():
    layer = evaluate_context({"confidence": 100, "reasons": ["context without score"]})
    assert layer["available"] is False


def test_l8_context_only_is_not_enough_to_force_trade_decision():
    result = NineLayerDecisionEngine().evaluate(
        "BTCUSDT",
        {"broader_context": {"score": 90, "confidence": 95, "reasons": ["broad market bullish"]}},
        risk={"allowed": True, "blockers": []},
    )
    layer = result["layers"]["broader_market_context"]
    assert layer["available"] is True
    assert result["decision"] == "HOLD"
    assert result["entry_eligible"] is False
    assert result["mode"] == "PAPER_ONLY"
    assert result["live_execution_enabled"] is False


@pytest.mark.parametrize("context", [
    {"score": 90, "confidence": 90, "reasons": ["bullish"]},
    {"score": -90, "confidence": 90, "reasons": ["bearish"]},
])
def test_l8_broader_context_is_independent_of_symbol_without_other_layers(context):
    result = NineLayerDecisionEngine().evaluate(
        "ALTUSDT", {"broader_context": context}, risk={"allowed": True, "blockers": []}
    )
    assert result["layers"]["broader_market_context"]["score"] == context["score"]
    assert result["directional_layers_available"] == 1
    assert result["decision"] == "HOLD"
