# agentic-smart-money-sniper

A composable trading **skill** for OKX Agentic Wallet — submitted to the [OKX Agentic Trading Contest](https://web3.okx.com/zh-hans/boost/trading-competition/agentic-trading) **Skill Quality Prize** track (2026-05-07 → 2026-05-21).

It listens for smart-money / KOL cluster-buy signals on Solana and X Layer, screens each candidate against a **12-rule hard safety filter**, sizes positions with a Kelly-bounded fractional rule, opens the entry, and immediately attaches limit-order TP/SL. Every decision is appended to a JSONL journal so the chain of reasoning is auditable after the fact and the corpus can be replayed against historical prices for backtest and parameter calibration.

```
[ LISTENER ] → [ FILTER ] → [ SIZER ] → [ EXECUTOR ] → [ MONITOR ]
 signal feed    12 rules     Kelly       buy + TP/SL    poll & exit
```

The skill composes five existing OKX Onchain OS skills (`okx-dex-signal`, `okx-security`, `okx-dex-swap`, `okx-dex-strategy`, `okx-wallet-portfolio`) into a single policy. It does not invent new primitives — it defines decision boundaries, thresholds, safety gates, and the data the journal must capture.

---

## Table of contents

1. [Quick start](#quick-start)
2. [The three modes](#the-three-modes)
3. [The 12-rule filter at a glance](#the-12-rule-filter-at-a-glance)
4. [Typical workflows](#typical-workflows)
5. [Reading the journal](#reading-the-journal)
6. [Running the backtest](#running-the-backtest)
7. [Safety & onboarding](#safety--onboarding)
8. [Repo map](#repo-map)
9. [How it scores against the contest rubric](#how-it-scores-against-the-contest-rubric)
10. [Deliberate non-goals](#deliberate-non-goals)
11. [Version timeline](#version-timeline)
12. [License & disclaimer](#license--disclaimer)

---

## Quick start

### Prerequisites

- `onchainos` CLI ≥ 3.3.2 from `okx/onchainos-skills`
- A logged-in OKX Agentic Wallet: `onchainos wallet login <email>`
- The composed OKX skills (all part of the `okx/onchainos-skills` bundle):
  `okx-dex-signal`, `okx-security`, `okx-dex-swap`, `okx-dex-strategy`, `okx-wallet-portfolio`
- macOS for the launchd jobs (or substitute systemd / cron / your scheduler of choice)

### Install

```bash
npx skills add AvatarDao/agentic-smart-money-sniper --yes --global

# Or clone manually into the local agent skill directory:
git clone https://github.com/AvatarDao/agentic-smart-money-sniper \
  ~/.agents/skills/agentic-smart-money-sniper
```

### First-run sanity check

```bash
# Confirm onchainos sees your wallet
onchainos wallet status

# Pull a fresh smart-money signal page (read-only)
onchainos signal list --chain solana --wallet-type 1,2 --min-address-count 3 --limit 10
```

If both commands return `"ok": true`, the skill's data plane is healthy. You can now ask any Agentic-Wallet agent: *"scan smart money signals"*, *"sniper paper"*, *"sniper live"*, *"show sniper positions"*, etc.

---

## The three modes

Mode determines what the Executor and Monitor modules actually do. Listener / Filter / Sizer behave identically across modes so the corpus is comparable.

| Mode | Executor | Monitor | Capital at risk | Default? | Gate |
|---|---|---|---|---|---|
| `shadow` | no-op (signals + filter result printed only) | no-op | none | no | none |
| **`paper`** | **virtual fill at spot + simulated slippage** | **5-min price poll, virtual TP/SL/timeout** | **none** | **yes** | **none** |
| `live` | real `swap execute` + 2× `strategy create-limit` | actual on-chain settlement; OCO via `strategy cancel` | real | no | typed `I understand` once per 30 days |

Trigger them in natural language:

| Say | Action |
|---|---|
| "scan smart money signals" / "扫描聪明钱信号" | Listener only — print ranked candidates |
| "run sniper" / "纸面跑一遍" | Full pipeline, virtual fills (default = paper) |
| "run sniper live" / "实盘跑一次" | Full pipeline, real broadcasts — gated by typed consent |
| "show sniper positions" / "看持仓" | `strategy list` + journal cross-ref |
| "show sniper journal" / "看交易日志" | Tail `~/.agentic-sniper/trades.jsonl`, last 20 events |
| "sniper backtest" / "回测" | Replay journal against `token kline`, print sensitivity grid |
| "configure sniper" / "改配置" | Show / edit `~/.agentic-sniper/config.yaml` |

---

## The 12-rule filter at a glance

A token passes only if **all 12 rules hold**. Reject on first failure; the failing rule is recorded in the journal. Missing API data defaults to **fail** (sentinel 9999), per the project-wide "default to fail" rule.

| # | Rule | Threshold | Source | Added |
|---|---|---|---|---|
| R1 | Mint authority revoked | `isMintable: false` | `token report.security` | v0.1 |
| R2 | Freeze authority revoked | `isHasFrozenAuth: false` | `token report.security` | v0.1 |
| R3 | LP locked or burned | LP burned ≥ 50% OR locked ≥ 30 days | `token report.advancedInfo.lpBurnedPercent` | v0.1 |
| R4 | Top-1 holder share (excl. LP) | < 20% of supply | `token report.advancedInfo` | v0.1 |
| R5 | Top-10 holder share (excl. LP) | < 50% of supply | `token report.advancedInfo.top10HoldPercent` | v0.1 |
| R6 | No insider bundling | `bundleHoldingPercent < 10` | `token report.advancedInfo.bundleHoldingPercent` | v0.1 |
| R7 | Sellable, low price impact | `isHoneypot: false`, impact < 5% | `swap quote` | v0.2 |
| R8 | Token age | ≥ 30 minutes from `createTime` | `token report.advancedInfo.createTime` | v0.1 |
| R9 | Holder count | ≥ 50 unique holders | `token report.priceInfo.holders` | v0.1 |
| R10 | Liquidity floor | pool ≥ $20,000 USD | `token report.priceInfo.liquidity` | v0.1 |
| R11 | Market cap floor | ≥ $200,000 USD | `token report.priceInfo.marketCap` | v0.3 |
| R12 | Dev rug history | `devRugPullTokenCount == 0` | `token report.advancedInfo.devRugPullTokenCount` | v0.4 |

Backed by two prior live-fire validations:

- **R11** lifted out of the v0.2.2 backtest: sub-$50K MC delivered −7.08% mean per trade across 44 trades; the $1M–$10M bucket alone returned +3.04% mean (40% win rate, n=10). See `references/backtest-2026-05-16-report.md`.
- **R12** caught a serial-rug deployer on 2026-05-20: token `HeavyPulp` cleared R1–R11 cleanly, then `devRugPullTokenCount: 105` rejected it. Full transcript in `references/r12-live-rejection.md`.

Position-sizing on top of the filter is Kelly-bounded fractional:

```
edge      = win_prob × avg_win_pct − (1 − win_prob) × avg_loss_pct
size_pct  = min(0.25 × edge / variance, max_position_pct)
size_usd  = bankroll × size_pct
```

v0.4 defaults yield ≈ 9% of bankroll per trade, capped at 15%, min $5.

---

## Typical workflows

### Workflow A — Build a paper corpus (recommended first run)

```bash
# One-time install of the autonomous paper runner
mkdir -p ~/.agentic-sniper
cp scripts/run_paper.py ~/.agentic-sniper/
cp scripts/launchd/com.agentic-sniper.paper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agentic-sniper.paper.plist

# Watch it work
tail -f ~/.agentic-sniper/paper.log
```

The job fires every 30 minutes (and once at load). Each run scans the live signal stream, applies the 12-rule filter, and writes virtual fills to the journal. After 24 h expect 50–200 events; after 7 days expect 300–1000.

### Workflow B — Daily backtest archive

```bash
cp scripts/run_backtest_daily.py ~/.agentic-sniper/
cp scripts/launchd/com.agentic-sniper.backtest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agentic-sniper.backtest.plist

# Run once on demand
python3 ~/.agentic-sniper/run_backtest_daily.py
```

The job fires daily at 04:00 local, pulls 24 h of signals, fetches 5-minute klines for every candidate token, and runs a 14-strategy matrix (v0.2 baseline, v0.3 default, single-change ablations, grid variants, counterfactuals). The archive lands at:

```
~/.agentic-sniper/backtest/YYYY-MM-DD/
├── signals.json          # 24 h of dedup'd signals
├── klines/<token>.json   # 5m candles per token
├── results.json          # per-strategy + per-trade detail
└── report.md             # rendered ranking table
```

Compare day-to-day to detect parameter drift, market-regime change, or sample-size milestones.

### Workflow C — Go live

1. Run paper for at least a few days. Inspect `~/.agentic-sniper/trades.jsonl` and a daily backtest report — confirm the corpus says what you expect.
2. Flip `mode: live` in `~/.agentic-sniper/config.yaml`.
3. First live invocation triggers the 7-step onboarding (see **Safety**). Type the literal string `I understand`.
4. The skill places real orders. Watch `paper.log` and `wallet history` for fills.

---

## Reading the journal

`~/.agentic-sniper/trades.jsonl` — one JSON object per line, schema stable across modes. Every event carries `mode`, `event`, `run_id`, and (for trades originating from a signal) the full `signal` feature snapshot taken at `signal_received` time, carried forward unchanged on every later event for the same `run_id`.

Worked example (one full live trade life-cycle):

```json
{"ts":"2026-05-16T10:09:49Z","mode":"live","event":"signal_received","run_id":"1638e64d-…","token":{"chain":"solana","address":"…","symbol":"Wish"},"signal":{"source":"smart_money_cluster","wallet_count":4,"sold_ratio_pct":0.77,…}}
{"ts":"2026-05-16T10:09:49Z","mode":"live","event":"filter_passed","run_id":"1638e64d-…","filter":{"passed":true,"rules_checked":["R1",…,"R10"],"failed_rule":null}}
{"ts":"2026-05-16T10:09:49Z","mode":"live","event":"size_decided","run_id":"1638e64d-…","sizer":{"bankroll_usd":172,"size_pct":0.09,"size_usd":15.5}}
{"ts":"2026-05-16T10:10:55Z","mode":"live","event":"position_opened","run_id":"1638e64d-…","trade":{"side":"buy","size_usd":15.5,"entry_price_usd":0.0004415,"tokens_received":34791.55,"tx_hash":"4wiUebx…"}}
{"ts":"2026-05-16T10:11:12Z","mode":"live","event":"tp_set","run_id":"1638e64d-…","tp":{"order_id":"…","trigger_price_usd":0.000574,"pct":0.30}}
{"ts":"2026-05-16T10:11:13Z","mode":"live","event":"sl_set","run_id":"1638e64d-…","sl":{"order_id":"…","trigger_price_usd":0.000375,"pct":-0.15}}
```

Useful one-liners:

```bash
# Count events by type
jq -r '.event' ~/.agentic-sniper/trades.jsonl | sort | uniq -c

# All trades for one run_id
grep '1638e64d' ~/.agentic-sniper/trades.jsonl

# Most-recent run summary
grep '"event":"run_summary"' ~/.agentic-sniper/trades.jsonl | tail -1 | jq

# Per-rule rejection counts (audit which rules are tightest)
grep '"event":"filter_rejected"' ~/.agentic-sniper/trades.jsonl | \
  jq -r '.filter.failed_rule' | sort | uniq -c | sort -rn
```

Canonical schema with all event types in `references/sample-journal.jsonl`.

---

## Running the backtest

The harness replays the journal against historical price data and produces three artifacts per run:

1. **Hypothetical PnL** under the current config — config-drift detector.
2. **Parameter sensitivity** — sweep `tp_pct`, `sl_pct`, `min_wallet_count`, `sold_ratio_max`, `min_market_cap`. Pick the point that maximises `mean_PnL × √n`.
3. **Per-feature lift** — conditional win-rate per signal-feature bucket vs. the corpus average.

The first complete run (2026-05-16, 24 h of signals, 25-strategy sweep) is captured in `references/backtest-2026-05-16-report.md`. Read it before tuning anything — it documents exactly which proposed changes the data supports and which are noise.

The daily runner (`scripts/run_backtest_daily.py`) automates all of this and writes a fresh archive every 04:00 local.

---

## Safety & onboarding

Live mode is gated by a seven-step onboarding flow, enforced before the first real broadcast:

1. `wallet status` — confirm logged in.
2. Refuse if total balance < $50 (gas + slippage dominate).
3. Warn if balance < $200 — explicit confirmation required.
4. Direct the user to set per-tx and daily limits at the OKX Policy Settings URL; confirm done.
5. Print the disclaimer verbatim.
6. Wait for the exact string `I understand`. Anything else aborts.
7. Persist consent timestamp to `~/.agentic-sniper/consent.json`; re-prompt every 30 days.

Paper and shadow modes skip steps 4–7 — no capital at risk.

Additional always-on protections:

- **`--expires-in` discipline** (added v0.3.1 after a real-money loss on Wish). The CLI order TTL must be strictly greater than the skill's `timeout_hours`. Use 7 days (`604800` seconds) as the safe default; the skill's own monitor handles earlier-than-TTL closes.
- **Default-to-fail on missing data** for every filter rule, especially R12 (sentinel 9999 if `devRugPullTokenCount` is null/missing).
- **No unlimited approvals.** Approve amount is capped at swap size + 10% buffer, never `2^256-1`.
- **Simulation-fail does not broadcast.** If `swap execute` returns `executeResult: false`, the skill logs an error event and stops — does not retry blind.

---

## Repo map

```
agentic-smart-money-sniper/
├── README.md                                       # this manual
├── SKILL.md                                        # the skill itself (the agent loads this)
├── CHANGELOG.md                                    # version history with rationale
├── LICENSE                                         # MIT
├── references/
│   ├── strategy-notes.md                           # open-source bot architectures + rug-check rule sources
│   ├── paper-trade.md                              # paper-mode arithmetic + poll cadence
│   ├── backtest.md                                 # backtest spec, calibration loop, bootstrap protocol
│   ├── backtest-2026-05-16-report.md               # the 24h, 25-strategy report that drove v0.3
│   ├── backtest-2026-05-16-results.json            # per-trade detail from above
│   ├── backtest-v0.3-comparison.md                 # v0.2 baseline vs v0.3 default on same corpus
│   ├── r12-live-rejection.md                       # live-fire validation of R12 on HeavyPulp
│   ├── smart-money-distillation.md                 # top-50 SM trader reverse-engineering + R13 proposal
│   ├── demo-run.md                                 # captured 2026-05-16 live trade with on-chain links
│   └── sample-journal.jsonl                        # canonical schema, one full life-cycle
└── scripts/
    ├── run_paper.py                                # autonomous corpus builder, fires every 30 min
    ├── run_backtest_daily.py                       # daily backtest archive, fires 04:00 local
    ├── pull_signals.py, fetch_klines.py,           # one-shot tools used to produce v0.2.2 report
    │   backtest.py, analyze_backtest.py            #   (subsumed by run_backtest_daily.py, kept for reference)
    └── launchd/
        ├── com.agentic-sniper.paper.plist          # paper job, 30-min cadence
        └── com.agentic-sniper.backtest.plist       # backtest job, daily 04:00
```

The runtime state directory `~/.agentic-sniper/` is created on first launchd load and holds:

```
~/.agentic-sniper/
├── trades.jsonl              # the journal (append-only)
├── consent.json              # live-mode consent timestamp
├── config.yaml               # user overrides (any subset of v0.4 defaults)
├── paper.log                 # paper runner stdout
├── backtest.log              # backtest runner stdout
└── backtest/YYYY-MM-DD/      # one daily archive per launchd fire
```

---

## How it scores against the contest rubric

| Rubric dimension | How this skill addresses it |
|---|---|
| **Strategy completeness** | Five-module pipeline with explicit handoffs. Every module has defined inputs, outputs, and journal events. The skill is a single-file policy (`SKILL.md`) — judges can read the whole decision tree in one place. |
| **Risk control** | 12-rule hard safety filter with conservative defaults; Kelly-bounded sizing capped at 15%; mandatory TP/SL on every entry; default-to-fail on missing data; explicit `--expires-in` discipline learned from a real loss. |
| **Execution reliability** | Per-step error handling table in §Failure Modes; simulation-fail does not broadcast; TP-then-SL atomicity (cancel TP if SL fails); launchd jobs include explicit proxy and home-dir env so daemon firings don't silently lose signal data (the v0.3.1 lesson). |
| **User safety onboarding** | Seven-step first-run flow gated on typed `I understand`; paper mode is the default (live requires explicit flag + valid consent stamp ≤ 30 d); Wallet Export Guard fires before any export to prevent forfeiting active competition entries. |
| **Observability** | JSONL journal with stable schema; every event carries `run_id` for cross-module traceability; full signal feature snapshot is captured on `signal_received` and **carried forward** unchanged on every later event for that `run_id`, making the corpus directly usable as backtest input without joins. |

Five live-fire validations are captured in the repo:

| Date | What | Outcome |
|---|---|---|
| 2026-05-16 | First live entry on Wish, full pipeline | TP/SL placed on-chain, captured in `demo-run.md`. (Later lost −41% — see "what we learned".) |
| 2026-05-16 | 24h, 25-strategy backtest sweep | Surfaced the six v0.3 parameter changes; report in `backtest-2026-05-16-report.md`. |
| 2026-05-17 to -19 | Daily backtest launchd job, three consecutive failures | Diagnosed proxy-env issue, fixed in v0.3.1. Documented in the CHANGELOG. |
| 2026-05-20 | First R12 trigger | `HeavyPulp` (12 rules → R12 rejected on `devRugPullTokenCount: 105`). Transcript in `r12-live-rejection.md`. |
| 2026-05-21 | Smart-money leaderboard distillation | Top-50 SM Solana traders reverse-engineered; central insight: R11 ≠ elite-SM playbook by design. R13 proposed for v0.5. See `smart-money-distillation.md`. |

---

## Deliberate non-goals

- **First-block new-pool sniping.** Latency-dominated, retail loses to professional infrastructure.
- **Multi-DEX manual routing.** The OKX aggregator already does this.
- **Own RPC pool / Jito bundle path.** Infra cost without our-scale edge.
- **ML signals / online training pipelines.** Not testable inside the contest window. The journal IS the dataset for whatever ML comes later.
- **Trades on non-Solana, non-X-Layer chains.** The contest does not credit them.
- **Following elite-SM into sub-$15K MC.** The leaderboard distillation shows this is exactly where the top wallets profit — and exactly where retail (us) lacks the tooling to play safely. R11 stays.

---

## Version timeline

| Version | Date | Key shipped |
|---|---|---|
| 0.1.0 | 2026-05-16 | Initial skeleton + first live trade on Wish |
| 0.2.0 | 2026-05-16 | Paper / shadow / live modes; default exit slippage 10% → 3% |
| 0.2.2 | 2026-05-16 | 24 h × 25-strategy backtest report → six v0.3 changes |
| 0.3.0 | 2026-05-16 | R11 (MC ≥ $200K) + drop whales + soldRatio < 15 + TP/SL +50/-20 / 6 h |
| 0.3.1 | 2026-05-19 | Three prod bugfixes: launchd proxy env, KeyError on n=0, `--expires-in` discipline |
| 0.4.0 | 2026-05-20 | R12 (`devRugPullTokenCount == 0`) + HeavyPulp live-rejection demo |
| 0.4.1 | 2026-05-21 | Smart-money distillation + R13 proposal (docs-only) |

Full rationale per version in `CHANGELOG.md`.

---

## License & disclaimer

MIT — see `LICENSE`.

This skill operates a self-custody wallet on a public blockchain. **All trades in live mode are irreversible.** The author makes no profitability guarantee and disclaims liability for losses, slippage, gas costs, or third-party DEX failures. Paper mode runs no broadcasts and risks no capital. Use live mode only with funds you can afford to lose.

---

## Acknowledgements

Built on top of the OKX Onchain OS skills suite (`okx-dex-signal`, `okx-security`, `okx-dex-swap`, `okx-dex-strategy`, `okx-wallet-portfolio`). Research distillation cited concrete sources in `references/strategy-notes.md` (warp-id/solana-trading-bot for architecture, BarryGuard for the seven-red-flags checklist, Helius for authority semantics).
