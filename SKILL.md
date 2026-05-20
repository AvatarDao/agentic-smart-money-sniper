---
name: agentic-smart-money-sniper
description: "Smart-money copy-trading skill for OKX Agentic Wallet on Solana and X Layer. Listens to smart-money / KOL cluster-buy signals via `okx-dex-signal`, runs a 10-rule safety filter (`okx-security` + on-chain checks), sizes positions with Kelly-bounded fractional rule, then opens positions in one of three modes: **paper** (default — virtual fills using real spot prices, no broadcast), **shadow** (signals + filter only, no fills), or **live** (real trades via `okx-dex-swap` + `okx-dex-strategy` TP/SL, gated by typed risk acknowledgement). Every event is appended to a JSONL journal with full signal-feature snapshot so the corpus can be replayed against historical prices for backtest and parameter calibration. Designed for the OKX Agentic Trading Contest. Triggers: 'run sniper', 'scan smart money', 'sniper paper', 'sniper shadow', 'sniper live', 'sniper positions', 'sniper journal', 'sniper backtest', 'configure sniper'."
license: MIT
metadata:
  author: AvatarDao
  version: "0.4.0"
  homepage: "https://github.com/AvatarDao/agentic-smart-money-sniper"
---

# Agentic Smart-Money Sniper

A composable trading skill for OKX Agentic Wallet. It does **one** thing well: when curated smart-money wallets collectively buy a Solana or X Layer token that passes a hard safety filter, open a small, stop-loss-protected position — by default *on paper*, with real broadcast gated behind explicit consent — and log every decision plus the input signal features so the corpus can be replayed later.

The skill does not invent new primitives — it composes `okx-dex-signal`, `okx-security`, `okx-dex-swap`, `okx-dex-strategy`, and `okx-wallet-portfolio` into a coherent policy. Judges and operators read this single file to understand the entire decision tree.

## Pre-flight

Read `../okx-agentic-wallet/_shared/preflight.md` and ensure the user is logged in (`onchainos wallet status` → `loggedIn: true`) before any other step. Refuse to proceed if not. (Shadow mode also requires login because the signal API is authenticated.)

## Execution Modes

The skill ships with three modes. Mode determines what the Executor and Monitor modules actually do — Listener / Filter / Sizer behave identically in all three so the dataset is comparable across modes.

| Mode | Executor | Monitor | Capital at risk | Default? | Gate |
|---|---|---|---|---|---|
| `shadow` | no-op | no-op | none | no | none |
| `paper` | record virtual fill at spot price + simulated slippage | poll spot price every 5 min, fire virtual TP/SL or timeout | none | **yes** | none |
| `live` | real `swap execute` + 2× `strategy create-limit` | actual on-chain TP/SL settlement; OCO via `strategy cancel` | real | no | typed `I understand` once per 30 days |

The mode is recorded on every journal event as `"mode": "paper" | "shadow" | "live"`. Backtest and calibration are computed on paper + live events combined; shadow events are excluded (no fill data).

**Why paper is the default in v0.2** — the v0.1 run on 2026-05-16 surfaced that a 10% TP/SL slippage budget is wasteful for small ($15) positions against deep ($118K) liquidity. Rather than retune slippage in the dark, v0.2 collects a corpus first and re-tunes against measured fill quality.

## Five-module pipeline (canonical)

Every run executes these in order. A failure at any module short-circuits the trade and writes a `filter_rejected` or `error` event to the journal.

```
[ LISTENER ] --(token candidates)--> [ FILTER ] --(passing tokens)--> [ SIZER ] --(USD size)--> [ EXECUTOR ] --(virtual or real fill)--> [ MONITOR ]
```

| Module | Implementation | Output |
|---|---|---|
| Listener | `onchainos signal list --wallet-type 1,2 --chain solana --min-address-count 3 --min-liquidity-usd 50000 --limit 100` | ranked token candidates with smart-money / KOL buy intensity (whale signals dropped in v0.3 — see below) |
| Filter (soldRatio gate) | reject any signal with `soldRatioPercent > 15` | strictly buy-heavy signals (tightened from 30% in v0.3) |
| Filter (11 rules) | `onchainos token report` for each surviving candidate | `(passed: bool, failed_rule: str?)` |
| Sizer | Kelly-bounded fractional formula (see §Position Sizing) | size in USD, clamped to caps |
| Executor | mode-dependent — see §Execution Modes | entry record (virtual or real txHash) |
| Monitor | mode-dependent — see §Execution Modes | exit record + realized PnL |

Each step writes one JSONL event (see §Journal). The journal is the source of truth for performance review and backtest.

## Risk Filter (the 12 rules)

A token passes only if **all** 12 rules hold. Reject on first failure; record which rule fired. (The soldRatio gate is a separate, earlier check — it filters signal direction, not token safety.)

| # | Rule | Threshold | Source | Added |
|---|---|---|---|---|
| R1 | Mint authority revoked | `isMintable: false` | `token report.security` | v0.1 |
| R2 | Freeze authority revoked | `isHasFrozenAuth: false` | `token report.security` | v0.1 |
| R3 | LP locked or burned | LP burned ≥ 50% OR locked ≥ 30 days | `token report.advancedInfo.lpBurnedPercent` | v0.1 |
| R4 | Top-1 holder share (excl. LP) | < 20% of supply | `token report.advancedInfo` (use top10 / 10 as proxy if top1 absent) | v0.1 |
| R5 | Top-10 holder share (excl. LP) | < 50% of supply | `token report.advancedInfo.top10HoldPercent` | v0.1 |
| R6 | No insider bundling | `bundleHoldingPercent < 10` | `token report.advancedInfo.bundleHoldingPercent` | v0.1 |
| R7 | Sellable, low price impact | `isHoneypot: false`, quote price impact < 5% | `swap quote` | v0.2 (tightened) |
| R8 | Token age | ≥ 30 minutes from `createTime` | `token report.advancedInfo.createTime` | v0.1 |
| R9 | Holder count | ≥ 50 unique holders | `token report.priceInfo.holders` | v0.1 |
| R10 | Liquidity floor | pool ≥ $20,000 USD equivalent | `token report.priceInfo.liquidity` | v0.1 |
| R11 | Market cap floor | ≥ $200,000 USD | `token report.priceInfo.marketCap` or signal row `marketCapUsd` | v0.3 |
| **R12** | **Dev rug history** | **`devRugPullTokenCount == 0`** | **`token report.advancedInfo.devRugPullTokenCount`** | **v0.4** |

When the upstream skill cannot return a field, **default to fail** (`failed_rule = "R<N>_unknown"`). Do not approximate — judges will dock for silent passes on missing data.

**R11 rationale**: the v0.2.2 backtest (`references/backtest-2026-05-16-report.md`) showed a clear monotonic lift by market cap on a 97-trade sample. Sub-$50K MC delivered −7.08% mean per trade; $200K+ buckets blended to roughly break-even; the $1M–$10M bucket alone returned +3.04% mean (40% win rate, n=10). Adding R11 at $200K cuts out the worst 67 of 97 universal-strategy trades while preserving every trade in the meaningfully-positive bucket.

**R12 rationale**: live-fire validated on 2026-05-20. The v0.3.1 listener surfaced exactly **one** R1-through-R11-passing candidate (`HeavyPulp`, MC $472K, 6018 holders, LP burned 68%, bundle 1.58%, smart-money cluster buy). All 11 hard-coded rules were ✅. The token report also showed `devRugPullTokenCount: 105, devLaunchedTokenCount: 54, devCreateTokenCount: 11895, tokenTags: [devHoldingStatusSellAll, ...]` — a serial-rug deployer who had already cashed out of THIS token's launch tranche. v0.3 would have approved the trade. v0.4 rejects on R12. See `references/r12-live-rejection.md` for the full transcript and screenshots of the rejection. The threshold is hard zero — token-mill deployers operate at industrial scale; even one prior rug is sufficient evidence of intent, and the false-positive cost (skipping a few legitimate trades by clean-but-experienced devs) is acceptable next to the realized loss of trusting a serial-rug pull.

## Position Sizing

Kelly-bounded fractional. For each candidate:

```python
edge      = win_prob * avg_win_pct - (1 - win_prob) * avg_loss_pct
kelly_f   = max(0, edge / variance)
size_pct  = min(kelly_f * 0.25, max_position_pct)   # 25% Kelly fractional, capped
size_usd  = bankroll_usd * size_pct
```

v0.2 defaults (conservative — to be re-calibrated from the journal corpus after ~50 paper trades):

```yaml
win_prob:          0.35
avg_win_pct:       1.5
avg_loss_pct:      0.5
variance:          1.0
max_position_pct:  0.15   # never more than 15% of bankroll in one trade
min_position_usd:  5      # below this, gas/slippage dominates → skip
```

These yield ~9% of bankroll per trade, capped at 15%. Override via `~/.agentic-sniper/config.yaml`. **Calibration is a first-class loop** — see §Backtest & Calibration.

## TP / SL policy

| Signal type | TP | SL | Time-out close | Slippage (entry) | Slippage (exit) |
|---|---|---|---|---|---|
| Smart-money cluster buy (≥ 3 wallets) | **+50%** | **−20%** | **6 h** | 2% | 3% |
| KOL cluster buy (≥ 3 wallets) | **+50%** | **−20%** | **6 h** | 2% | 3% |
| Single high-conviction KOL | +50% | −20% | 8 h | 2% | 3% |

**v0.3 change**: widened the cluster-buy TP/SL from +30/-15 to +50/-20 and extended timeout from 4h to 6h. The v0.2.2 backtest showed that on the same set of buy-heavy signals, S03 (+50/-25) caught a +47.75% trade that S01 (+30/-15) gave up at +28%, with identical downside profile. The SL is loosened from −15% to −20% to reduce premature stop-outs caused by within-bar noise on 5m candles — 60% of trades in the universal sample stopped out on −15%, but several of those rebounded immediately. Re-evaluate after 30+ closed positions accumulate.

v0.2 tightened exit slippage from the v0.1 default of 10% to 3%, based on the 2026-05-16 demo run where actual market impact at $15 size was under 1% on $118K liquidity. If a paper-trade fill simulation shows fills outside this budget, the corpus will flag it and the config bumps for the affected signal class only.

**Live mode**: at entry, fire two limit orders **immediately** via `onchainos strategy create-limit` with `--slippage 3` and **`--expires-in 604800`** (7 days — the CLI default, but pass it explicitly so the order TTL outlives any plausible monitor downtime). Monitor module cancels the surviving limit order when the other fills (`onchainos strategy cancel`). Time-out triggers a market close via `onchainos swap execute --slippage 5` (slightly looser because the timeout fill is non-discretionary).

**`--expires-in` is the order TTL, separate from the skill's own `timeout_hours`.** The skill's timeout is when the monitor module decides to manually close at market; the CLI `--expires-in` is when the limit order self-destructs on the backend. The two must agree in shape: `--expires-in` should be **strictly greater than** `timeout_hours`, otherwise (as on the 2026-05-16 Wish trade) a 4h `--expires-in` against a 6h `timeout_hours` produces a 2-hour window where the position has no SL coverage at all. Use 7d as the safe default; the skill's own monitor handles earlier-than-TTL closes.

**Paper mode**: virtual TP/SL triggers are checked every 5 minutes against `onchainos token price-info`. When triggered, the journal records a virtual fill at `trigger_price * (1 ± simulated_slippage)`, where `simulated_slippage` is sampled from the empirical distribution of recent live fills on the same liquidity bucket (default 1.5% until enough data accumulates).

## Safety Onboarding

Live mode enforces this sequence. Refuse to proceed if any step is skipped.

1. `onchainos wallet status` → confirm logged-in account and total balance.
2. Refuse if balance < $50 — too low to overcome gas + slippage.
3. Warn if balance < $200 — print expected per-trade size and ask explicit confirmation.
4. Direct the user to set per-tx and daily limits at the OKX Policy URL (from `okx-agentic-wallet` user-facing templates) and confirm they did.
5. Print verbatim:
   > This skill opens real positions in volatile memecoin tokens on Solana and X Layer. Realized losses are possible and not refundable. Type "I understand" to proceed.
6. Wait for exact string `I understand`. Anything else aborts.
7. Persist consent timestamp to `~/.agentic-sniper/consent.json`; re-prompt every 30 days.

Paper and shadow modes skip steps 4–7 — no real funds at stake. They still require login (step 1).

## Commands the skill responds to

The skill is invoked through the agent in natural language. Canonical intents:

| User says (EN / ZH) | Action | Mode |
|---|---|---|
| "scan smart money signals" / "扫描聪明钱信号" | Listener only — print ranked candidates, do nothing | shadow |
| "sniper shadow" / "只看信号" | Full Listener + Filter, no Sizer/Executor | shadow |
| "run sniper" / "sniper paper" / "纸面跑一遍" | Full pipeline, virtual fills, journal written | paper (default) |
| "run sniper live" / "实盘跑一次" | Full pipeline, real trades — gated by onboarding | live |
| "show sniper positions" / "看持仓" | `strategy list` + `wallet history` for the account, plus virtual positions from journal | any |
| "show sniper journal" / "看交易日志" | Tail `~/.agentic-sniper/trades.jsonl`, render last 20 events | any |
| "sniper backtest" / "回测" | Replay journal against `token candles`, print parameter sensitivity | any |
| "configure sniper" / "改配置" | Show `~/.agentic-sniper/config.yaml` and offer edits | any |

Paper is the default. Live mode requires either a typed `--live` token in the prompt **and** a valid (< 30 d old) consent stamp, or a fresh interactive `I understand` confirmation in the current session.

## Journal Format

One JSON object per line at `~/.agentic-sniper/trades.jsonl`. Schema is stable across modes — same fields, just different `mode` value and (for paper) virtual identifiers in place of on-chain hashes.

```json
{
  "ts": "2026-05-17T03:14:22Z",
  "mode": "paper | shadow | live",
  "event": "signal_received | filter_rejected | filter_passed | size_decided | position_opened | tp_set | sl_set | tp_fired | sl_fired | timeout_close | error | run_summary",
  "run_id": "uuid-v4 — same id across all events of one pipeline run",
  "token": {"chain": "solana", "address": "...", "symbol": "..."},
  "signal": {
    "source": "smart_money_cluster | kol_solo | whale",
    "wallet_type": "1 | 2 | 3",
    "wallet_count": 4,
    "sold_ratio_pct": 0.77,
    "amount_usd": 4135,
    "market_cap_usd": 445682,
    "holders": 3645,
    "top10_pct": 21.16,
    "liquidity_usd": 118549,
    "price_change_1h_pct": -13.3,
    "price_change_24h_pct": 37.09,
    "raw": "<verbatim signal-list row>"
  },
  "filter": {"passed": true, "rules_checked": ["R1",...], "failed_rule": null, "risk_level": "LOW"},
  "trade": {"side": "buy|sell", "size_usd": 15.5, "price": 0.000441, "tx_hash": "...", "slippage_realized_pct": 0.92},
  "pnl": {"realized_usd": 4.5, "pct": 0.26}
}
```

**Required for every event**: `ts`, `mode`, `event`, `run_id`. The full `signal` block is required on `signal_received` and **carried forward** unchanged on every subsequent event for the same `run_id` — this gives every closed position a complete feature snapshot of why it was opened, which is what makes the corpus usable for calibration.

After each run, append a summary line with `"event": "run_summary"` containing `total_trades`, `win_rate`, `gross_pnl_usd`, `mean_pnl_pct`, `top_reject_rule`, `mean_realized_slippage_pct`.

## Data Accumulation

The journal is not just a log — it is the **training set**. Discipline:

1. **Capture before deciding.** `signal_received` must record all upstream signal fields verbatim under `signal.raw`, plus the derived features used by the filter. If a feature was unavailable, store `null` — never silently default.
2. **Carry the feature snapshot forward.** Every later event for the same `run_id` keeps the same signal block so a single line tells the full story when grepped by `run_id`.
3. **Run paper continuously.** Even after live mode launches, default to paper for any signal that doesn't clear an additional confidence threshold. The paper corpus is the larger sample.
4. **Don't prune.** Keep all events including `filter_rejected`. Rejected-token outcomes (did the token rug? did it moon?) are what teaches the filter.
5. **Tag schema changes.** When this skill bumps version, every journal event after the bump includes `"skill_version": "0.2.0"` so backtests can segment.

## Backtest & Calibration

`sniper backtest` reads the journal and a price-series source (`onchainos token price-info` history endpoint, or candles from `okx-dex-market`) and produces:

- **Hypothetical PnL per run** — re-simulate every paper position with the *current* config and report the delta from the original simulation. Detects whether config drift would improve or degrade past trades.
- **Parameter sensitivity table** — sweep `tp_pct`, `sl_pct`, `min_wallet_count`, soldRatio gate threshold; print the grid of resulting win rate, mean PnL, and Sharpe-equivalent for the journal corpus.
- **Per-feature lift** — for each signal feature (wallet_count, soldRatio, marketCap bucket, etc.), the conditional win rate vs. the corpus average. Surfaces what features actually predict winners.

Calibration loop (run weekly, or after every 50 closed positions):

1. Run backtest on the latest journal snapshot.
2. If a parameter change improves median PnL on > 70% of bootstrap resamples, propose it to the user in a diff.
3. User approves → write to `config.yaml`, version-bump in journal, continue.

The backtest harness itself is a Python script under `scripts/backtest.py` (added in v0.3 — v0.2 ships only the spec and example output in `references/backtest.md`).

## Out of scope (deliberate)

State plainly in the README and refuse if the user asks:

- New-pool first-block sniping (latency-dominated, retail loses).
- Multi-DEX manual routing (OKX aggregator already does this).
- Own RPC pool / Jito bundle path (infra cost, no edge for our size).
- ML signals / online training pipelines (not testable inside the contest window — but the journal IS the data layer for whatever ML comes later).
- Trades on non-Solana, non-X-Layer chains (the contest does not credit them).

## Failure Modes

| Failure | Skill response |
|---|---|
| `signal list` returns empty | print "no qualifying signals in window", exit clean — no error |
| `signal list` returns only sell-heavy (all soldRatio > 30%) | log `filter_rejected_all` summary, exit clean |
| `token report` times out (> 5s) | retry once with 10s budget; if still timing out, treat as R1/R2/R7 unknown → reject |
| `swap execute` returns simulation failure (live mode) | log error event with `executeErrorMsg`, do NOT broadcast |
| `strategy create-limit` for TP succeeds but SL fails (live mode) | cancel TP immediately, market-close the position, log error |
| Paper-mode price poll fails | back-off retry every 60s; positions stay open until next successful poll or timeout |
| Network error during monitor | back-off retry every 60s; alert user only after 3 consecutive failures |
| Journal write fails | abort the run — never silently lose a decision event |

## Configuration (`~/.agentic-sniper/config.yaml`)

```yaml
mode: paper                              # paper | shadow | live
chains: [solana, xlayer]
listener:
  window_minutes: 30
  min_wallet_count: 3
  min_liquidity_usd: 50000               # API-level filter, before our R10
  max_sold_ratio_pct: 15                 # v0.3: tightened from 30 to 15 based on backtest lift
  wallet_types: [1, 2]                   # v0.3: dropped whales (3) — 10% win rate / -10.5% mean
filter:
  min_holders: 50                        # R9
  min_liquidity_usd: 20000               # R10
  min_market_cap_usd: 200000             # R11
  max_top1_pct: 0.20                     # R4
  max_top10_pct: 0.50                    # R5
  max_bundle_holding_pct: 0.10           # R6
  min_token_age_minutes: 30              # R8
  min_lp_burned_pct: 50                  # R3
  max_price_impact_pct: 5                # R7
  max_dev_rug_count: 0                   # R12 (v0.4, new) — strict zero
regime:                                  # v0.4 — observed only, no automatic action yet
  track: true                            # at every listener run, log the % of signals with sold>50%
  field: signal_regime_pct               # written to journal `regime.buy_heavy_pct` / `regime.sell_heavy_pct`
  hot_threshold: 25                      # buy_heavy_pct > 25 → "bullish-leaning regime"
  cold_threshold: 5                      # buy_heavy_pct < 5  → "distribution-mode regime" (current state as of 5/20)
sizing:
  win_prob: 0.35
  avg_win_pct: 1.5
  avg_loss_pct: 0.5
  variance: 1.0
  kelly_fraction: 0.25
  max_position_pct: 0.15
  min_position_usd: 5
exits:
  cluster_buy: {tp_pct: 0.50, sl_pct: -0.20, timeout_hours: 6, slippage_entry: 2, slippage_exit: 3}
  kol_solo:    {tp_pct: 0.50, sl_pct: -0.20, timeout_hours: 8, slippage_entry: 2, slippage_exit: 3}
paper:
  poll_interval_minutes: 5
  default_simulated_slippage_pct: 1.5    # used until live corpus replaces it
backtest:
  schedule: "daily 04:00 local"          # v0.3: launchd job
  archive_dir: "~/.agentic-sniper/backtest/"
```

Override any value in this file; missing keys fall back to v0.3 defaults shown above. Config edits are journaled as a `config_changed` event so backtests can segment by config epoch.

## Disclaimer

This skill operates a self-custody wallet on a public blockchain. All trades in live mode are irreversible. The author makes no guarantee of profitability and disclaims liability for losses, slippage, gas costs, or third-party DEX failures. Paper mode runs no broadcasts and risks no capital. Use live mode only with funds you can afford to lose.
