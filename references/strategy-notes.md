# Strategy Notes — Distilled from Open-Source Solana Trading Bots

Compiled 2026-05-16 for the OKX Agentic Trading Contest (ends 2026-05-21). Sources cited at the end.

## 1. Architectural pattern that wins evaluation

Every credible open-source bot we surveyed (`warp-id/solana-trading-bot`, `AnyxLabs/Solana-Copy-Trading-Sniper-Bot`, `mkdir700/solana-smart-trader`, `Immutal0/Solana-CopyTrading-Bot`) shares the same five-module separation. The skill mirrors it so judges see a recognizable shape:

| Module | Responsibility | Our mapping |
|---|---|---|
| **Listener** | Watch external feed (new pool, smart-money tx, KOL alert) | `okx-dex-signal` — aggregated smart-money / KOL signals |
| **Filter** | Reject the token if it fails safety / liquidity / age rules | `okx-security` + local rule set (see §3) |
| **Sizer** | Decide position size from bankroll + conviction | Local Kelly-bounded rule (see §4) |
| **Executor** | Place market or limit order; record txHash | `okx-dex-swap` (market) or `okx-dex-strategy` (TP/SL) |
| **Monitor** | Track open positions, fire TP/SL, log outcome | `okx-wallet-portfolio` + JSONL log |

Each module is invoked sequentially; failures short-circuit. The shape is what scores under "strategy completeness" + "execution reliability".

## 2. The signal we trust

Three classes of signal in the open-source world, ranked by edge:

1. **Smart-money cluster buys** — when N ≥ 3 wallets from a curated smart-money set buy the same token within a short window. Highest precision. **Use this.**
2. **KOL alpha calls** — one trusted wallet enters; lower precision, higher latency. Use as a secondary filter only.
3. **New-pool sniping** — buy any new Raydium/PumpFun pool that passes filters. Highest volume, lowest precision, dominated by professional sniper bots with sub-100ms infrastructure. **Skip — we cannot win on latency.**

OKX's `okx-dex-signal` aggregates (1) and (2) and returns ranked tokens by smart-money buy intensity. That is exactly the listener input we need.

## 3. Risk filter rule set — distilled from rugcheck patterns + BarryGuard 7-red-flag checklist

Token passes filter only if **all** of the following hold. Encode as a single function returning `(ok: bool, failedRule: str | None)`:

| # | Rule | Threshold | Why |
|---|---|---|---|
| R1 | Mint authority | **must be revoked / null** | Creator can otherwise mint infinite supply |
| R2 | Freeze authority | **must be revoked / null** | Creator can otherwise freeze your wallet → honeypot |
| R3 | LP status | **locked ≥ 30 days OR burned** | Otherwise creator can rug the pool |
| R4 | Top-1 holder share | **< 20%** of supply (excluding the LP address itself) | Concentration → dump risk |
| R5 | Top-10 holder share | **< 50%** of supply (excluding LP) | Cartel control |
| R6 | Insider funding pattern | **no ≥ 5 top holders sharing same funder** | Bundled launch |
| R7 | Honeypot / sellability | **simulated sell must succeed with < 50% price impact** | The whole point |
| R8 | Token age | **≥ 30 minutes** at first sight | Filter the riskiest first-block snipes |
| R9 | Holder count | **≥ 50 unique holders** | Floor against bot-only launches |
| R10 | Liquidity floor | **pool ≥ $20K USD equivalent** | Below this, even a $50 trade moves 5%+ |

For our contest scope (Solana + X Layer), `okx-security tx-scan` covers R1, R2, R7 directly. R3-R6, R8-R10 we compute from `okx-dex-token` / `okx-dex-trenches` token detail. Reject on first failure, log the rule that fired — judges value this kind of legible decision trail.

## 4. Position sizing

Kelly-criterion-bounded fractional. For each trade:

```
edge      = expected_win_prob * avg_win_pct - (1 - expected_win_prob) * avg_loss_pct
kelly     = edge / variance_of_outcome
position  = bankroll * min(kelly * 0.25, max_position_pct)
```

Hardcoded conservative defaults for v1 (no historical estimate yet):
- `expected_win_prob = 0.35` (35% — assumes smart-money signal gives meaningful edge on memes)
- `avg_win_pct       = 1.5`  (150% — meme winners 2-3x)
- `avg_loss_pct      = 0.5`  (50% — capped by stop loss)
- `max_position_pct  = 0.15` (cap any single trade at 15% of bankroll)

This yields ~9% bankroll per trade, capped at 15%. Conservative for memecoin land; survives 3-4 stop-outs.

For a 2-SOL ($172) bankroll: $15-26 per trade. Below the $1000 qualifying-volume threshold requires ~50-70 trades — implausible. So this v1 is a Skill-submission demo + small live verification, **not** a serious PnL-leaderboard bid.

## 5. Take-profit / stop-loss policy

Open-source convention is **fixed % TP/SL with time-out**. We adopt:

| Signal | TP | SL | Time-out |
|---|---|---|---|
| Smart-money cluster buy (≥3 wallets) | +30% | -15% | 4 hours |
| Single high-conviction KOL | +50% | -20% | 8 hours |

Implementation: at entry, fire two `okx-dex-strategy create-limit` orders — one TP sell at +X%, one SL sell at -Y%. The first to trigger cancels the other in `monitor` step. Time-out closes the position at market if neither fires.

## 6. Observability — what to log per trade

JSONL line per decision event, written to `~/.agentic-sniper/trades.jsonl`. Fields:

```json
{
  "ts": "ISO-8601",
  "event": "signal_received | filter_passed | filter_rejected | position_opened | tp_fired | sl_fired | timeout_close",
  "token": {"address": "...", "symbol": "...", "chain": "solana|xlayer"},
  "signal": {"source": "smart_money_cluster", "wallet_count": 3, "intensity_rank": 7},
  "filter": {"passed": true, "rules_checked": [...], "failed_rule": null},
  "trade": {"side": "buy|sell", "size_usd": 17.2, "price": 0.000123, "tx_hash": "..."},
  "pnl": {"realized_usd": 4.5, "pct": 0.26}
}
```

Plus a per-run summary at exit: total trades, win rate, gross PnL, mean PnL per trade, top filter-rejection reason. This is the artifact judges read — make it readable.

## 7. Safety onboarding

First-run interactive flow (skill must walk the user through):

1. Run `onchainos wallet status` — refuse to start if not logged in.
2. Show current balance and warn if `usdValue < $200` (sub-threshold for serious play).
3. Force the user to set a daily transfer / trade limit at the OKX policy URL **before** the first live trade.
4. Print explicit disclaimer; require typed confirmation (`I understand`) before the first non-dry-run.
5. Default mode is `--dry-run`; live trading requires explicit `--live` flag.

This is the "user safety onboarding experience" line item in the contest rubric.

## 8. What we deliberately do NOT do (scope cuts)

- **No new-pool first-block sniping.** Latency loss to pro infra.
- **No multi-DEX routing.** OKX aggregator already handles it.
- **No own RPC pool / Jito bundle path.** Out of scope.
- **No backtesting harness.** Not enough historical data in 5 days.
- **No ML / training.** Hand-tuned thresholds are easier to justify and audit.

State these in the README so judges know it is principled scoping, not omission.

## Sources

- [warp-id/solana-trading-bot](https://github.com/warp-id/solana-trading-bot) — architecture reference (listeners / filters / transactions / cache separation)
- [AnyxLabs/Solana-Copy-Trading-Sniper-Bot](https://github.com/AnyxLabs/Solana-Copy-Trading-Sniper-Bot) — smart-money mirror pattern with TP/SL
- [mkdir700/solana-smart-trader](https://github.com/mkdir700/solana-smart-trader) — real-time smart-money tracker
- [Immutal0/Solana-CopyTrading-Bot](https://github.com/Immutal0/Solana-CopyTrading-Bot) — multi-DEX execution pattern
- [BarryGuard — 7 Solana rug-pull red flags (2026)](https://www.barryguard.com/blog/how-to-check-solana-token-rug-pull) — risk-filter source
- [StakePoint Solana token safety scanner](https://stakepoint.app/blog/solana-token-safety-scanner) — risk scoring reference
- [Helius — Mint, Freeze, Update Authority docs](https://www.helius.dev/docs/orb/explore-authorities) — authority semantics
