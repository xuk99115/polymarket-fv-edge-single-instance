"""方向过滤器单元测试。"""

import os
import sys
import time
from datetime import datetime, timezone

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from trading.direction_filter import DirectionFilter, DirectionState


def _make_ticks(now_ts, prices_and_offsets):
    """创建 ticks 历史数据。
    
    注意：每个 tick 的偏移 = 目标偏移 + 额外偏移。
    最新 tick 用 +1 秒，60m tick 用 +11 秒，15m tick 用 +11 秒。
    这样可以确保 cutoff = latest_ts - N 严格大于 tick.ts。
    """
    ticks = []
    for i, (price, offset) in enumerate(prices_and_offsets):
        # 最新 tick 用 +1，其他用 +11
        extra = 1 if i == len(prices_and_offsets) - 1 else 11
        ticks.append({"ts": now_ts - offset - extra, "price": price})
    ticks.sort(key=lambda x: x["ts"])
    return ticks


# ── 方向计算测试 ───────────────────────────────────────────

def test_up_trend():
    """上涨趋势应返回 UP。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (100.5, 900),
        (101.0, 0),
    ])
    
    f = DirectionFilter(mode="shadow")
    f.set_history(ticks)
    result = f.calculate()
    
    assert result.direction == DirectionState.UP, f"Expected UP, got {result.direction} (60m={result.pct_60m}%, 15m={result.pct_15m}%)"
    assert result.pct_60m > 0
    assert result.pct_15m > 0


def test_down_trend():
    """下跌趋势应返回 DOWN。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (99.5, 900),
        (99.0, 0),
    ])
    
    f = DirectionFilter(mode="shadow")
    f.set_history(ticks)
    result = f.calculate()
    
    assert result.direction == DirectionState.DOWN, f"Expected DOWN, got {result.direction}"
    assert result.pct_60m < 0
    assert result.pct_15m < 0


def test_neutral_60m_below_threshold():
    """60m 涨幅 < 30bps → NEUTRAL。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (100.5, 900),
        (100.015, 0),
    ])
    
    f = DirectionFilter(mode="shadow")
    f.set_history(ticks)
    result = f.calculate()
    
    assert result.direction == DirectionState.NEUTRAL


def test_neutral_15m_below_threshold():
    """60m 涨幅 OK 但 15m < 10bps → NEUTRAL。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (100.9, 900),
        (100.93, 0),
    ])
    
    f = DirectionFilter(mode="shadow")
    f.set_history(ticks)
    result = f.calculate()
    
    assert result.direction == DirectionState.NEUTRAL


def test_unknown_no_data():
    """无数据应返回 UNKNOWN。"""
    f = DirectionFilter(mode="shadow")
    f.set_history([])
    result = f.calculate()
    
    assert result.direction == DirectionState.UNKNOWN


def test_unknown_stale_data():
    """数据超过 900 秒应返回 UNKNOWN。"""
    now = time.time()
    ticks = [{"ts": now - 2000, "price": 100.0}]
    
    f = DirectionFilter(mode="shadow")
    f.set_history(ticks)
    result = f.calculate()
    
    assert result.direction == DirectionState.UNKNOWN


def test_up_strict_same_direction():
    """60m 涨、15m 跌 → NEUTRAL。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (100.9, 900),
        (100.85, 0),
    ])
    
    f = DirectionFilter(mode="shadow")
    f.set_history(ticks)
    result = f.calculate()
    
    assert result.direction == DirectionState.NEUTRAL


# ── 状态机测试 ─────────────────────────────────────────────

def test_confirm_twice():
    """连续两次确认才生效。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (100.5, 900),
        (101.0, 0),
    ])
    
    f = DirectionFilter(mode="shadow", update_seconds=1)
    f.set_history(ticks)
    
    r1 = f.calculate(now=now)
    assert r1.direction == DirectionState.UP
    
    r2 = f.calculate(now=now + 1)
    assert r2.direction == DirectionState.UP


def test_shadow_does_not_block():
    """Shadow 模式不应阻止任何交易。"""
    f = DirectionFilter(mode="shadow")
    signal = {"outcome_label": "Up", "slug": "test"}
    
    assert f.should_allow_trade(signal) is True


def test_neutral_allows_both():
    """NEUTRAL 方向允许双向交易。"""
    now = time.time()
    ticks = _make_ticks(now, [
        (100.0, 3600),
        (100.9, 900),
        (100.85, 0),
    ])
    
    f = DirectionFilter(mode="enforce")
    f.set_history(ticks)
    
    up_signal = {"outcome_label": "Up", "slug": "test"}
    down_signal = {"outcome_label": "Down", "slug": "test"}
    
    f.calculate(now=now)
    
    assert f.should_allow_trade(up_signal) is True
    assert f.should_allow_trade(down_signal) is True


def test_integration_methods_exist():
    """验证 DirectionFilter 有所有必要的方法。"""
    f = DirectionFilter(mode="shadow")
    assert hasattr(f, 'should_allow_trade')
    assert hasattr(f, 'calculate')
    assert hasattr(f, 'set_history')
    assert hasattr(f, 'record_shadow_candidate')
    assert hasattr(f, 'get_stats')


if __name__ == "__main__":
    tests = [
        test_up_trend, test_down_trend,
        test_neutral_60m_below_threshold, test_neutral_15m_below_threshold,
        test_unknown_no_data, test_unknown_stale_data, test_up_strict_same_direction,
        test_confirm_twice,
        test_shadow_does_not_block, test_neutral_allows_both,
        test_integration_methods_exist,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    sys.exit(0 if failed == 0 else 1)
