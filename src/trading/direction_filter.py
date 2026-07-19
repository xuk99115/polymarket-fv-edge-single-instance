"""BTC 方向过滤器 — 基于 Chainlink BTC 价格计算趋势方向。

功能：
- 计算最近 15 分钟和 60 分钟的 BTC 收益率
- 根据阈值判断方向：UP / DOWN / NEUTRAL / UNKNOWN / TRANSITION
- 支持 shadow（只记录）和 enforce（限制交易）两种模式
- 状态机：连续两次确认才切换方向，反转走 TRANSITION 过渡
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DirectionState(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"
    TRANSITION = "TRANSITION"


@dataclass
class DirectionResult:
    """单次方向计算结果。"""
    direction: DirectionState
    pct_15m: float = 0.0
    pct_60m: float = 0.0
    data_points_15m: int = 0
    data_points_60m: int = 0
    stale_seconds: float = 0.0
    confirmed_count: int = 0


@dataclass
class DirectionFilter:
    """方向过滤器。"""
    mode: str = "shadow"
    update_seconds: int = 60
    confirmations: int = 2
    threshold_60m_bps: int = 30
    threshold_15m_bps: int = 10
    max_stale_seconds: int = 900
    
    ticks_file: str = ""
    status_file: str = ""
    log_file: str = ""
    
    _last_calc_time: float = 0.0
    _last_direction: DirectionState = DirectionState.UNKNOWN
    _confirm_count: int = 0
    _transition_target: Optional[DirectionState] = None
    _history: List[Dict[str, Any]] = field(default_factory=list)
    _shadow_stats: Dict[str, Any] = field(default_factory=dict)
    _shadow_filtered_signals: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self._shadow_stats:
            self._shadow_stats = {
                "mode": self.mode,
                "total_candidates": 0,
                "filtered_count": 0,
                "allowed_count": 0,
                "filtered_assumed_pnl": 0.0,
                "filtered_assumed_count": 0,
            }

    def set_history(self, ticks: List[Dict[str, Any]]) -> None:
        """从 manager 注入 BTC ticks 历史数据。"""
        self._history = list(ticks)

    def calculate(self, now: Optional[float] = None) -> DirectionResult:
        """计算当前方向。"""
        now = now or time.time()
        
        if now - self._last_calc_time < self.update_seconds:
            return self._cached_result(now)
        
        self._last_calc_time = now
        result = self._do_calculate()
        self._update_state_machine(result)
        self._log_result(result)
        self._write_status(result)
        return result

    def should_allow_trade(self, signal: Dict[str, Any], now: Optional[float] = None) -> bool:
        """判断是否允许交易信号通过。"""
        if self.mode == "off":
            return True
        
        result = self.calculate(now)
        direction = result.direction
        
        if direction == DirectionState.NEUTRAL:
            return True
        
        if direction == DirectionState.UNKNOWN:
            return True  # shadow 模式不阻止
        
        if direction == DirectionState.TRANSITION:
            return True  # shadow 模式不阻止
        
        if self.mode == "enforce":
            outcome_label = signal.get("outcome_label", "")
            if direction == DirectionState.UP and outcome_label != "Up":
                return False
            if direction == DirectionState.DOWN and outcome_label != "Down":
                return False
        
        return True

    def record_shadow_candidate(self, signal: Dict[str, Any], was_filtered: bool, assumed_pnl: float = 0.0) -> None:
        """记录 shadow 模式下被过滤的候选交易。"""
        stats = self._shadow_stats
        
        if was_filtered:
            stats["filtered_count"] += 1
            stats["filtered_assumed_pnl"] += assumed_pnl
            stats["filtered_assumed_count"] += 1
            self._shadow_filtered_signals.append({
                "t": datetime.now(timezone.utc).isoformat(),
                "slug": signal.get("slug"),
                "outcome_label": signal.get("outcome_label"),
                "edge_bps": signal.get("edge_bps"),
                "fair_selected": signal.get("fair_selected"),
                "current_ask": signal.get("current_ask"),
                "mte_minutes": signal.get("mte_minutes"),
                "assumed_pnl": assumed_pnl,
            })
            if len(self._shadow_filtered_signals) > 1000:
                self._shadow_filtered_signals = self._shadow_filtered_signals[-500:]
        else:
            stats["allowed_count"] += 1
        
        stats["total_candidates"] += 1

    def _do_calculate(self) -> DirectionResult:
        """执行方向计算。"""
        if not self._history:
            return DirectionResult(
                direction=DirectionState.UNKNOWN,
                stale_seconds=self.max_stale_seconds + 1,
            )
        
        now_ts = time.time()
        latest = self._history[-1]
        latest_ts = latest.get("ts", now_ts)
        stale = now_ts - latest_ts
        
        if stale > self.max_stale_seconds:
            return DirectionResult(
                direction=DirectionState.UNKNOWN,
                stale_seconds=stale,
                data_points_15m=len(self._history),
                data_points_60m=len(self._history),
            )
        
        cutoff_15m = latest_ts - 900
        cutoff_60m = latest_ts - 3600
        
        price_now = latest["price"]
        price_15m = None
        price_60m = None
        pts_15m = 0
        pts_60m = 0
        
        for tick in reversed(self._history):
            ts = tick.get("ts", 0)
            if ts >= cutoff_15m:
                pts_15m += 1
            if ts >= cutoff_60m:
                pts_60m += 1
            if price_15m is None and ts <= cutoff_15m - 0.5:
                price_15m = tick["price"]
            if price_60m is None and ts <= cutoff_60m - 0.5:
                price_60m = tick["price"]
        
        pct_15m = 0.0
        pct_60m = 0.0
        
        if price_15m and price_15m > 0:
            pct_15m = (price_now - price_15m) / price_15m * 100.0
        
        if price_60m and price_60m > 0:
            pct_60m = (price_now - price_60m) / price_60m * 100.0
        
        bps_15m = pct_15m * 100
        bps_60m = pct_60m * 100
        
        threshold_60 = self.threshold_60m_bps
        threshold_15 = self.threshold_15m_bps
        
        if bps_60m >= threshold_60 and bps_15m >= threshold_15:
            direction = DirectionState.UP
        elif bps_60m <= -threshold_60 and bps_15m <= -threshold_15:
            direction = DirectionState.DOWN
        else:
            direction = DirectionState.NEUTRAL
        
        return DirectionResult(
            direction=direction,
            pct_15m=round(pct_15m, 4),
            pct_60m=round(pct_60m, 4),
            data_points_15m=pts_15m,
            data_points_60m=pts_60m,
            stale_seconds=round(stale, 1),
        )

    def _update_state_machine(self, result: DirectionResult) -> None:
        """更新方向状态机。"""
        current = self._last_direction
        new_dir = result.direction
        
        if new_dir == DirectionState.UNKNOWN:
            self._confirm_count = 0
            self._transition_target = None
            return
        
        if self._transition_target is not None:
            if new_dir == self._transition_target:
                self._confirm_count += 1
                if self._confirm_count >= self.confirmations:
                    self._last_direction = self._transition_target
                    self._transition_target = None
                    self._confirm_count = 0
            else:
                if new_dir == DirectionState.UP or new_dir == DirectionState.NEUTRAL:
                    self._transition_target = None
                    self._confirm_count = 0
                    self._last_direction = new_dir
        else:
            if new_dir == current:
                self._confirm_count += 1
                if self._confirm_count < self.confirmations:
                    self._transition_target = new_dir
                    self._last_direction = DirectionState.TRANSITION
            else:
                self._confirm_count = 1
                self._transition_target = new_dir
                self._last_direction = DirectionState.TRANSITION
        
        result.confirmed_count = self._confirm_count

    def _cached_result(self, now: float) -> DirectionResult:
        """返回缓存的方向结果。"""
        return DirectionResult(
            direction=self._last_direction,
            stale_seconds=now - self._last_calc_time,
            confirmed_count=self._confirm_count,
        )

    def _log_result(self, result: DirectionResult) -> None:
        """记录方向计算结果到 JSONL 日志。"""
        if not self.log_file:
            return
        
        log_entry = {
            "t": datetime.now(timezone.utc).isoformat(),
            "direction": result.direction.value,
            "pct_15m": result.pct_15m,
            "pct_60m": result.pct_60m,
            "data_points_15m": result.data_points_15m,
            "data_points_60m": result.data_points_60m,
            "stale_seconds": result.stale_seconds,
            "confirmed_count": result.confirmed_count,
            "mode": self.mode,
        }
        
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except (OSError, IOError) as e:
            logger.debug("Failed to write direction log: %s", e)

    def _write_status(self, result: DirectionResult) -> None:
        """更新 bot_status.json 中的方向状态。"""
        if not self.status_file:
            return
        
        try:
            status = {}
            if os.path.exists(self.status_file):
                with open(self.status_file, "r") as f:
                    try:
                        status = json.load(f)
                    except json.JSONDecodeError:
                        pass
            
            status["direction"] = result.direction.value
            status["direction_pct_15m"] = result.pct_15m
            status["direction_pct_60m"] = result.pct_60m
            status["direction_stale_seconds"] = result.stale_seconds
            status["direction_confirmed"] = result.confirmed_count
            status["direction_mode"] = self.mode
            status["direction_updated_at"] = datetime.now(timezone.utc).isoformat()
            
            with open(self.status_file, "w") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
                f.flush()
        except (OSError, IOError) as e:
            logger.debug("Failed to write direction status: %s", e)

    def get_stats(self) -> Dict[str, Any]:
        """获取 shadow 模式下的对比统计。"""
        stats = dict(self._shadow_stats)
        stats["current_direction"] = self._last_direction.value
        stats["transition_target"] = (
            self._transition_target.value if self._transition_target else None
        )
        stats["confirm_count"] = self._confirm_count
        return stats
