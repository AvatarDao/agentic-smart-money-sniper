---
name: agentic-smart-money-sniper
description: "Smart-money copy-trading skill for OKX Agentic Wallet on Solana and X Layer. Listens to smart-money / KOL cluster-buy signals via `okx-dex-signal`, runs a 10-rule safety filter (`okx-security` + on-chain checks), sizes positions with Kelly-bounded fractional rule, executes market entry via `okx-dex-swap`, and immediately attaches limit-order TP/SL via `okx-dex-strategy`. Designed for the OKX Agentic Trading Contest. Triggers: 'run sniper', 'scan smart money', 'sniper dry-run', 'sniper live', 'sniper positions', 'sniper journal', 'configure sniper'. Refuses to trade live without an explicit `--live` flag and a typed risk acknowledgement."
license: MIT
metadata:
  author: AvatarDao
  version: "0.1.0"
  homepage: "https://github.com/AvatarDao/agentic-smart-money-sniper"
---

# Agentic Smart-Money Sniper

A composable trading skill for OKX Agentic Wallet. It does **one** thing well: when curated smart-money wallets collectively buy a Solana or X Layer token that passes a hard safety filter, open a small, stop-loss-protected position and log every decision.

The skill does not invent new primitives — it composes `okx-dex-signal`, `okx-security`, `okx-dex-swap`, `okx-dex-strategy`, and `okx-wallet-portfolio` into a coherent policy. Judges and operators read this single file to understand the entire decision tree.

## Pre-flight

Read `../okx-agentic-wallet/_shared/preflight.md` and ensure the user is logged in (`onchainos wallet status` → `loggedIn: true`) before any other step. Refuse to proceed if not.

## Five-module pipeline (canonical)

Every run executes these in order. A failure at any module short-circuits the trade and writes a `filter_rejected` or `error` event to the journal.

```
[ LISTENER ] --(token candidates)--> [ FILTER ] --(passing tokens)--> [ SIZER ] --(USD size)--> [ EXECUTOR ] --(txHash)--> [ MONITOR ]
```

| Module | Implementation | Output |
|---|---|---|
| Listener | `onchainos signal list --type smart_money --chain solana,xlayer --window 30m` | ranked token candidates with smart-money buy intensity |
| Filter | 10 rules (see §Risk Filter), backed by `onchainos security tx-scan` + `onchainos token detail` | `(passed: bool, failed_rule: str?)` |
| Sizer | Kelly-bounded fractional formula (see §Position Sizing) | size in USD, clamped to caps |
| Executor | `onchainos swap swap` for entry; `onchainos strategy create-limit` ×2 for TP & SL | entry txHash + 2 limit-order IDs |
| Monitor | `onchainos strategy list` + `onchainos wallet history` polled every 60s | exit txHash + realized PnL |

Each step writes one JSONL event (see §Journal). The journal is the source of truth for performance review.

## Risk Filter (the 10 rules)

A token passes only if **all** 10 rules hold. Reject on first failure; record which rule fired.

| # | Rule | Threshold | Source |
|---|---|---|---|
| R1 | Mint authority revoked | `mintAuthority == null` | `security tx-scan` |
| R2 | Freeze authority revoked | `freezeAuthority == null` | `security tx-scan` |
| R3 | LP locked or burned | lock ≥ 30 days OR LP burned | `token detail` |
| R4 | Top-1 holder share (excl. LP) | < 20% of supply | `token detail` |
| R5 | Top-10 holder share (excl. LP) | < 50% of supply | `token detail` |
| R6 | No insider bundling | < 5 top holders share one funder | `token detail` |
| R7 | Sellable, low price impact | simulated sell price impact < 50% | `security tx-scan` |
| R8 | Token age | ≥ 30 minutes from first trade | `token detail` |
| R9 | Holder count | ≥ 50 unique holders | `token detail` |
| R10 | Liquidity floor | pool ≥ $20,000 USD equivalent | `token detail` |

When the upstream skill cannot return a field, **default to fail** (`failed_rule = "R<N>_unknown"`). Do not approximate — judges will dock for silent passes on missing data.

## Position Sizing

Kelly-bounded fractional. For each candidate:

```python
edge      = win_prob * avg_win_pct - (1 - win_prob) * avg_loss_pct
kelly_f   = max(0, edge / variance)
size_pct  = min(kelly_f * 0.25, max_position_pct)   # 25% Kelly fractional, capped
size_usd  = bankroll_usd * size_pct
```

v1 defaults (conservative — no historical estimate yet):

```yaml
win_prob:          0.35
avg_win_pct:       1.5
avg_loss_pct:      0.5
variance:          1.0
max_position_pct:  0.15   # never more than 15% of bankroll in one trade
min_position_usd:  5      # below this, gas/slippage dominates → skip
```

These yield ~9% of bankroll per trade, capped at 15%. Override via `~/.agentic-sniper/config.yaml`.

## TP / SL policy

At every successful entry, fire two limit orders **immediately** via `onchainos strategy create-limit`:

| Signal type | TP | SL | Time-out close |
|---|---|---|---|
| Smart-money cluster buy (≥ 3 wallets) | +30% | −15% | 4 h |
| Single high-conviction KOL | +50% | −20% | 8 h |

Monitor module cancels the surviving limit order when the other fills (`onchainos strategy cancel`). Time-out triggers a market close via `onchainos swap swap` and a `timeout_close` journal event.

## Safety Onboarding

First run of `sniper run --live` enforces this sequence. Refuse to proceed if any step is skipped.

1. `onchainos wallet status` → confirm logged-in account and total balance.
2. Refuse if balance < $50 — too low to overcome gas + slippage.
3. Warn if balance < $200 — print expected per-trade size and ask explicit confirmation.
4. Direct the user to set per-tx and daily limits at the OKX Policy URL (from `okx-agentic-wallet` user-facing templates) and confirm they did.
5. Print verbatim:
   > This skill opens real positions in volatile memecoin tokens on Solana and X Layer. Realized losses are possible and not refundable. Type "I understand" to proceed.
6. Wait for exact string `I understand`. Anything else aborts.
7. Persist consent timestamp to `~/.agentic-sniper/consent.json`; re-prompt every 30 days.

Dry-run (`--dry-run`, the default) skips steps 4-7 — no real funds at stake.

## Commands the skill responds to

The skill is invoked through the agent in natural language. Canonical intents:

| User says (EN / ZH) | Action |
|---|---|
| "scan smart money signals" / "扫描聪明钱信号" | Listener only — print ranked candidates, do nothing |
| "run sniper dry-run" / "跑一遍模拟" | Full pipeline, simulated execution, journal written |
| "run sniper live" / "实盘跑一次" | Full pipeline, real trades — gated by onboarding |
| "show sniper positions" / "看持仓" | `strategy list` + `wallet history` for the account |
| "show sniper journal" / "看交易日志" | Tail `~/.agentic-sniper/trades.jsonl`, render last 20 events |
| "configure sniper" / "改配置" | Open `~/.agentic-sniper/config.yaml` |

Dry-run is always the default. Live mode requires either a typed `--live` token in the prompt or an interactive `I understand` confirmation in the current session.

## Journal Format

One JSON object per line at `~/.agentic-sniper/trades.jsonl`. Required fields per event type:

```json
{
  "ts": "2026-05-17T03:14:22Z",
  "event": "signal_received | filter_passed | filter_rejected | position_opened | tp_set | sl_set | tp_fired | sl_fired | timeout_close | error",
  "run_id": "uuid-v4 — same id across all events of one pipeline run",
  "token": {"chain": "solana", "address": "...", "symbol": "..."},
  "signal": {"source": "smart_money_cluster", "wallet_count": 3, "intensity_rank": 7},
  "filter": {"passed": true, "rules_checked": ["R1","R2",...], "failed_rule": null},
  "trade": {"side": "buy|sell", "size_usd": 17.2, "price": 0.000123, "tx_hash": "..."},
  "pnl": {"realized_usd": 4.5, "pct": 0.26}
}
```

After each run, append a summary line with `"event": "run_summary"` containing `total_trades`, `win_rate`, `gross_pnl_usd`, `mean_pnl_pct`, `top_reject_rule`.

## Out of scope (deliberate)

State plainly in the README and refuse if the user asks:

- New-pool first-block sniping (latency-dominated, retail loses).
- Multi-DEX manual routing (OKX aggregator already does this).
- Own RPC pool / Jito bundle path (infra cost, no edge for our size).
- ML signals / training pipelines (untestable in the contest window).
- Trades on non-Solana, non-X-Layer chains (the contest does not credit them).

## Failure Modes

| Failure | Skill response |
|---|---|
| `signal list` returns empty | print "no qualifying signals in window", exit clean — no error |
| `security tx-scan` times out (> 5s) | retry once with 10s budget; if still timing out, treat as R1/R2/R7 unknown → reject |
| `swap swap` returns simulation failure | log error event with `executeErrorMsg`, do NOT broadcast |
| `strategy create-limit` for TP succeeds but SL fails | cancel TP immediately, market-close the position, log error |
| Network error during monitor | back-off retry every 60s; alert user only after 3 consecutive failures |

## Configuration (`~/.agentic-sniper/config.yaml`)

```yaml
chains: [solana, xlayer]
listener:
  window_minutes: 30
  min_wallet_count: 3
filter:
  min_holders: 50
  min_liquidity_usd: 20000
  max_top1_pct: 0.20
  max_top10_pct: 0.50
  min_token_age_minutes: 30
sizing:
  win_prob: 0.35
  avg_win_pct: 1.5
  avg_loss_pct: 0.5
  variance: 1.0
  kelly_fraction: 0.25
  max_position_pct: 0.15
  min_position_usd: 5
exits:
  cluster_buy: {tp_pct: 0.30, sl_pct: -0.15, timeout_hours: 4}
  kol_solo:    {tp_pct: 0.50, sl_pct: -0.20, timeout_hours: 8}
```

Override any value in this file; missing keys fall back to the v1 defaults shown above.

## Disclaimer

This skill operates a self-custody wallet on a public blockchain. All trades are irreversible. The author makes no guarantee of profitability and disclaims liability for losses, slippage, gas costs, or third-party DEX failures. Use only with funds you can afford to lose.
