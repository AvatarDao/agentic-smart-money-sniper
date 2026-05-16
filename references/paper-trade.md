# Paper Trade Mode

Paper mode runs the **full** five-module pipeline, but the Executor records virtual fills against real spot prices instead of broadcasting transactions. The Monitor module polls the same `price-info` endpoint every five minutes and fires virtual TP / SL / timeout exits identically to how live mode would.

Paper is the default mode in v0.2. The point is to accumulate a corpus of *real signals → real prices → simulated outcomes* before risking capital, so v0.3 can ship calibrated parameters rather than hand-tuned guesses.

## What paper mode does and doesn't do

### Does
- Pull the same signals from `onchainos signal list` as live mode.
- Apply the same soldRatio gate (`< 30%`).
- Run the same ten-rule safety filter via `onchainos token report`.
- Compute the same Kelly-bounded position size.
- Write the same journal schema, with `"mode": "paper"`.
- Record the **actual** quote price (`onchainos swap quote`) at the moment of "entry" — so the virtual fill matches what a real fill would have gotten, modulo slippage.
- Add a `simulated_slippage_pct` to entry and exit fills, sampled from the empirical distribution (1.5% default until enough live fills accumulate).

### Doesn't
- Broadcast any transaction.
- Pay any gas.
- Call `swap execute` or `strategy create-limit`.
- Affect wallet balance.

## Virtual fill arithmetic

**Entry fill** at journal event `position_opened`:
```
quote_price       = okx-dex-swap quote (fromToken→toToken, size_usd)
simulated_slip    = 1.5% (config default; will be replaced by empirical when n ≥ 50)
virtual_entry     = quote_price * (1 + simulated_slip)        # paying more = worse price for buy
tokens_received   = size_usd / virtual_entry
```

**TP fill** when spot ≥ `entry_price * (1 + tp_pct)`:
```
spot              = okx-dex-token price-info (current)
simulated_slip    = 1.5%
virtual_exit      = spot * (1 - simulated_slip)               # receiving less = worse price for sell
proceeds_usd      = tokens_held * virtual_exit
pnl_usd           = proceeds_usd - entry_size_usd
pnl_pct           = pnl_usd / entry_size_usd
```

**SL fill** when spot ≤ `entry_price * (1 + sl_pct)`:
```
same as TP but with the SL trigger price; same slippage direction (sell side).
```

**Timeout fill** at `entry_ts + timeout_hours`:
```
virtual_exit      = current_spot * (1 - simulated_slip)
journal event     = timeout_close
```

## Poll cadence

The monitor module runs every five minutes. On each poll:

1. Read all `run_id`s whose latest event is `tp_set` or `sl_set` (open positions).
2. For each, fetch current spot via `onchainos token price-info`.
3. Check TP / SL / timeout conditions; fire the appropriate exit event.
4. Append a `monitor_poll` event with the spot read so the price series is reconstructable later for backtest.

Five minutes is a deliberate tradeoff. Memecoin moves at minute resolution are noisy enough that more frequent polling adds backend cost without improving the corpus. Backtest can interpolate between polls using on-chain candles when finer granularity is wanted.

## Why paper mode is essential before live scaling

The 2026-05-16 demo live run on Wish:
- Size: $15.5 entry against $118K liquidity
- Realized price impact: 0.92%
- Configured TP/SL slippage budget: **10%**

A 10% slippage budget on a sub-1% impact trade is wasteful — it widens the effective exit price by an order of magnitude. But going to 1% would risk fill failures during a fast wick. The right answer is to measure the actual fill quality across many trades and set the budget at the 95th percentile of observed impacts — **not** to guess. Paper mode produces exactly that data.

After ~50 paper closes, run `sniper backtest` and re-tune `slippage_exit` per signal class. After ~200 closes, the calibration is dense enough to differentiate by liquidity bucket and time-of-day.

## Replaying paper to live

Once parameters are calibrated and the user wants to commit capital, set `mode: live` in config. The skill flips the Executor and Monitor to broadcast paths; the journal schema, signal flow, and exit policy are unchanged. The corpus from paper continues to be used by backtest — paper and live events are merged on `run_id` for calibration purposes.

If a live config performs noticeably worse than its paper sibling on the same parameter set, the discrepancy is captured in a `paper_vs_live_drift` metric in the next `run_summary` and surfaced to the user.

## Operational notes

- Paper mode still requires `onchainos wallet login` because the signal API is authenticated. No funds are at risk; the login is just for API access.
- Paper journal events are interleaved with live events in the same file. Tools should always filter by `mode` when computing summaries.
- A paper run that produces a `position_opened` event with `size_usd = 0` indicates the Sizer rejected for too-small bankroll — useful diagnostic, do not treat as a bug.
- Killing the agent mid-run does not lose state: each event is fsync'd to the journal before the next module starts. On restart, the monitor module picks up open positions from the journal.
