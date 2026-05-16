---
name: agentic-smart-money-sniper
description: "Smart-money copy-trading skill for OKX Agentic Wallet on Solana and X Layer. Listens to smart-money / KOL cluster-buy signals via `okx-dex-signal`, runs a 10-rule safety filter (`okx-security` + on-chain checks), sizes positions with Kelly-bounded fractional rule, then opens positions in one of three modes: **paper** (default — virtual fills using real spot prices, no broadcast), **shadow** (signals + filter only, no fills), or **live** (real trades via `okx-dex-swap` + `okx-dex-strategy` TP/SL, gated by typed risk acknowledgement). Every event is appended to a JSONL journal with full signal-feature snapshot so the corpus can be replayed against historical prices for backtest and parameter calibration. Designed for the OKX Agentic Trading Contest. Triggers: 'run sniper', 'scan smart money', 'sniper paper', 'sniper shadow', 'sniper live', 'sniper positions', 'sniper journal', 'sniper backtest', 'configure sniper'."
license: MIT
metadata:
  author: AvatarDao
  version: "0.2.0"
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
| Listener | `onchainos signal list --wallet-type 1,2,3 --chain solana --min-address-count 3 --min-liquidity-usd 50000 --limit 100` | ranked token candidates with smart-money / KOL / whale buy intensity |
| Filter (soldRatio gate) | reject any signal with `soldRatioPercent > 30` | buy-heavy signals only |
| Filter (10 rules) | `onchainos token report` for each surviving candidate | `(passed: bool, failed_rule: str?)` |
| Sizer | Kelly-bounded fractional formula (see §Position Sizing) | size in USD, clamped to caps |
| Executor | mode-dependent — see §Execution Modes | entry record (virtual or real txHash) |
| Monitor | mode-dependent — see §Execution Modes | exit record + realized PnL |

Each step writes one JSONL event (see §Journal). The journal is the source of truth for performance review and backtest.

## Risk Filter (the 10 rules)

A token passes only if **all** 10 rules hold. Reject on first failure; record which rule fired. (The soldRatio gate is a separate, earlier check — it filters signal direction, not token safety.)

| # | Rule | Threshold | Source |
|---|---|---|---|
| R1 | Mint authority revoked | `isMintable: false` | `token report.security` |
| R2 | Freeze authority revoked | `isHasFrozenAuth: false` | `token report.security` |
| R3 | LP locked or burned | LP burned ≥ 50% OR locked ≥ 30 days | `token report.advancedInfo.lpBurnedPercent` |
| R4 | Top-1 holder share (excl. LP) | < 20% of supply | `token report.advancedInfo` (use top10 / 10 as proxy if top1 absent) |
| R5 | Top-10 holder share (excl. LP) | < 50% of supply | `token report.advancedInfo.top10HoldPercent` |
| R6 | No insider bundling | `bundleHoldingPercent < 10` | `token report.advancedInfo.bundleHoldingPercent` |
| R7 | Sellable, low price impact | `isHoneypot: false`, quote price impact < 5% | `swap quote` |
| R8 | Token age | ≥ 30 minutes from `createTime` | `token report.advancedInfo.createTime` |
| R9 | Holder count | ≥ 50 unique holders | `token report.priceInfo.holders` |
| R10 | Liquidity floor | pool ≥ $20,000 USD equivalent | `token report.priceInfo.liquidity` |

When the upstream skill cannot return a field, **default to fail** (`failed_rule = "R<N>_unknown"`). Do not approximate — judges will dock for silent passes on missing data.

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
| Smart-money cluster buy (≥ 3 wallets) | +30% | −15% | 4 h | 2% | **3%** |
| Single high-conviction KOL | +50% | −20% | 8 h | 2% | **3%** |

v0.2 tightens exit slippage from the v0.1 default of 10% to 3%, based on the 2026-05-16 demo run where actual market impact at $15 size was under 1% on $118K liquidity — 10% was wasteful defensive padding. If a paper-trade fill simulation shows fills outside this budget, the corpus will flag it and the config bumps for the affected signal class only.

**Live mode**: at entry, fire two limit orders **immediately** via `onchainos strategy create-limit` with `--slippage 3`. Monitor module cancels the surviving limit order when the other fills (`onchainos strategy cancel`). Time-out triggers a market close via `onchainos swap execute --slippage 5` (slightly looser because the timeout fill is non-discretionary).

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
  max_sold_ratio_pct: 30                 # soldRatio gate (signal direction filter)
  wallet_types: [1, 2, 3]                # 1=smart money, 2=KOL, 3=whale
filter:
  min_holders: 50
  min_liquidity_usd: 20000               # R10
  max_top1_pct: 0.20                     # R4
  max_top10_pct: 0.50                    # R5
  max_bundle_holding_pct: 0.10           # R6
  min_token_age_minutes: 30              # R8
  min_lp_burned_pct: 50                  # R3
sizing:
  win_prob: 0.35
  avg_win_pct: 1.5
  avg_loss_pct: 0.5
  variance: 1.0
  kelly_fraction: 0.25
  max_position_pct: 0.15
  min_position_usd: 5
exits:
  cluster_buy: {tp_pct: 0.30, sl_pct: -0.15, timeout_hours: 4, slippage_entry: 2, slippage_exit: 3}
  kol_solo:    {tp_pct: 0.50, sl_pct: -0.20, timeout_hours: 8, slippage_entry: 2, slippage_exit: 3}
paper:
  poll_interval_minutes: 5
  default_simulated_slippage_pct: 1.5    # used until live corpus replaces it
```

Override any value in this file; missing keys fall back to v0.2 defaults shown above. Config edits are journaled as a `config_changed` event so backtests can segment by config epoch.

## Disclaimer

This skill operates a self-custody wallet on a public blockchain. All trades in live mode are irreversible. The author makes no guarantee of profitability and disclaims liability for losses, slippage, gas costs, or third-party DEX failures. Paper mode runs no broadcasts and risks no capital. Use live mode only with funds you can afford to lose.
