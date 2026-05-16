# Changelog

## 0.2.0 — 2026-05-16

Iteration after the first live trade exposed two problems: TP/SL slippage was way too loose for the position size we actually run at, and we had no path to recalibrate other than guessing. v0.2 swaps the operational stance from "trade live by default, dry-run as opt-out" to "paper by default, live as opt-in" — and adds the data plumbing that makes recalibration mechanical.

### New

- **Three explicit modes**: `paper` (default, virtual fills against real spot), `shadow` (signals + filter only, no fills), `live` (real trades, gated by typed `I understand` valid for 30 days).
- **Signal feature snapshot**: every `signal_received` event records the full upstream signal row plus derived features (wallet_count, sold_ratio_pct, market_cap, holders, top10%, liquidity, 1h/24h price change). Carried forward unchanged on every later event for the same `run_id`.
- **Paper-mode monitor loop**: polls `okx-dex-token price-info` every 5 minutes for open virtual positions; fires virtual TP / SL / timeout exits using the same exit rules as live mode. Slippage simulated from a configurable distribution.
- **Backtest spec** (`references/backtest.md`): three artifacts — hypothetical PnL under config drift, parameter sensitivity sweeps, per-feature lift — plus a bootstrap protocol to guard against overfitting on small corpora. Runner ships in v0.3.
- **Config epochs**: `config.yaml` edits append a `config_changed` event to the journal, so backtests can segment by config version.

### Changed

- **Default exit slippage**: 10% → 3%. The v0.1 live trade had actual price impact of 0.92% on a $15 position against $118K liquidity — 10% was wasteful padding. The new value is conservative-but-realistic; paper-mode fills will tell us if it needs to go up or down per signal class.
- **Default entry slippage**: 2% (unchanged in practice — v0.1 used `--slippage 2`; now explicit in config).
- **Filter R6 (bundling)**: now reads `bundleHoldingPercent` directly from `token report.advancedInfo` (threshold 10%), rather than the indirect "5 top holders shared funder" heuristic which wasn't observable in `token report`.
- **Filter R7 (price impact)**: tightened from 50% to 5%, sourced from the entry `swap quote` rather than `security tx-scan`. 50% was a honeypot guard, not a fill-quality guard; we want both.
- **Skill default mode**: was `--dry-run` (which actually still hit the network and the wallet API); now `paper`, which writes a full virtual fill life-cycle to the journal.

### Operational notes

- Open v0.1 live position on Wish remains active with the 10% slippage budget. Not retroactively tightened — the position is small enough that the wasted padding caps at a few cents and rewriting limit orders mid-run is more risk than benefit.
- The paper corpus and live corpus share the same journal schema; backtest merges them on `run_id` for calibration.

---

## 0.1.0 — 2026-05-16

Initial release for the OKX Agentic Trading Contest. Five-module pipeline (Listener → Filter → Sizer → Executor → Monitor), 10-rule risk filter, Kelly-bounded fractional sizing, TP/SL via `okx-dex-strategy` limit orders. Includes a captured live demo run on `Wish` token with on-chain proof of execution.
