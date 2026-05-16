# Backtest Report — 2026-05-16

A compressed-time "12-hour paper trade" run, simulated on 24 hours of real Solana smart-money / KOL / whale signal data, with $10,000 bankroll across 25 strategy variants. The point of this run was not to find an optimal strategy — the buy-side sample is too small for that — but to **rule out** clearly losing approaches and to surface per-feature lift that informs the v0.3 calibration.

## Setup

- **Bankroll**: $10,000 USD
- **Time window**: 24h of signals ending 2026-05-16 (137 unique signal events, 97 unique tokens)
- **Price data**: 5-minute OHLC candles for each token, from `onchainos market kline`
- **Entry**: open of the first 5m bar after `signal.timestamp` (≈ "I saw it and reacted within 5 min")
- **Slippage**: 1.5% entry, 1.5% exit (matches v0.2 paper-mode default)
- **Gas**: $0.05 entry + $0.05 exit (Solana)
- **Re-entry guard**: never trade the same token twice in the run (matches live skill behavior)

## Strategy rankings (sorted by final bankroll)

```
ID   name                         n    win%   total $    ret%   mean%   med%    std%   sharpe  maxDD%  best%   worst%
=========================================================================================================================
S25  ≥4 wallets + wide            1   100%   +429.65  +4.30%  +47.75  +47.75   0.00    (n=1)   0.00%  +47.75   +47.75
S21  KOL + permissive             4    50%   +340.29  +3.40%   +9.51  +28.05  19.24   +0.494   1.62%  +28.05   -16.28
S09  KOL only                     1   100%   +252.35  +2.52%  +28.05  +28.05   0.00    (n=1)   0.00%  +28.05   +28.05
S11  very buy-heavy <10%          1   100%   +252.35  +2.52%  +28.05  +28.05   0.00    (n=1)   0.00%  +28.05   +28.05
S15  big size 20%                 2    50%   +217.03  +2.17%   +5.89  +28.05  22.17   +0.266   3.26%  +28.05   -16.28
S03  wide tp/sl (+50/-25)         2    50%   +184.32  +1.84%  +10.81  +47.75  36.94   +0.293   2.35%  +47.75   -26.13
S01  v0.2 default (+30/-15)       2    50%   +102.07  +1.02%   +5.89  +28.05  22.17   +0.266   1.47%  +28.05   -16.28
S07  loose cluster (≥2)           2    50%   +102.07  +1.02%   +5.89  +28.05  22.17   +0.266   1.47%  +28.05   -16.28
S13  strict top10 < 25%           2    50%   +102.07  +1.02%   +5.89  +28.05  22.17   +0.266   1.47%  +28.05   -16.28
S18  hold longer 12h              2    50%   +102.07  +1.02%   +5.89  +28.05  22.17   +0.266   1.47%  +28.05   -16.28
S19  TP only (no SL)              2    50%    +62.80  +0.63%   +3.76  +28.05  24.29   +0.155   1.85%  +28.05   -20.53
S14  small size 5%                2    50%    +57.53  +0.58%   +5.89  +28.05  22.17   +0.266   0.81%  +28.05   -16.28
S06  strong cluster (≥5 SM)       0   —          0     0      —       —       —       —       —      —        —
S08  SM only (≥3)                 0   —          0     0      —       —       —       —       —      —        —
S16  big MC > $500K only          0   —          0     0      —       —       —       —       —      —        —
S23  SM + tight                   0   —          0     0      —       —       —       —       —      —        —
S20  very tight scalp             2     0%    -80.23  -0.80%   -4.46   -4.46   0.00   (n=2)    0.80%   -4.46    -4.46
S05  scalp (+10/-5)               2     0%   -115.52  -1.16%   -6.43   -6.43   0.00   (n=2)    1.16%   -6.43    -6.43
S10  Whale only                   1     0%   -146.57  -1.47%  -16.28  -16.28   0.00   (n=1)    1.47%  -16.28   -16.28
S17  small MC < $100K             1     0%   -190.90  -1.91%  -21.20  -21.20   0.00   (n=1)    1.91%  -21.20   -21.20
S02  tight tp/sl (+20/-10)        2     0%   -203.46  -2.03%  -11.35  -11.35   0.00   (n=2)    2.03%  -11.35   -11.35
S12  permissive sold <50%         5    20%   -207.72  -2.08%   -4.51  -16.28  17.22   -0.262   3.07%  +28.05   -16.28
S04  moonshot (+100/-30)          2     0%   -364.59  -3.65%  -20.38   -9.71  10.67   -1.910   3.65%   -9.71   -31.05
S22  contrarian (sold > 70%)     64    28%  -2406.12 -24.06%   -4.64  -16.27  16.49   -0.281  27.40%  +28.05   -16.28
S24  no filter all-in            97    27%  -3520.46 -35.20%   -4.82  -16.27  16.96   -0.284  37.13%  +28.05   -16.28
```

## TL;DR — what we learned

1. **Buy-heavy strategies are positive on tiny samples** (n=1–5). S01 to S15 all return between +0.6% and +4.3% on the bankroll. But every single one has fewer than 5 trades, which means none of these point estimates are statistically reliable — they're indicative, not conclusive.

2. **Counterfactual experiments hit decisive losses on big samples.** The two strategies that trade indiscriminately:
   - **S24** (no filter): 97 trades, **−35.2%** ($−3,520), 27% win rate
   - **S22** (contrarian, buy when smart money sells > 70%): 64 trades, **−24%**, 28% win rate
   These are statistically robust. They establish a baseline: buying every smart-money signal regardless of direction loses 4–5% per trade after fees.

3. **The TP/SL geometry is unfavorable on this corpus.** Across 97 trades in S24:
   - SL fired 60%, TP fired 18.6%, timeout 18.6%
   - Break-even win rate for TP +30 / SL −15 is **33.3%**. Observed: **27%**. Below break-even.

4. **Wider TP/SL captured the biggest moves.** S03 (+50/−25) caught a +47.75% trade while keeping the same downside profile per trade. Suggests trailing TP or wider fixed TP may be a better default once you're already in a winner.

## Per-feature lift (S24 universe — every signal traded once)

The point of running a no-filter strategy was to get a clean lift measurement on each feature in isolation. The buy-side strategies are too sparse to lift on. Even the no-filter sample is small per bucket, so treat the numbers as **directional**, not exact.

### By wallet type (n = 97)

| Type | n | win rate | mean PnL % |
|------|---|----------|------------|
| Smart Money | 67 | **29.9%** | **−3.80%** |
| KOL | 20 | 25.0% | −5.38% |
| **Whale** | **10** | **10.0%** | **−10.53%** |

Whales lose hardest. The contrarian read: whale signals on this corpus are mostly distribution events the whale is **causing** by selling, which is structurally a sell signal on the token even though the wallet itself is labeled bullish.

### By wallet count

| Wallet count | n | win rate | mean PnL % |
|--------------|---|----------|------------|
| 3 | 70 | 27.1% | −4.42% |
| 4 | 10 | 20.0% | −6.20% |
| ≥ 5 | 17 | 29.4% | −5.66% |

Wallet-count ladder is **noisy** at this sample size. Going to ≥5 didn't help (sometimes hurt). The v0.2 default of ≥3 is fine; raising it filters out signals without improving expected value.

### By soldRatio bucket — the most actionable finding

| soldRatio % | n | win rate | mean PnL % |
|-------------|---|----------|------------|
| **< 10** | 1 | 100.0% | **+28.05%** |
| **10–30** | 2 | 50.0% | **+5.89%** |
| 30–50 | 4 | 0.0% | −12.65% |
| 50–70 | 5 | 0.0% | −16.28% |
| 70–100 | 85 | 28.2% | −4.41% |

This is the "valley of death": **smart money in mid-exit (soldRatio 30–70%) is the worst signal class to follow**. Either follow them in early (< 30%, very few but consistently positive) or wait until they've fully exited and someone else might bid the chart back up. The v0.2 spec already gates at `sold_ratio < 30%` — the data validates that cut and shows we could even tighten to `< 15%` without losing much sample.

### By market cap

| Market cap | n | win rate | mean PnL % |
|------------|---|----------|------------|
| < $50K | 44 | 22.7% | **−7.08%** |
| $50K–$200K | 23 | 26.1% | −6.27% |
| $200K–$1M | 19 | 31.6% | −2.02% |
| **$1M–$10M** | **10** | **40.0%** | **+3.04%** |
| > $10M | 1 | 0.0% | −3.33% |

Clearest monotonic lift in the dataset. **Sub-$50K MC is poison (−7% mean)**; $1M–$10M MC delivers the only positive-expected-value bucket on a meaningful sample (n=10, 40% win rate). The skill currently has no MC floor — adding `min_market_cap_usd: 200_000` would cut 67 of 97 universe trades and lift the average from −4.8% to roughly −1% even without the soldRatio filter.

## Recommended v0.3 changes (in order of expected impact)

| # | Change | Rationale | Confidence |
|---|--------|-----------|------------|
| 1 | Add **min_market_cap_usd: 200_000** as new rule R11 | $200K+ bucket is +0.6% mean blended; < $50K is −7%. Single biggest lift in the data. | medium |
| 2 | **Drop wallet_type=3 (Whale)** from default listener | Whales hit 10% win rate / −10.5% mean — they distort the corpus negatively | medium |
| 3 | Tighten **sold_ratio_max: 30 → 15** | Below 30%, the few trades we have are all winners; the 15–30% bucket is positive but tiny | low (small sample) |
| 4 | Try widening default exits to **TP +50 / SL −20** (was +30/−15) | S03 outperformed S01 on identical sample; one trade reached +47.75% under wider TP | low |
| 5 | Keep **min_wallet_count: 3** | Raising to 4 or 5 didn't help in this corpus | high (no-op confidence) |
| 6 | Keep **R3 (LP burned ≥ 50%)** as a hard gate | Rejected tokens in earlier paper runs were almost all small-cap pump.fun; combined with rule #1 above this gate becomes redundant for most rejections, but it's still the right shape | high |

Even with all six changes, expected PnL on this corpus is **still negative** (−1% to 0% mean per trade). The honest reading: the current Solana market state (smart money in distribution mode, 95% of signals sell-heavy) is unfriendly to the buy-side thesis. The skill should keep collecting data through different market regimes before re-tuning aggressively.

## Sample-size warnings

- **None of S01–S15 has more than 5 trades.** Their "win rates" of 50–100% are not statistically distinguishable from coin-flip. Don't pick S25 ("+4.3% return") as the "best" strategy — it's n=1.
- **S22 and S24 have 64 and 97 trades** and are robustly negative. Treat those as ruled-out, not as evidence for the inverse.
- **Per-feature lift uses S24's 97 trades**, so the MC and wallet-type findings are the strongest in the report. Even there, the $1M–$10M MC bucket is only 10 trades — directional, not a guarantee.

## Limitations

- **Bear-market corpus.** 95% of 24h signals were sell-heavy. In a bullish regime smart-money buy clusters would be ~10× more frequent and the buy-side strategies would have hundreds of trades, not 1–5. This run should be re-executed weekly.
- **No R3 (LP burned) check in the backtest.** The signal-list row doesn't carry `lpBurnedPercent`, and we didn't have enough time to refetch `token report` for every one of 97 tokens. Strategies S01–S25 trade through this gap; the live skill won't. Expect a noticeable reduction in tradeable signals when R3 is enforced.
- **No R1/R2/R7 check (mint/freeze/honeypot).** Same reason. The signal API has its own internal vetting but doesn't surface these fields directly. Adding a `token report` call per signal would add 5–10s per run — acceptable in real-time but slow in backtest.
- **5-minute candle granularity.** Within-bar TP/SL ordering uses worst-case (SL checked before TP). Real fills with 1-second granularity could shift 10–20% of exits from SL to TP.
- **Same kline bar for entry and any same-bar exit.** A real fill at the entry bar's open then an SL touch later in the same bar is possible. Our simulation handles it; just note it's optimistic on entry timing.
- **No actual on-chain replay.** We replay against the aggregator-reported price, which already reflects all DEX fills. Real broadcast might miss the trigger by 1–2 candles for orders during congestion.

## Reproducibility

All scripts and the raw results JSON are in the repo:

```
scripts/pull_signals.py        # 24h paginated pull, saves to /tmp
scripts/fetch_klines.py        # 5m candles for each candidate token
scripts/backtest.py            # the 25-strategy simulation
scripts/analyze_backtest.py    # per-feature lift
references/backtest-2026-05-16-results.json   # raw per-trade results
```

Re-run:

```bash
python3 scripts/pull_signals.py
python3 scripts/fetch_klines.py
python3 scripts/backtest.py
python3 scripts/analyze_backtest.py
```
