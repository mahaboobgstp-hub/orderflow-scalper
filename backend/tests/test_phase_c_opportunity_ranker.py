from app.services.opportunity_ranker import OpportunityRanker


def test_ranker_assigns_rank_and_explainable_components():
    ranker = OpportunityRanker()
    rows = [
        {"symbol": "LOWVOLUSDT", "quote_volume_24h": 1_000_000, "spread_pct": 0.2,
         "range_24h_pct": 5, "trade_count_24h": 2000, "price_change_24h_pct": 2,
         "volume_acceleration_ratio_5m": 1.2},
        {"symbol": "STRONGUSDT", "quote_volume_24h": 12_000_000, "spread_pct": 0.04,
         "range_24h_pct": 8, "trade_count_24h": 18000, "price_change_24h_pct": 4,
         "volume_acceleration_ratio_5m": 1.5},
    ]
    result = ranker.rank(rows)
    assert result["ranked_count"] == 2
    assert result["markets"][0]["symbol"] == "STRONGUSDT"
    assert result["markets"][0]["phase_c_rank"] == 1
    assert "phase_c_score_components" in result["markets"][0]
    assert result["markets"][0]["phase_c_review_status"] == "REVIEW_CANDIDATE"
    assert result["markets"][1]["phase_c_review_status"] == "FILTERED"


def test_ranker_handles_missing_and_nonfinite_values():
    ranker = OpportunityRanker()
    result = ranker.rank([
        {"symbol": "SAFEUSDT", "quote_volume_24h": "nan", "spread_pct": "inf",
         "range_24h_pct": 0, "trade_count_24h": None,
         "price_change_24h_pct": "bad", "volume_acceleration_ratio_5m": None},
        {},
        None,
    ])
    assert result["ranked_count"] == 1
    row = result["markets"][0]
    assert row["phase_c_rank"] == 1
    assert "ACTIVITY_ACCELERATION_UNAVAILABLE" in row["phase_c_quality_flags"]
    assert result["execution_enabled"] is False
    assert result["trade_signal"] is False
