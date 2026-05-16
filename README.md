# agentic-smart-money-sniper

A composable trading **skill** for OKX Agentic Wallet — submitted to the [OKX Agentic Trading Contest](https://web3.okx.com/zh-hans/boost/trading-competition/agentic-trading) Skill Quality Prize track (2026-05-07 → 2026-05-21).

The skill orchestrates five OKX Onchain OS skills into a single policy:

```
okx-dex-signal    →    okx-security    →    (Kelly sizer)    →    okx-dex-swap    →    okx-dex-strategy (TP/SL)
   listener              filter               sizer                  executor                monitor
```

It listens for smart-money / KOL cluster-buy signals on Solana and X Layer, screens each candidate against ten hard safety rules, sizes positions with a Kelly-bounded fractional rule, opens the entry, and immediately attaches limit-order take-profit and stop-loss orders. Every decision is appended to a JSONL journal so the user can audit the chain of reasoning after the fact.

## What the skill is and is not

**What it is** — a single-file policy document (`SKILL.md`) that the OKX Agentic Wallet agent reads to make consistent, auditable trading decisions on the user's behalf. The skill defines decision boundaries, thresholds, safety filters, and the data the journal must capture. The OKX skills it composes do the actual on-chain work.

**What it is not** — a low-latency new-pool sniper, a multi-DEX router, an ML-based signal generator, or a CEX bot. Those are deliberately out of scope (see §"Out of scope" in `SKILL.md`).

## Files

| File | Purpose |
|---|---|
| `SKILL.md` | The skill itself — frontmatter + policy. This is what an Agentic Wallet agent loads. |
| `references/strategy-notes.md` | Research distillation: open-source bot architectures, rug-check rule sources, sizing rationale. |
| `references/paper-trade.md` | Paper-mode semantics: virtual fill arithmetic, poll cadence, paper-to-live transition. |
| `references/backtest.md` | Backtest spec and calibration loop. Runner lands in v0.3; v0.2 ships the schema and worked-example tables. |
| `references/sample-journal.jsonl` | Canonical journal schema with one example trade life-cycle. |
| `references/demo-run.md` | A captured live end-to-end run on 2026-05-16, with on-chain links for verifiability. |
| `scripts/run_paper.py` | Autonomous corpus builder. Scans signals, applies the 11-rule filter (records every rule's status, not just the first failure), opens paper positions, writes everything to `~/.agentic-sniper/trades.jsonl`. Safe to run on a cron — has 6-hour dedup window on rejected tokens. |
| `scripts/run_backtest_daily.py` | Daily backtest runner — pulls 24h of signals, fetches klines for each candidate, runs the 14-strategy matrix (v0.2 baseline / v0.3 default / per-change ablations / counterfactuals), archives results to `~/.agentic-sniper/backtest/YYYY-MM-DD/`. |
| `scripts/pull_signals.py`, `fetch_klines.py`, `backtest.py`, `analyze_backtest.py` | One-shot backtest tools used to produce the v0.2.2 report. The daily runner subsumes them but they remain as reference. |
| `scripts/launchd/com.agentic-sniper.paper.plist` | macOS launchd: paper-trade pipeline every 30 minutes. |
| `scripts/launchd/com.agentic-sniper.backtest.plist` | macOS launchd: full backtest daily at 04:00 local. |
| `CHANGELOG.md` | Version history. |
| `README.md` | This file. |

## Autonomous corpus growth

To accumulate the journal corpus needed for v0.3 calibration, install the launchd job:

```bash
# Copy the script out of any sandboxed directory (macOS denies launchd access to ~/Desktop, ~/Documents, etc.)
mkdir -p ~/.agentic-sniper
cp scripts/run_paper.py ~/.agentic-sniper/run_paper.py

# Install + start the launchd job (runs every 30 min, also fires at load)
cp scripts/launchd/com.agentic-sniper.paper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agentic-sniper.paper.plist

# Tail the log
tail -f ~/.agentic-sniper/paper.log

# Stop / uninstall
launchctl unload ~/Library/LaunchAgents/com.agentic-sniper.paper.plist
```

Each run adds 1–10 events to `~/.agentic-sniper/trades.jsonl`. Over 24 hours you can expect 50–200 events depending on signal stream activity. The `recently_processed` dedup window (6 h) prevents the same rejected token being re-scanned to death; tokens whose signal returns *after* the window are re-examined and their evolving state is captured.

## Daily backtest

Same install pattern. The job runs daily at 04:00 local time, pulls 24h of signals, fetches klines for every candidate token, runs the 14-strategy sweep, and writes the archive to `~/.agentic-sniper/backtest/YYYY-MM-DD/`:

```bash
cp scripts/run_backtest_daily.py ~/.agentic-sniper/
cp scripts/launchd/com.agentic-sniper.backtest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agentic-sniper.backtest.plist

# Run once on demand
python3 ~/.agentic-sniper/run_backtest_daily.py

# Browse the archive
ls -lt ~/.agentic-sniper/backtest/
```

Each daily archive contains:

```
~/.agentic-sniper/backtest/YYYY-MM-DD/
├── signals.json          # 24h of dedup'd signals
├── klines/<token>.json   # 5m candles per token, cached
├── results.json          # full 14-strategy result with per-trade detail
└── report.md             # rendered table, sorted by final bankroll
```

Compare day-to-day to detect parameter drift, market regime changes, or sample-size milestones.

## How to install

```bash
npx skills add AvatarDao/agentic-smart-money-sniper --yes --global
```

Or clone into the local agent skill directory:

```bash
git clone https://github.com/AvatarDao/agentic-smart-money-sniper ~/.agents/skills/agentic-smart-money-sniper
```

The skill requires the following prerequisites installed and configured first:

- `onchainos` CLI ≥ 3.3.2 from `okx/onchainos-skills`
- Logged-in OKX Agentic Wallet (`onchainos wallet login <email>`)
- The composed OKX skills: `okx-dex-signal`, `okx-security`, `okx-dex-swap`, `okx-dex-strategy`, `okx-wallet-portfolio`. All are part of the `okx/onchainos-skills` bundle.

## How it scores against the contest rubric

| Rubric dimension | How this skill addresses it |
|---|---|
| **Strategy completeness** | Five-module pipeline with explicit handoffs; every step has defined inputs, outputs, and journal events. |
| **Risk control** | Ten-rule hard filter with conservative defaults; Kelly-bounded sizing capped at 15%; mandatory TP/SL on every entry; default-fail on unknown data. |
| **Execution reliability** | Per-step error handling table; simulation-fail does not broadcast; TP-then-SL atomicity (cancel TP if SL fails). |
| **User safety onboarding** | Seven-step first-run onboarding with typed `I understand` confirmation; dry-run is the default; live mode requires explicit flag. |
| **Observability** | JSONL journal with stable schema; per-run summary; uses `run_id` for traceability across pipeline events. |

## Disclaimer

This skill operates a self-custody wallet. All trades are irreversible. The author makes no profitability guarantee and disclaims liability for losses, slippage, gas costs, or third-party DEX failures.

## License

MIT — see `LICENSE`.
