from app.services.opportunity_ranker import OpportunityRanker


def row(symbol, volume, spread, range_pct, trades, momentum, accel=1.0):
    return {
        "symbol": symbol,
        "quote_volume_24h": volume,
        "spread_pct": spread,
        "range_24h_pct": range_pct,
        "trade_count_24h": trades,
        "price_change_24h_pct": momentum,
        "volume_acceleration_ratio_5m": accel,
    }


def test_ranker_sorts_high_quality_rows_and_exposes_components():
    result = OpportunityRanker().rank([
        row("LOW", 1_000_000, 0.3, 0.2, 500, -5, None),
        row("HIGH", 30_000_000, 0.02, 10, 25_000, 8, 2.5),
    ])
    assert result["mode"] == "READ_ONLY_PUBLIC_MARKET_DATA"
    assert result["trade_signal"] is False
    assert result["execution_enabled"] is False
    assert result["markets"][0]["symbol"] == "HIGH"
    components = result["markets"][0]["phase_c_score_components"]
    assert set(components) == {
        "volume", "spread", "range", "trade_activity", "momentum_proxy", "activity_acceleration"
    }
    assert result["markets"][0]["phase_c_rank"] == 1


def test_quality_flags_and_filtered_status_are_reported():
    result = OpportunityRanker().rank([
        row("BAD", 100, 0.5, 0, 0, -50, None),
    ])
    market = result["markets"][0]
    assert "LOW_VOLUME" in market["phase_c_quality_flags"]
    assert "WIDE_SPREAD" in market["phase_c_quality_flags"]
    assert "RANGE_UNAVAILABLE" in market["phase_c_quality_flags"]
    assert market["phase_c_review_status"] == "FILTERED"
    assert "ACTIVITY_ACCELERATION_UNAVAILABLE" in market["phase_c_quality_flags"]


def test_invalid_numeric_inputs_are_safely_defaulted():
    result = OpportunityRanker().rank([{
        "symbol": "SAFE",
        "quote_volume_24h": "NaN",
        "spread_pct": "inf",
        "range_24h_pct": None,
        "trade_count_24h": "bad",
        "price_change_24h_pct": None,
        "volume_acceleration_ratio_5m": "NaN",
    }])
    market = result["markets"][0]
    assert market["phase_c_score"] >= 0
    assert market["phase_c_review_status"] == "FILTERED"
    assert market["phase_c_quality_flags"]
