from src.api.chainlink_rtds import parse_latest_tick


def test_snapshot_topic_mismatch_is_accepted_by_symbol_and_shape():
    message = {
        "topic": "crypto_prices",
        "type": "subscribe",
        "payload": {
            "symbol": "btc/usd",
            "data": [
                {"timestamp": 1_000, "value": 100.0},
                {"timestamp": 2_000, "value": 101.0},
            ],
        },
    }
    tick = parse_latest_tick(message, now_ms=2_000)
    assert tick["price"] == 101.0
    assert tick["measurement_ts_ms"] == 2_000


def test_single_update_shape_is_supported():
    tick = parse_latest_tick(
        {"payload": {"symbol": "btc/usd", "timestamp": 2_000, "value": 101.0}},
        now_ms=2_000,
    )
    assert tick["price"] == 101.0


def test_future_tick_is_rejected():
    assert parse_latest_tick(
        {"payload": {"symbol": "btc/usd", "timestamp": 10_000, "value": 101.0}},
        now_ms=1_000,
    ) is None
