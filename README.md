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
| `CHANGELOG.md` | Version history. |
| `README.md` | This file. |

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
