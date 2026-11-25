import pytest

from app.market_data.backend_stream import BinanceOrderBookStream


def stream_with_snapshot(update_id=100):
    stream = BinanceOrderBookStream(symbol="BTCUSDT")
    stream._load_snapshot(
        {
            "lastUpdateId": update_id,
            "bids": [["100.0", "1.0"]],
            "asks": [["101.0", "1.0"]],
        }
    )
    return stream


def depth_event(U, u, pu=None, bids=None, asks=None):
    event = {
        "U": U,
        "u": u,
        "b": bids or [],
        "a": asks or [],
    }
    if pu is not None:
        event["pu"] = pu
    return event


def test_snapshot_bridge_requires_covering_next_update_id():
    stream = stream_with_snapshot(100)

    assert stream._event_bridges_snapshot(depth_event(100, 101))
    assert stream._event_bridges_snapshot(depth_event(101, 101))
    assert stream._event_bridges_snapshot(depth_event(99, 102))

    # An event ending at the snapshot ID is already covered and cannot bridge.
    assert not stream._event_bridges_snapshot(depth_event(99, 100))
    assert not stream._event_bridges_snapshot(depth_event(100, 100))

    # A later event that starts after the next required update is a gap.
    assert not stream._event_bridges_snapshot(depth_event(102, 103))


def test_snapshot_bridge_rejects_malformed_or_reversed_sequences():
    stream = stream_with_snapshot(100)

    assert not stream._event_bridges_snapshot({"u": 101})
    assert not stream._event_bridges_snapshot({"U": "bad", "u": 101})
    assert not stream._event_bridges_snapshot(depth_event(102, 101))
    assert not stream._event_bridges_snapshot(depth_event(101, 100))


def test_initial_bridge_ignores_stream_previous_id_and_applies_event():
    stream = stream_with_snapshot(100)
    event = depth_event(
        100,
        101,
        pu=98,  # Stream predecessor is not the REST snapshot update ID.
        bids=[["100.0", "2.5"]],
        asks=[["101.0", "0"]],
    )

    assert stream._event_bridges_snapshot(event)
    assert stream._apply_event(event, initial_snapshot_bridge=True)
    assert stream.last_update_id == 101
    assert stream.bids[100.0] == 2.5
    assert 101.0 not in stream.asks


@pytest.mark.parametrize(
    "event",
    [
        depth_event(100, 100),
        depth_event(102, 103),
        depth_event(101, 100),
    ],
)
def test_initial_bridge_does_not_apply_nonbridging_events(event):
    stream = stream_with_snapshot(100)
    before_bids = dict(stream.bids)
    before_asks = dict(stream.asks)

    assert not stream._apply_event(event, initial_snapshot_bridge=True)
    assert stream.last_update_id == 100
    assert stream.bids == before_bids
    assert stream.asks == before_asks


def test_subsequent_event_requires_matching_pu():
    stream = stream_with_snapshot(100)
    bridge = depth_event(100, 101, pu=98, bids=[["100", "2"]])
    assert stream._apply_event(bridge, initial_snapshot_bridge=True)

    contiguous = depth_event(102, 103, pu=101, bids=[["100", "3"]])
    assert stream._apply_event(contiguous)
    assert stream.last_update_id == 103
    assert stream.bids[100.0] == 3.0

    gap = depth_event(104, 105, pu=102, bids=[["100", "9"]])
    assert not stream._apply_event(gap)
    assert stream.last_update_id == 103
    assert stream.bids[100.0] == 3.0


def test_subsequent_event_without_pu_uses_update_range_gap_fallback():
    stream = stream_with_snapshot(100)
    bridge = depth_event(101, 101, bids=[["100", "2"]])
    assert stream._apply_event(bridge, initial_snapshot_bridge=True)

    contiguous = depth_event(102, 102, bids=[["100", "3"]])
    assert stream._apply_event(contiguous)
    assert stream.last_update_id == 102

    gap = depth_event(104, 104, bids=[["100", "8"]])
    assert not stream._apply_event(gap)
    assert stream.last_update_id == 102


def test_duplicate_or_old_events_are_ignored_without_mutation():
    stream = stream_with_snapshot(100)
    bridge = depth_event(100, 101, bids=[["100", "2"]])
    assert stream._apply_event(bridge, initial_snapshot_bridge=True)

    duplicate = depth_event(100, 101, bids=[["100", "99"]])
    old = depth_event(90, 99, bids=[["100", "99"]])

    assert stream._apply_event(duplicate)
    assert stream._apply_event(old)
    assert stream.last_update_id == 101
    assert stream.bids[100.0] == 2.0
