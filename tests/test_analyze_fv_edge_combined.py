from scripts.analyze_fv_edge_combined import edge_trade, pick_per_slug


def row(**overrides):
    value = {
        "slug": "btc-updown-15m-1",
        "minutes_to_end": 1.4,
        "fair_up": 0.2,
        "market_up_ask": 0.25,
        "market_down_ask": 0.1,
        "resolved_up": 0,
    }
    value.update(overrides)
    return value


def test_down_uses_real_down_ask_and_fixed_stake_pnl():
    trade = edge_trade(row(), 500, stake=2.0)
    assert trade["outcome_label"] == "Down"
    assert trade["buy_price"] == 0.1
    assert trade["pnl"] == 18.0


def test_missing_down_ask_cannot_create_synthetic_trade():
    assert edge_trade(row(market_down_ask=None), 0) is None


def test_first_eligible_has_no_out_of_window_fallback():
    rows = [
        row(minutes_to_end=2.2),
        row(minutes_to_end=1.4),
        row(minutes_to_end=-0.1),
    ]
    picked = pick_per_slug(rows, target_mte=1.5, edge_thr=500, variant="v1")
    assert len(picked) == 1
    assert picked[0]["minutes_to_end"] == 1.4


def test_each_slug_is_picked_once_at_first_eligible_row():
    rows = [
        row(minutes_to_end=1.4, market_down_ask=0.1),
        row(minutes_to_end=1.2, market_down_ask=0.05),
        row(slug="btc-updown-15m-2", minutes_to_end=1.3, market_down_ask=0.1),
    ]
    picked = pick_per_slug(rows, target_mte=1.5, edge_thr=500, variant="v1")
    assert [item["slug"] for item in picked] == ["btc-updown-15m-1", "btc-updown-15m-2"]
