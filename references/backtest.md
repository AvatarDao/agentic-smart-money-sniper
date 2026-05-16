# Backtest & Calibration

The skill's journal is the dataset. The backtest harness replays the journal against historical price data and produces three artifacts: hypothetical PnL, parameter sensitivity, and per-feature lift. The harness ships in v0.3; v0.2 ships only the specification and worked example below.

## What we replay

A "trade" in the corpus is a chain of journal events sharing one `run_id` that reaches at least `position_opened`. The backtest harness:

1. Reads all such chains from `~/.agentic-sniper/trades.jsonl`.
2. For each, extracts the signal feature snapshot from the `signal_received` event.
3. Fetches the historical price series for the token from the entry timestamp through the exit timestamp (via `onchainos token price-info` history or candles from `okx-dex-market`).
4. Re-simulates the position under a candidate config — applies the candidate's TP / SL / timeout / slippage rules to the same price series.
5. Records the hypothetical exit and PnL.

The skill's design guarantees this is replayable: every `signal_received` carries the full feature dict, every `position_opened` carries the entry price, and every closed run summarises duration so the price window is bounded.

## Three artifacts

### 1. Hypothetical PnL — config drift detector

Re-run the full corpus under (a) the original config the trade was made under and (b) the current config. The delta tells you whether your config changes are improving or degrading historical performance.

| Trade | Original config TP/SL/timeout | Original PnL | Current config TP/SL/timeout | Hypothetical PnL | Δ |
|---|---|---|---|---|---|
| `r1` | 30/-15/4h | +$3.20 | 25/-12/3h | +$2.80 | −$0.40 |
| `r2` | 30/-15/4h | −$1.10 | 25/-12/3h | −$0.90 | +$0.20 |
| … | | | | | |
| **Total** | | **+$X** | | **+$Y** | **Δ$Z** |

If the **current** config underperforms the **original** on aggregate, revert. If it outperforms on > 70% of bootstrap resamples, keep.

### 2. Parameter sensitivity table

Sweep one parameter at a time over a grid, recomputing the whole corpus's PnL each time. Plot the curve; pick the point that maximises (mean PnL × √n) so single outliers don't dominate.

Example for `tp_pct` (cluster_buy class):

| `tp_pct` | n_trades | win_rate | mean_pnl_pct | sharpe-equiv | hit_rate (TP fired vs total exits) |
|---|---|---|---|---|---|
| 0.15 | 48 | 0.71 | 0.041 | 0.92 | 0.65 |
| 0.20 | 48 | 0.63 | 0.058 | 1.12 | 0.50 |
| 0.30 | 48 | 0.42 | 0.072 | 1.20 | 0.27 |
| 0.40 | 48 | 0.31 | 0.069 | 1.04 | 0.18 |
| 0.50 | 48 | 0.21 | 0.058 | 0.78 | 0.09 |

In this synthetic example, `tp_pct = 0.30` maximises the sharpe-equivalent — confirming the v0.2 default. A real run on the corpus may move this; that's the point.

Other sweep dimensions:
- `sl_pct`: −0.05 to −0.30 by 0.05
- `min_wallet_count`: 2, 3, 4, 5
- `max_sold_ratio_pct`: 10, 20, 30, 40, 50
- `timeout_hours`: 1, 2, 4, 8, 16
- `slippage_exit`: 1, 2, 3, 5, 10 (driven by paper corpus realisations)

### 3. Per-feature lift

For each feature in the `signal` block, compute conditional win-rate vs. corpus average. Surfaces which features actually predict winners.

| Feature | Bucket | n | win_rate | lift |
|---|---|---|---|---|
| wallet_count | 3 | 88 | 0.32 | −0.06 |
| wallet_count | 4 | 41 | 0.41 | +0.03 |
| wallet_count | 5+ | 19 | 0.58 | +0.20 |
| sold_ratio_pct | < 5 | 67 | 0.45 | +0.07 |
| sold_ratio_pct | 5–15 | 52 | 0.38 | 0.00 |
| sold_ratio_pct | 15–30 | 29 | 0.21 | −0.17 |
| market_cap_usd | < $100K | 33 | 0.27 | −0.11 |
| market_cap_usd | $100K–$500K | 71 | 0.42 | +0.04 |
| market_cap_usd | > $500K | 44 | 0.39 | +0.01 |

These tell us, for instance: tighten the soldRatio gate to 15%; require 4+ wallets for a position; treat sub-$100K MC as a separate (lower-confidence) class.

## Calibration loop

Run **weekly** or after every 50 closed positions, whichever comes first:

1. `sniper backtest --since <last_calibration_ts>` produces the three artifacts above.
2. The harness proposes a *single* config diff — the change with the largest expected lift on bootstrap resamples (n=500).
3. User sees the diff plus the lift distribution plot, and accepts or rejects.
4. Accepted change is written to `config.yaml`; a `config_changed` event is appended to the journal with the old → new diff, so future backtests can segment by config epoch.

Why a single change at a time: simultaneous parameter changes can mask each other; isolating one keeps the causal chain auditable.

## Bootstrap protocol

To guard against overfitting on a small corpus (likely for the first weeks):

- Split the journal into 500 bootstrap resamples with replacement.
- Compute the proposed change's lift on each resample.
- Accept only if lift > 0 on ≥ 70% of resamples **and** the median lift > 0.5 × estimated noise.
- The noise estimate is the standard deviation of `mean_pnl_pct` across the bootstrap resamples under the *current* config.

This is not academic — over a 5-day contest window with maybe 50–100 closed positions, a naive "max-PnL" calibration will routinely pick noise.

## Where this lives

- Backtest harness: `scripts/backtest.py` (added v0.3)
- Replay engine: `scripts/replay.py` (added v0.3)
- Historical price fetch: thin wrapper around `onchainos token price-info` + `okx-dex-market candles`
- Output format: markdown report to stdout, JSON artefact to `~/.agentic-sniper/backtest/YYYY-MM-DD/`

v0.2 ships the spec and the schema. The runner is v0.3 work, deferred until the corpus is big enough to be informative (≥ 50 closed positions).
