#!/usr/bin/env python3
"""Explore FV + edge combined strategies.

Hypothesis: edge alone makes money, but combining FV confidence / z-score
as a filter or weighting layer could improve.

Variants tested (all require |edge| >= baseline threshold first):
  V1: edge baseline (no FV filter)
  V2: edge + FV direction agrees (e.g. edge>0 means FV says UP > market)
  V3: edge + FV confidence high (fair_up extreme or fair_z_score large)
  V4: edge + FV doesn't disagree strongly (avoid cases FV is bullish but market knows better)
  V5: edge + z-score magnitude weighted (size bet by z)
  V6: edge + FV overconfidence discount (skip trades where FV calibration is biased)
"""

from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRED = ROOT / "data" / "fair_value_predictions.jsonl"
RESO = ROOT / "data" / "fair_value_resolutions.json"
OUT = ROOT / "data" / "fv_edge_combined_report.json"


def load():
    rows = []
    with PRED.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    resos = json.loads(RESO.read_text()) if RESO.exists() else {}
    enriched = []
    for r in rows:
        slug = r.get("slug")
        reso = resos.get(slug)
        if not reso or reso.get("resolved_up") is None:
            continue
        r2 = dict(r)
        r2["resolved_up"] = int(reso["resolved_up"])
        enriched.append(r2)
    return enriched


def pick_per_slug(rows, target_mte, edge_thr=0, variant="v1"):
    """Replay the first eligible row inside the production MTE window.

    Rows are ordered from the start of the entry window toward expiry. There
    is deliberately no out-of-window fallback: production never trades a
    market before the configured window or after it has expired.
    """
    by_slug = defaultdict(list)
    for r in rows:
        by_slug[r["slug"]].append(r)
    picked = []
    for slug, slug_rows in by_slug.items():
        slug_rows.sort(key=lambda x: x.get("minutes_to_end", 0), reverse=True)
        chosen = None
        for r in slug_rows:
            mte = r.get("minutes_to_end")
            if mte is None or not 0 < mte <= target_mte:
                continue
            if not _variant_allows(r, edge_thr, variant):
                continue
            chosen = r
            break
        if chosen:
            picked.append(chosen)
    return picked


def edge_trade(r, edge_thr_bps, stake=1.0):
    """Return a fixed-stake trade using both executable asks."""
    fair_up = r.get("fair_up")
    up_ask = r.get("market_up_ask")
    down_ask = r.get("market_down_ask")
    resolved = r.get("resolved_up")
    if fair_up is None or up_ask is None or down_ask is None or resolved is None:
        return None
    fair_down = 1.0 - fair_up
    edge_up = (fair_up - up_ask) * 10000.0
    edge_down = (fair_down - down_ask) * 10000.0
    edge, outcome_index, outcome_label, buy_price = max(
        (edge_up, 0, "Up", up_ask),
        (edge_down, 1, "Down", down_ask),
        key=lambda item: item[0],
    )
    if edge < edge_thr_bps or buy_price <= 0:
        return None
    won = resolved == (1 if outcome_index == 0 else 0)
    shares = stake / buy_price
    pnl = stake * ((1.0 - buy_price) / buy_price) if won else -stake
    return {
        "won": won,
        "pnl": pnl,
        "stake": stake,
        "buy_price": buy_price,
        "shares": shares,
        "edge_bps": edge,
        "outcome_index": outcome_index,
        "outcome_label": outcome_label,
        "fair_selected": fair_up if outcome_index == 0 else fair_down,
        "fair_up": fair_up,
        "fair_down": fair_down,
    }


def _variant_allows(r, edge_thr, variant):
    t = edge_trade(r, edge_thr)
    if not t:
        return False
    if variant in {"v2", "v6"} and t["fair_selected"] <= 0.5:
        return False
    if variant in {"v4", "v6"} and r.get("minutes_to_end", 0) > 2.0:
        return False
    if variant == "v3":
        z = r.get("fair_z_score", 0) or 0
        if (t["outcome_index"] == 0 and z < 1.0) or (t["outcome_index"] == 1 and z > -1.0):
            return False
    if variant == "v5":
        fair = t["fair_selected"]
        if 0.2 <= fair < 0.3 or 0.4 <= fair < 0.5 or 0.9 <= fair <= 1.0:
            return False
    return True


def stats(trades):
    if not trades:
        return {"trades": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t["won"])
    total_pnl = sum(t["pnl"] for t in trades)
    invested = sum(t.get("stake", 1.0) for t in trades)
    return {
        "trades": n,
        "win_rate": round(wins / n * 100, 2),
        "total_pnl": round(total_pnl, 3),
        "roi_pct": round(total_pnl / invested * 100, 2) if invested else 0,
    }


def variant_v1_edge_only(picked, edge_thr):
    trades = []
    for r in picked:
        t = edge_trade(r, edge_thr)
        if t:
            trades.append(t)
    return trades


def variant_v2_edge_and_fv_agrees(picked, edge_thr):
    """Same direction bet — FV agrees with direction (edge>0 means FV > market, so FV bullish)."""
    trades = []
    for r in picked:
        t = edge_trade(r, edge_thr)
        if not t:
            continue
        # Only buy the model-favorite side in the temporary V2 risk variant.
        if t["fair_selected"] > 0.5:
            trades.append(t)
    return trades


def variant_v3_edge_and_strong_fv(picked, edge_thr, z_min=1.0):
    """Require FV has at least z=z_min confidence in the direction."""
    trades = []
    for r in picked:
        t = edge_trade(r, edge_thr)
        if not t:
            continue
        z = r.get("fair_z_score", 0) or 0
        if (t["outcome_index"] == 0 and z >= z_min) or (t["outcome_index"] == 1 and z <= -z_min):
            trades.append(t)
    return trades


def variant_v4_edge_and_low_mte(picked, edge_thr, mte_max=2.0):
    """FV is more accurate near window close — only bet when mte is small."""
    trades = []
    for r in picked:
        mte = r.get("minutes_to_end", 0)
        if mte > mte_max:
            continue
        t = edge_trade(r, edge_thr)
        if t:
            trades.append(t)
    return trades


def variant_v5_calibration_discount(picked, edge_thr):
    """When FV is in known biased bucket (0.4-0.5 or 0.9-1.0), reduce conviction.
    Just skip trades where FV is in the bad buckets from calibration analysis."""
    trades = []
    for r in picked:
        t = edge_trade(r, edge_thr)
        if not t:
            continue
        fair = t["fair_selected"]
        # FV calibration bad buckets: 0.2-0.3, 0.4-0.5, 0.9-1.0
        bad = (0.2 <= fair < 0.3) or (0.4 <= fair < 0.5) or (0.9 <= fair <= 1.0)
        if bad:
            continue
        trades.append(t)
    return trades


def variant_v6_edge_and_strong_fv_strict(picked, edge_thr):
    """Combo: edge + FV agrees (v2) + low mte (v4)."""
    trades = []
    for r in picked:
        if r.get("minutes_to_end", 0) > 2.0:
            continue
        t = edge_trade(r, edge_thr)
        if not t:
            continue
        if t["fair_selected"] > 0.5:
            trades.append(t)
    return trades


def main():
    rows = load()
    print(f"Loaded {len(rows)} rows, {len(set(r['slug'] for r in rows))} unique slugs")

    target_mte = 1.5

    results = {}
    for edge_thr in [100, 300, 500, 700]:
        v1 = variant_v1_edge_only(pick_per_slug(rows, target_mte, edge_thr, "v1"), edge_thr)
        v2 = variant_v2_edge_and_fv_agrees(pick_per_slug(rows, target_mte, edge_thr, "v2"), edge_thr)
        v3 = variant_v3_edge_and_strong_fv(pick_per_slug(rows, target_mte, edge_thr, "v3"), edge_thr)
        v4 = variant_v4_edge_and_low_mte(pick_per_slug(rows, target_mte, edge_thr, "v4"), edge_thr)
        v5 = variant_v5_calibration_discount(pick_per_slug(rows, target_mte, edge_thr, "v5"), edge_thr)
        v6 = variant_v6_edge_and_strong_fv_strict(pick_per_slug(rows, target_mte, edge_thr, "v6"), edge_thr)

        results[f"edge{edge_thr}_bps"] = {
            "V1_edge_only": stats(v1),
            "V2_edge+FV_agrees": stats(v2),
            "V3_edge+|z|>=1.0": stats(v3),
            "V4_edge+mte<=2": stats(v4),
            "V5_edge-skip_bad_cal": stats(v5),
            "V6_edge+FV_agrees+mte<=2": stats(v6),
        }

    print(f"\n--- COMBINED STRATEGY COMPARISON (first eligible, max mte={target_mte}) ---")
    print(f"{'edge':<6} {'variant':<28} {'trades':>6} {'win%':>6} {'ROI%':>8}")
    for edge_thr in [100, 300, 500, 700]:
        key = f"edge{edge_thr}_bps"
        print(f"\n  Threshold: {edge_thr} bps")
        for vname, vstats in results[key].items():
            if vstats.get("trades", 0) > 0:
                print(f"  {vname:<28} {vstats['trades']:>6} {vstats['win_rate']:>5.1f}% {vstats['roi_pct']:>+7.2f}%")

    # Save report
    OUT.write_text(json.dumps(results, indent=2))
    print(f"\nReport saved: {OUT}")

    # Verdict
    print(f"\n=== VERDICT ===")
    best_v1_roi = max((results[k]["V1_edge_only"].get("roi_pct", 0) for k in results), default=0)
    print(f"  Baseline V1 best ROI: {best_v1_roi:+.2f}%")
    for variant in ["V2_edge+FV_agrees", "V3_edge+|z|>=1.0", "V4_edge+mte<=2",
                    "V5_edge-skip_bad_cal", "V6_edge+FV_agrees+mte<=2"]:
        best = max((results[k][variant].get("roi_pct", 0)
                    for k in results if results[k][variant].get("trades", 0) > 0), default=0)
        beats = best > best_v1_roi
        marker = "+" if beats else "-"
        print(f"  {variant:<28} best ROI: {best:>+7.2f}%  beats_V1={marker}")


if __name__ == "__main__":
    main()
