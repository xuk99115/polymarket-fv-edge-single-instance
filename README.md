# Polymarket FV Edge Bot

BTC 15-minute UP/DOWN market trader using one strategy only: FV Edge.

The bot estimates the fair UP/DOWN probability from:

- current BTC spot price;
- the window-start BTC reference price;
- estimated 15-minute volatility;
- time remaining until settlement.

It buys only when one side's fair probability exceeds that side's executable ask by the configured edge threshold. Accepted positions are held to expiry.

## Start

Requires Python 3.10 or newer so a current `py-clob-client` build is available.

```bash
chmod +x run.sh
./run.sh
```

The dashboard is available at `http://localhost:8889` by default.

## Runtime Backup

Recovery-critical runtime state is exported from `/tmp/polymarket-fv-edge/data` into
`history/github-runtime-backup/` and can be pushed to GitHub on demand.

```bash
# Export only when state changed; pushes to origin/main and backup-20260713/fv-edge-main
python3 scripts/github_runtime_backup.py

# Dry run: refresh backup directory only, do not commit/push
python3 scripts/github_runtime_backup.py --no-push

# Restore backup files back into runtime before starting the bot
python3 scripts/restore_runtime_from_github.py
```

Only these files are included in the GitHub runtime backup:

- `paper_trade_state.json`
- `state_summary.json`
- `bot_status.json`
- `direction_state.json`
- `sync_health.json`

Large replay/audit logs such as `btc_ticks.jsonl`, `fv_direction.jsonl`, and
`position_audit.jsonl` are intentionally excluded.

## Configuration

On first launch, `run.sh` copies `.env.example` to `.env`. Important settings:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `TRADING_MODE` | `paper_live` | `paper_live` or `live` |
| `DRY_RUN` | `true` | Must be explicitly set to `false` for real orders |
| `FV_EDGE_ENABLE_LIVE` | `false` | Disabled until settlement/redeem lifecycle is implemented |
| `FV_EDGE_POSITION_USD` | `2.0` | Stake per accepted signal |
| `FV_EDGE_THRESHOLD_BPS` | `300` | Minimum positive edge |
| `FV_EDGE_MAX_MTE` | `1.5` | Latest entry window in minutes |
| `FV_EDGE_MIN_PRICE` | `0.10` | Minimum executable ask |
| `FV_EDGE_MAX_PRICE` | `0.85` | Maximum executable ask |
| `FV_EDGE_MAX_BTC_AGE_SECONDS` | `3` | Reject stale Chainlink measurements |
| `FV_EDGE_MAX_REF_DELAY_SECONDS` | `10` | Reject late window references |
| `BTC_PRICE_SOURCE` | `chainlink` | FV execution price source; Binance is volatility-only |
| `FV_EDGE_REQUIRE_FAVORITE_SIDE` | `true` | Temporary risk gate requiring selected FV side > 50% |
| `FV_EDGE_REQUIRE_CHAINLINK` | `true` | Reject entries without same-source Chainlink price/reference |
| `FV_EDGE_MAX_BOOK_AGE_SECONDS` | `3` | Reject stale CLOB snapshots |

Live mode requires valid Polymarket credentials. The bot refuses mode changes while positions or active orders exist.

## Layout

```text
bot.py                    entry point
src/trading/fv_edge.py    FV Edge signal engine
src/trading/manager.py    FV-only lifecycle and risk controls
src/trading/executor.py   paper/live order execution
src/api/                  market, BTC, fair-value, and WebSocket clients
src/server/               local dashboard API
tests/                    FV and infrastructure tests
```

This software is for research and testing. Prediction-market trading can lose the full position value.
