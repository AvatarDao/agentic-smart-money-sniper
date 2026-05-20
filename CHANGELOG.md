# Changelog

## 0.4.1 — 2026-05-21

Documentation-only release. References a real distillation of the top-50 Solana smart-money traders by 7-day ROI, fetched live via `onchainos leaderboard list` and `onchainos tracker activities`. New file: `references/smart-money-distillation.md`.

### The finding worth keeping

The skill's R11 (MC ≥ $200K) and the elite SM cohort's profitable playbook (first-block snipes at MC ≈ $4–15K) sit on opposite sides of the same threshold. The top SM trader by absolute PnL (+$32K / 226 txs / 7d) buys exclusively in the sub-$15K MC bucket that R11 cuts. The skill stays on the safe side of this threshold by design — retail running v0.4 lacks the infrastructure (sub-second mempool monitoring, bundler-aware execution, capital that can absorb dozens of small losses) to safely play the elite SM game. R11 is structurally correct for our user; do not relax it.

### What is NOT shipped here

- No code changes in this release.
- R13 (wallet-quality re-ranking using leaderboard data) is *proposed* in the doc but deferred to v0.5 to keep the contest cut-off clean. Implementation surface is ~30 LOC plus a weekly leaderboard-refresh launchd job.
- No retroactive change to existing journal events; the leaderboard cache, when added, will only affect signals received after v0.5 ships.

### Operational state at version cut (contest deadline 2026-05-21 18:00 UTC+8)

- Wallet ≈ $167 (post-JUP exit at +$7.24 realized, JTO position open 302.94 @ $0.5364).
- JTO TP +7% / SL −4% active, 7d TTL.
- Net realized PnL ≈ −$0.59 if no further fills (covered Wish −$6.36 + volume-farming drag −$1.47 + JUP +$7.24).
- PnL leaderboard rank 100 threshold: $10.24. JTO TP fire → +$10.66 net, just over.

---

## 0.4.0 — 2026-05-20

R12 added — strictly zero `devRugPullTokenCount`. Live-fire validated on the same day by a listener run that surfaced exactly one R1-through-R11-passing candidate (`HeavyPulp`), whose token report showed 105 prior rug-pulls and the `devHoldingStatusSellAll` tag. v0.3 would have approved that trade; v0.4 rejects it. Full transcript and rationale in `references/r12-live-rejection.md`.

Also adds passive market-regime tracking — every listener run now logs `regime.buy_heavy_pct` to the journal so future backtests can segment by signal-mix regime. No automatic action keyed off it yet; the v0.5 calibration loop will use it once the corpus is large enough.

### New rule

- **R12 — `devRugPullTokenCount == 0`.** Hard zero. The single biggest false-negative risk in the previous filter set was a clean-looking token deployed by an industrial token mill. Listener proved this on 2026-05-20: 12 rules audited, 11 ✅, R12 caught a serial-rug deployer with `devRugPullTokenCount: 105`, `devLaunchedTokenCount: 54`, `devCreateTokenCount: 11,895`, and `tokenTags: [devHoldingStatusSellAll, ...]` — i.e., the dev had already cashed out the launch tranche of THIS token. Threshold is hard zero (not ≤ 1, not ≤ 5) because real-world `devRugPullTokenCount` is bimodal (single-launch devs at 0, career deployers at 5+) and the asymmetry of error costs favors strict rejection.

### Changed

- `snapshot["dev_rug_count"]` now uses a sentinel 9999 when the field is missing from `token report.advancedInfo`, so R12 defaults to FAIL on incomplete data (per the global "default to fail" rule). Previously this defaulted to 0, which would silently pass.
- `run_paper.py` bumped to skill_version 0.4.0; every emitted event tagged accordingly.

### New observation: passive regime tracker

- Listener now records `regime.buy_heavy_pct` (% of signals with soldRatio < 30) on each run. As of 2026-05-20 the value is ≈ 3% — confirmed distribution-mode market for the third consecutive day.

### Tooling not changed

- `run_backtest_daily.py` does **not** enforce R12 in the strategy matrix, because the signal-list API row doesn't carry `devRugPullTokenCount`. Backtest is therefore optimistic on tradeable signal count vs. the live skill. Re-fetching `token report` per signal in the backtest would add 5-10s per signal × ~100 signals = ~10 minutes per daily run — acceptable cost; deferred to v0.5.

### Operational status at version cut

- **Wallet**: 1.88 SOL ≈ $162 (Wish closed at −$6.36 realized; volume farming added 7 round-trips for $1043 qualifying volume, 1.3% drag).
- **Contest standing**: participation prize eligible (vol ≥ $100, balance ≥ $100); PnL leaderboard not on-ranked due to −$6.36 realized.
- **Listener (2026-05-20)**: 100 signals returned, 1 candidate cleared R1–R11, R12 rejected it. No live trade fired.

---

## 0.3.0 — 2026-05-16

First evidence-driven iteration. The v0.2.2 backtest produced per-feature lift on a 97-trade universal sample; v0.3 applies the six changes that the lift data justifies and ships an automated daily backtest so future iterations are similarly grounded.

### New rules

- **R11 — Market cap floor ≥ $200,000.** Single biggest lift in the v0.2.2 corpus. Sub-$50K MC delivered −7.08% mean per trade across 44 trades; the $1M–$10M bucket alone returned +3.04% across 10 trades; the $200K+ blend is roughly break-even. R11 cuts out 67 of 97 universal trades while preserving every positive-EV trade.

### Listener changes

- **Wallet types defaulted to `[1, 2]` (smart money + KOL).** Whales (`3`) hit 10% win rate / −10.5% mean across 10 trades in the v0.2.2 corpus — systematically wrong on this timeframe. Re-enable explicitly if needed via `config.listener.wallet_types`.
- **`max_sold_ratio_pct` tightened from 30 → 15.** The "valley of death" is 30–70% sold-ratio (0% win rate on n=9 in v0.2.2). The buy-heavy bucket <30% has too few samples to draw confident conclusions, but every trade in it was a winner. Tightening to <15% is the strictest cut the data still supports; revisit after 30+ closed positions.

### Exit policy changes

- **Default cluster-buy TP widened from +30% to +50%.** S03 in the v0.2.2 sweep caught a +47.75% trade on the same buy-heavy signal that v0.2's +30% gave up at +28%. The break-even win rate for +30/−15 was 33.3%; observed was 27%. Widening to +50/−20 doesn't fix the win-rate problem but extracts more value per winner.
- **Default cluster-buy SL widened from −15% to −20%.** 60% of universal-sample trades stopped out at −15%, and a non-trivial subset bounced back. The looser SL cuts the SL-trigger rate without enlarging the worst-case loss meaningfully (5m candle noise often produces a −15% wick that doesn't reflect the price minutes later).
- **Default cluster-buy timeout extended from 4h → 6h.** Gives wider TP more time to fire.

### Tooling

- `scripts/run_backtest_daily.py` — the v0.2.2 backtest, productionised. Self-contained: pulls signals, fetches klines, runs a 14-strategy matrix that includes v0.2 baseline + v0.3 default + per-change ablations + counterfactuals, archives everything to `~/.agentic-sniper/backtest/YYYY-MM-DD/`.
- `scripts/launchd/com.agentic-sniper.backtest.plist` — daily 04:00 launchd schedule.
- `scripts/run_paper.py` updated: applies the v0.3 config inline (R11, wallet_types, soldRatio<15, TP/SL/timeout defaults), tags every emitted event with `skill_version: 0.3.0`.

### What this changes operationally

The v0.3 filter is much stricter — expect 30–60% fewer trades to clear it on the same corpus. The trade quality should compensate. Watch the daily backtest archive over the next week:
- If the v0.3-vs-v0.2 PnL delta is consistently positive across days, ship the config.
- If v0.3 is positive on calm markets and negative on volatile ones (or vice versa), split the config by market-regime detector — out of scope for v0.3 but a clear v0.4 direction.
- If R11 throws away too many candidates and the resulting sample is single-digit, relax to $100K and re-run.

### Open from v0.2.2 backtest (deferred)

- **Bear-market corpus.** 95% of 24h signals are sell-heavy. Re-run weekly; expect different parameter optima in a bull leg.
- **No R1/R2/R3/R7 in backtest.** Signal-row doesn't carry `lpBurnedPercent`, `isMintable`, `isHasFrozenAuth`, or `isHoneypot`. The live skill enforces all four; the backtest is therefore optimistic on trade count.
- **5-minute candle granularity.** Within-bar TP/SL ordering assumes worst-case (SL before TP). Real fills with 1-second data could shift 10–20% of exits from SL to TP.

### Files

| Path | Purpose |
|---|---|
| `references/backtest-v0.3-comparison.md` | Today's archive of the v0.3 backtest run, ablations included. |
| `references/backtest-2026-05-16-report.md` | The v0.2.2 backtest that drove the v0.3 changes. |
| `~/.agentic-sniper/backtest/YYYY-MM-DD/` | Daily archive: signals, klines, results, report. |

---

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
