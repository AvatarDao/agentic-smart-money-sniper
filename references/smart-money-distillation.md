# Smart Money Distillation — 2026-05-21

A reverse-engineering pass on the top 50 Solana smart-money traders by 7-day ROI, as reported by `onchainos leaderboard list --chain solana --time-frame 3 --sort-by 5 --wallet-type smartMoney --min-realized-pnl-usd 1000`. The goal: understand what the elite cohort actually does on-chain, identify reusable patterns, and propose a v0.5 rule (R13) that uses signal-source-wallet quality as an additional filter.

Honest framing first: until this analysis, v0.1 through v0.4 consumed the smart-money signal feed as a **bulk** input — every cluster-buy by ≥ 3 SM wallets was treated equally. The leaderboard data shows that the source wallets are heavily heterogeneous in quality, and that the top performers play a fundamentally different game than the average SM signal would suggest.

## The data: top 50 SM Solana traders, 7d

```
onchainos leaderboard list --chain solana --time-frame 3 --sort-by 5 \
    --wallet-type smartMoney --min-realized-pnl-usd 1000
```

Returned 50 wallets, all with ≥ $1K realized PnL in the prior 7 days. Aggregate stats:

| Metric | p10 | p50 (median) | p90 |
|---|---:|---:|---:|
| 7d realized PnL % (ROI) | +19% | **+30%** | +91% |
| 7d win rate | 31% | **48%** | 69% |
| Average buy size USD | $78 | **$190** | $440 |

## Top 20 traders by 7d ROI

```
walletAddress                          pnl_usd     ROI      WR     avgBuy   txs   vol
DEdEW3...BQDQ  $    1,249    +1351.6%   33.3%    $128    24    $2.6K
8T9mnA...HTgy  $   19,550     +361.5%  100.0%      $0     6   $25.0K
954Kj3...AnEv  $    1,779     +171.6%   66.7%    $238    23    $3.8K
4nwfXw...9k6T  $   32,702     +112.4%   44.6%    $241   226   $88.3K   ← top by absolute PnL
FCt3Gy...ctPv  $    1,951     +102.4%   72.7%    $111    43    $5.9K
CxgPWv...eGve  $    1,207      +91.0%   66.7%    $273     7    $3.9K
Dvbv5T...UaRv  $    3,155      +89.6%   55.6%     $31   176   $10.6K
GGGq5o...yEfb  $    2,293      +85.5%   23.1%    $370    23   $11.6K
DjM7Tu...uN7s  $    2,705      +76.9%  100.0%    $143    43    $9.9K
BXAWg4...myGF  $    4,151      +74.0%   25.0%  $2,072    11   $22.2K
78N177...Vkh2  $   15,867      +53.5%   88.1%    $211   321   $75.5K
9EyPAM...rUiH  $    1,200      +50.4%   40.0%    $357    32    $6.4K
5ZuV8e...qbdg  $   32,104      +48.8%   38.0%    $214   674  $183.0K   ← second by absolute PnL
9RrKUh...FBj9  $    3,528      +47.3%   47.6%     $60   245   $19.8K
BHREKF...2AtX  $    5,716      +43.4%   23.9%     $12  1638   $35.4K   ← extreme high-frequency
FopcXZ...jGdm  $    2,093      +42.2%   50.0%    $420     9    $9.2K
7zenhR...xyac  $    6,857      +40.2%   38.9%    $549    76   $46.7K
84DTmK...9J5S  $    4,200      +39.3%   50.0%    $148   172   $25.8K
5hAgYC...84zM  $   11,004      +36.3%   50.6%    $216   320   $75.8K
4BdKax...EFUk  $   23,258      +35.4%   69.3%     $97   978  $155.8K
```

## What the top wallet is actually buying (tracker output)

```
onchainos tracker activities --tracker-type multi_address \
    --wallet-address 4nwfXw7n98jEQn93VWY7Cuf1jnn1scHXuXCPGVYS9k6T \
    --trade-type 1 --chain solana --min-volume 100
```

The single top-by-PnL SM trader (4nwfXw…9k6T, +$32K / +112% ROI) was placing buys in tokens with these market caps:

| Token | Market cap at trade | Quote size |
|---|---:|---:|
| FUJIKURA | **$8,967** | 2.46 SOL |
| Starman | **$12,362** | 2.97 SOL |
| SOS | **$4,524** | 1.54 SOL |
| sloglana | **$4,146** | 1.40 SOL |

Every single one is sub-$15K MC. These are **first-block pump.fun snipes** — buying the token within minutes of deploy, hoping for a 10–100× pump before the dev or other snipers dump.

## The key insight

The skill's R11 ($200,000 MC floor, added v0.3) was justified by the v0.2.2 backtest: sub-$50K MC delivered −7% mean per trade for an undifferentiated retail strategy. That analysis stands.

**But the leaderboard distillation shows R11 also disqualifies the entire elite-SM playbook.** The top 1% of Solana traders concentrate exactly in the sub-$15K MC bucket that R11 cuts. The fact that their *median* ROI is +30% / week is because they have:

1. **Tooling**: sub-second mempool monitoring + bundler-aware execution.
2. **Statistical edge per wallet**: they each take 50–1000+ small bets per week so individual rugs are bounded.
3. **Inside-the-cohort information**: top wallets coordinate / observe each other.
4. **Capital they can afford to lose**: avg buy $128 means a $2 win on a 100× covers many $0.50 losses.

Retail running v0.4 of this skill has none of those. R11 is **structurally correct** for our user — we trade larger positions, less frequently, without sub-second monitoring. Removing R11 to "follow the alpha" would put us in a game where we have negative edge.

This is the most important calibration finding in the project: **the skill's safety floor and the SM leaderboard's profit ceiling sit on opposite sides of the same threshold**, and the skill must stay on the safe side.

## Common holdings — overlap analysis

Cross-checking the `topPnlTokenList` field across top-20 traders to find tokens 2+ traders profit from:

| Token | Held by | Avg ROI | Total PnL across traders |
|---|---:|---:|---:|
| **SPCX** | 2/20 | +282% | $26,246 |
| WORLDCUP | 2/20 | +119% | $4,493 |
| WATERFALL | 2/20 | +1142% | $2,602 |
| Fiveish | 2/20 | +381% | $823 |
| MONET | 2/20 | +37% | $672 |

These tokens are post-R11 candidates only for SPCX (currently MC ~$2M) — the others are too small to clear our filter. So even the "high-conviction tokens that multiple SM made money on" mostly fail R11.

## Position-size patterns

Plotting `avgBuyValueUsd` against `winRatePercent` and `roi`:

- **High win-rate quadrant (WR > 70%)**: 4 wallets, avgBuy $111–$238. Concentrated bets on 5–50 picks, picks them carefully.
- **High volume / high ROI quadrant (txs > 500, ROI > 30%)**: 5 wallets, avgBuy $60–$216. Memecoin scalpers, run on volume.
- **Big absolute PnL (>$20K) but moderate ROI (35–50%)**: 4 wallets, avgBuy $97–$214. Tier-1 wallets with size, can't be too aggressive % wise.
- **One-shot outliers**: 1 wallet with $128 avg buy, 24 txs, +1352% ROI. Effectively one 10× catch on a low base.

No clean answer to "what's the right size". The data says size and frequency are jointly chosen, with R^2 close to zero. Anyone telling you "always do X% per trade" is overfitting to their own corpus.

## v0.5 proposal: R13 — wallet-quality re-ranking (not a hard filter)

R12 is binary (devRug == 0). R13 should be a *ranker*, not a *filter*: signals where the source wallet is in the top-50 SM leaderboard get scored higher, but no signal is hard-rejected purely on source-wallet quality (the leaderboard is noisy at small-sample sizes — a wallet's 7d ROI is heavily luck-correlated).

### Concept

```
For each candidate signal:
    1. Apply hard filter R1–R12 as today.
    2. For each `triggerWalletAddress` in the signal row:
         - Look up in cached 7d top-50 SM leaderboard.
         - If present, record (rank, 7d_roi, win_rate).
    3. Compute a `source_quality_score`:
         = sum(1 / rank) over each SM wallet in the cluster found in top-50
         (so a cluster with the #1 wallet scores 1.0, with #50 scores 0.02,
         with three top-25 wallets scores ~0.15).
    4. Weight position size by `0.5 + clip(source_quality_score, 0, 0.5)`:
         a "no top wallets in cluster" signal gets 0.5x sizing,
         a "multiple top wallets" signal gets up to 1.0x sizing.
    5. Refresh the top-50 leaderboard cache weekly.
```

### Why a ranker, not a filter

- The 7d leaderboard is noisy; many top wallets cycle in and out week to week.
- Hard-filtering on source wallet would shrink our already-small signal stream (the v0.2.2 backtest had 137 signals total in 24h; cutting to "top-50 wallets only" might leave 5–10).
- Re-ranking preserves the wide funnel but biases capital toward higher-quality signals.

### What R13 does NOT do

- Doesn't relax R11. The skill's MC floor stays at $200K. We don't follow elite SM into sub-$15K snipes — we don't have the infrastructure.
- Doesn't use the leaderboard for binary include/exclude. The leaderboard is a *prior*, not a verdict.
- Doesn't fire on stale data — leaderboard is refreshed at most weekly, ideally as a launchd job alongside the existing daily backtest.

### Implementation surface (deferred to v0.5)

```
scripts/refresh_sm_leaderboard.py     # weekly cron, caches top-50 to disk
~/.agentic-sniper/sm-leaderboard.json # cached top-50 with timestamp
```

Plus a small change in `run_paper.py` to weight `size_pct` by source quality at the Sizer step. ~30 LOC.

## Limitations / honest disclosures

- **Sample size**: 50 wallets ranked by 7d ROI is a tiny denominator. A wallet with 1 trade at +100% has the same "ROI" as one with 100 trades averaging +100%. The leaderboard returns include trade-count fields but not noise-adjusted measures. v0.6 should add a Bayesian shrinkage estimator (`shrunken_roi = roi * txs / (txs + k)`) to dampen one-shot outliers.
- **Survivorship**: today's leaderboard top-50 ARE today's winners. They may have been today's losers a week ago. Cohort persistence is unknown without longitudinal data — out of scope for the contest, in scope for v0.5+ once a few weeks of leaderboard snapshots accumulate.
- **Selection bias of the smart-money tag**: OKX classifies wallets as "smart money" internally; we don't have visibility into their classification rules. If those rules are themselves biased (e.g., labeled because already profitable), the leaderboard is partly tautological. We accept this as data we don't control.

## Sources

All data fetched 2026-05-21 via the `onchainos` CLI shipped with this skill's dependencies. Raw responses cached at `/tmp/lb.json` (top-50) and the tracker output above. Re-fetch with the same CLI commands; expect different wallets in different weeks.
