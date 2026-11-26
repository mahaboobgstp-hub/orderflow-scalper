import pytest
from app.services.trade_management import TradeManagementEngine, TradeManagementConfig


def test_long_stop_moves_up_and_break_even_protection_activates():
    engine = TradeManagementEngine()
    result = engine.evaluate({"symbol":"BTCUSDT","side":"long","entry_price":100,"best_price":101},
                             {"mark_price":101,"trend_score":70})
    assert result.break_even_active is True
    assert result.stop_price > result.initial_stop_price
    assert result.trend_extension is True


def test_short_stop_trails_down_and_is_directionally_correct():
    engine = TradeManagementEngine()
    result = engine.evaluate({"symbol":"ETHUSDT","side":"short","entry_price":100,"best_price":98},
                             {"mark_price":98,"trend_score":70})
    assert result.break_even_active is True
    assert result.stop_price < result.initial_stop_price
    assert result.stop_price > 98


def test_long_stop_exit_when_mark_hits_protection():
    engine = TradeManagementEngine()
    result = engine.evaluate({"symbol":"X","side":"long","entry_price":100,"best_price":100},
                             {"mark_price":98.9,"trend_score":50})
    assert result.exit_action == "EXIT"
    assert result.exit_reason == "PROTECTIVE_STOP"


def test_trailing_take_profit_exit_after_activation_and_reversal():
    engine = TradeManagementEngine()
    position = {"symbol":"X","side":"long","entry_price":100,"best_price":102}
    result = engine.evaluate(position,{"mark_price":101.4,"trend_score":60})
    assert result.trailing_take_profit_active
    assert result.exit_reason == "TRAILING_TAKE_PROFIT"


def test_trend_weakening_exit_only_when_move_is_not_favorable():
    engine = TradeManagementEngine(TradeManagementConfig(weak_trend_exit_score=20))
    result = engine.evaluate({"symbol":"X","side":"long","entry_price":100,"best_price":100},
                             {"mark_price":99.5,"trend_score":10})
    assert result.exit_action == "EXIT"
    assert result.exit_reason == "TREND_WEAKENING"


def test_max_hold_time_exit_suppressed_during_trend_extension():
    config = TradeManagementConfig(max_hold_seconds=60)
    engine = TradeManagementEngine(config)
    pos = {"symbol":"X","side":"long","entry_price":100,"best_price":100,"opened_at_seconds":0}
    held = engine.evaluate(pos,{"mark_price":101,"trend_score":80},now_seconds=120)
    flat = engine.evaluate(pos,{"mark_price":99.5,"trend_score":50},now_seconds=120)
    assert held.exit_reason is None
    assert flat.exit_reason == "MAX_HOLD_TIME"


@pytest.mark.parametrize("side",["long","short"])
def test_invalid_prices_rejected(side):
    engine = TradeManagementEngine()
    with pytest.raises(ValueError):
        engine.evaluate({"symbol":"X","side":side,"entry_price":0},
                         {"mark_price":10,"trend_score":50})


def test_config_rejects_bad_trailing_parameters():
    with pytest.raises(ValueError):
        TradeManagementEngine(TradeManagementConfig(trailing_stop_pct=0))


def test_best_price_extreme_is_returned_for_state_persistence():
    engine = TradeManagementEngine()
    long_result = engine.evaluate({"symbol":"L","side":"long","entry_price":100,"best_price":100},
                                 {"mark_price":102,"trend_score":80})
    short_result = engine.evaluate({"symbol":"S","side":"short","entry_price":100,"best_price":100},
                                  {"mark_price":98,"trend_score":80})
    assert long_result.best_price == 102
    assert short_result.best_price == 98


def test_trailing_stop_does_not_tighten_before_favorable_move():
    engine = TradeManagementEngine()
    result = engine.evaluate({"symbol":"L","side":"long","entry_price":100,"best_price":100},
                             {"mark_price":100,"trend_score":50})
    assert result.stop_price == result.initial_stop_price
    assert result.trailing_stop_active is False


def test_favorable_mark_updates_extreme_and_activates_on_same_evaluation():
    engine = TradeManagementEngine()
    result = engine.evaluate({"symbol":"L","side":"long","entry_price":100,"best_price":100},
                             {"mark_price":102,"trend_score":70})
    assert result.best_price == 102
    assert result.break_even_active
    assert result.trailing_take_profit_active
