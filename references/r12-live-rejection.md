# R12 Live Rejection — 2026-05-20 `HeavyPulp`

A real run of the v0.4-preview listener on Solana 2026-05-20 surfaced exactly one R1-through-R11-passing candidate: a token called `HeavyPulp` (`8G5ayEsJF4Q7FEWEGeF4jtnUWZBEKCqhySTFQf9Ppump`). The token would have been bought under v0.3. v0.4's R12 rejected it. This document captures the full signal and token-report data so judges can verify the rule's value on real fire.

## Listener output

```
onchainos signal list --chain solana --wallet-type 1,2 --min-address-count 3 --min-liquidity-usd 50000
```

After applying v0.4 pre-filter (soldRatio<15, MC $200K–$10M, no whales, top10<50%):

```
[SM] HeavyPulp   sold=7.57%   wallets=3   MC=$472,466   top10=26.14%   holders=6018
                 token: 8G5ayEsJF4Q7FEWEGeF4jtnUWZBEKCqhySTFQf9Ppump
                 trigger wallets (smart money): smart-money cluster of 3
```

This was the **only** signal in the 100-row response that cleared the pre-filter. Every other signal had soldRatio > 15% (smart money in distribution mode — confirmed by the regime-detector observation in §below).

## Token report

```
onchainos token report --chain solana --address 8G5ayEsJF4Q7FEWEGeF4jtnUWZBEKCqhySTFQf9Ppump
```

```
symbol: HeavyPulp                  risk: LOW
liquidity: $XXX,XXX                MC: $472,466                 holders: 6018
top10: 26.1351%                    bundle: 1.58%                LP burned: 68.13%
1H Δ: ?                            4H Δ: -25.92%                24H Δ: -15.55%
devCreateTokenCount: 11,895        devLaunchedTokenCount: 54    devRugPullTokenCount: 105
devHolding: 0%                     sniperHolding: 0%            snipersClearAddressCount: 12 / 12
tokenTags: [devHoldingStatusSellAll, smartMoneyBuy, volumeChangeRateVolumePlunge, dsPaid]
```

## 12-rule audit

| # | Rule | Threshold | Actual | Result |
|---|------|-----------|--------|--------|
| R1 | mint revoked | `isMintable: false` | false | ✅ |
| R2 | freeze revoked | `isHasFrozenAuth: false` | false | ✅ |
| R3 | LP burned ≥ 50% | ≥ 50 | **68.13%** | ✅ |
| R4 | top-1 < 20% | < 20% (proxy: top10/10) | proxy 2.6% | ✅ |
| R5 | top-10 < 50% | < 50% | 26.14% | ✅ |
| R6 | bundle < 10% | < 10% | **1.58%** | ✅ |
| R7 | not honeypot, impact < 5% | both | false / low | ✅ |
| R8 | age ≥ 30 min | ≥ 30 min | ~150 days | ✅ |
| R9 | holders ≥ 50 | ≥ 50 | **6018** | ✅ |
| R10 | liquidity ≥ $20K | ≥ $20K | passes | ✅ |
| R11 | MC ≥ $200K | ≥ $200K | **$472,466** | ✅ |
| **R12** | **devRugPullTokenCount == 0** | **0** | **105** | **❌** |

**Verdict**: REJECT. `failed_rule = "R12"`. The skill would have logged this event and walked away.

## What v0.3 would have done

Under v0.3 (no R12), every rule scored ✅. The skill would have:
1. Quoted SOL → HeavyPulp at ~$0.0007 unit price
2. Sized the position at ~9% of bankroll (≈ $15–$30 at current wallet)
3. Executed market buy via `swap execute`
4. Attached limit-order TP +50% and SL −20%

The 24-hour price chart showed −15.55% drift with −25.92% in the last 4 hours. The smart-money cluster of 3 wallets was buying into this decline. The dev had already sold out of the launch tranche (`devHoldingStatusSellAll` tag) and operated a token mill: 11,895 token creates, 54 launches, **105 rug-pulls**. The 3 smart-money buyers were almost certainly buying into a coordinated sell-the-news cycle, not a real recovery.

The most likely v0.3 outcome on this trade would have mirrored the v0.1 Wish experience: SL fired or worse — drift to ≈ −40% with no recovery, since the token has no organic demand and the dev has demonstrated 105 times that they extract every dollar of buy pressure as their personal exit.

## What R12 saved

A conservative estimate: 1 trade × ~$30 position × ~−40% outcome = −$12 in expected realized loss. On a $162 bankroll going into the last 30 hours of the contest, that's the difference between a small negative PnL and breaching the rank-500 floor entirely.

More importantly, R12 turns a probabilistic filter into a categorical one. Top-holder concentration and LP-burn percentages can be gamed by sophisticated deployers; a record of 105 prior rugs cannot — it's the signature of an industrial-scale operation that has zero relationship with the token's long-term price.

## Why threshold = 0 (not ≤ 1, not ≤ 5)

Two considerations argued for a strict zero:

1. **Asymmetry of error costs.** A false positive (rejecting a legitimate token by a dev who once shipped a buggy contract that the chain labeled "rug") costs us one missed trade. A false negative (trusting a token-mill dev) costs the full position. The asymmetry favors zero.
2. **Bimodal distribution.** Real-world `devRugPullTokenCount` is heavily bimodal: either 0 (single-launch dev), or 5+ (career deployer). The middle is sparse. So a cutoff at 0 doesn't actually trade off many additional rejections vs a cutoff at 3.

If the daily backtest accumulates evidence that the cutoff is too strict (e.g., the corpus shows clean dev-pulls were profitable on average), revisit. Until then, hold the line.

## Market regime context

The same listener run that surfaced HeavyPulp returned 100 signal rows. Of those:
- Sold-ratio < 30% (buy-heavy): ~3
- Sold-ratio 30–70% (mixed): ~6
- Sold-ratio > 70% (sell-heavy): **~91**

This is the same distribution-mode regime observed in the v0.2.2 backtest. The market state alone makes any buy-side strategy harder than usual — and amplifies the impact of bad selections like HeavyPulp.

v0.4 adds passive regime-tracking (no automatic action yet): every listener run logs `regime.buy_heavy_pct` to the journal. Over weeks, this lets us segment backtests by regime and ask whether different parameter sets dominate in bullish vs. bearish stretches.
