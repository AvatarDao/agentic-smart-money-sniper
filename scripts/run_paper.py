#!/usr/bin/env python3
"""
run_paper.py — execute the agentic-smart-money-sniper pipeline in paper mode.

Pulls buy-heavy smart-money / KOL / whale signals on Solana, applies the v0.2
ten-rule filter, sizes positions with the Kelly-bounded fractional rule, and
appends a full event chain to ~/.agentic-sniper/trades.jsonl. No transactions
are broadcast.

Usage:
  python3 scripts/run_paper.py                   # one pass, all wallet types
  python3 scripts/run_paper.py --max-trades 5    # cap new positions this pass
  python3 scripts/run_paper.py --dry             # filter only, no journal writes

Designed to be run periodically (e.g. cron every 30 min) to accumulate the
corpus needed for v0.3 backtest and calibration.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

SKILL_VERSION = "0.4.0"
JOURNAL = os.path.expanduser("~/.agentic-sniper/trades.jsonl")
SOL_NATIVE = "11111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"

# v0.3 config defaults — see backtest-2026-05-16-report.md for rationale
CONFIG = {
    "max_sold_ratio_pct": 15,            # v0.3: was 30; valley-of-death is 30-70
    "min_wallet_count": 3,
    "wallet_types": ["1", "2"],          # v0.3: dropped "3" whales
    "min_liquidity_usd_api": 50000,      # API-level pre-filter
    "filter": {
        "min_lp_burned_pct": 50,
        "max_top10_pct": 50,
        "max_bundle_pct": 10,
        "min_holders": 50,
        "min_liquidity_usd": 20000,
        "min_market_cap_usd": 200000,    # R11
        "max_dev_rug_count": 0,          # v0.4 R12 — strict zero, see references/r12-live-rejection.md
        "min_age_minutes": 30,
        "max_price_impact_pct": 5,
    },
    "sizing": {
        "win_prob": 0.35,
        "avg_win_pct": 1.5,
        "avg_loss_pct": 0.5,
        "variance": 1.0,
        "kelly_fraction": 0.25,
        "max_position_pct": 0.15,
        "min_position_usd": 5,
    },
    "exits": {
        "cluster_buy": {"tp_pct": 0.50, "sl_pct": -0.20, "timeout_h": 6},   # v0.3: widened
        "kol_solo":    {"tp_pct": 0.50, "sl_pct": -0.20, "timeout_h": 8},
    },
    "paper": {
        "simulated_slippage_pct": 1.5,
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd(*args, timeout=60):
    """Run `onchainos <args>` and return the parsed JSON `data` field, or None on failure."""
    full = ["onchainos"] + list(args)
    try:
        out = subprocess.check_output(full, timeout=timeout, stderr=subprocess.PIPE)
        parsed = json.loads(out)
        if not parsed.get("ok"):
            print(f"    cli !ok: {parsed.get('error', parsed)}", file=sys.stderr)
            return None
        return parsed.get("data")
    except subprocess.TimeoutExpired:
        print(f"    cli timeout: {' '.join(full)}", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(f"    cli error ({e.returncode}): {e.stderr.decode()[:200]}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(f"    cli non-json output: {out[:200]!r}", file=sys.stderr)
        return None


def read_journal_state(recent_hours=6):
    """Return (open_tokens, ever_traded_tokens, recently_processed_tokens).

    recently_processed = any token whose signal_received or filter_rejected was
    written within the last `recent_hours` hours. Used to dedupe scans.
    """
    open_tokens = set()
    ever_traded = set()
    recently_processed = set()
    if not os.path.exists(JOURNAL):
        return open_tokens, ever_traded, recently_processed
    runs = {}
    now_ms = time.time() * 1000
    recent_cutoff_ms = now_ms - recent_hours * 3600 * 1000
    with open(JOURNAL) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = e.get("run_id")
            if rid:
                runs.setdefault(rid, []).append(e)
            # Track recently processed tokens
            ts = e.get("ts")
            event = e.get("event")
            addr = e.get("token", {}).get("address") if isinstance(e.get("token"), dict) else None
            if addr and event in ("signal_received", "filter_rejected", "position_opened") and ts:
                try:
                    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    if dt.timestamp() * 1000 >= recent_cutoff_ms:
                        recently_processed.add(addr)
                except ValueError:
                    pass
    closed_events = {"tp_fired", "sl_fired", "timeout_close", "error"}
    for rid, events in runs.items():
        has_open = any(e.get("event") == "position_opened" for e in events)
        is_closed = any(e.get("event") in closed_events for e in events)
        token_addr = None
        for e in events:
            if e.get("event") == "position_opened":
                token_addr = e.get("token", {}).get("address")
                break
        if has_open and token_addr:
            ever_traded.add(token_addr)
            if not is_closed:
                open_tokens.add(token_addr)
    return open_tokens, ever_traded, recently_processed


def write_event(event):
    """Append one JSON event to the journal, fsync-safe."""
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


def listener(chain="solana", min_wallet=3, min_liquidity=0, pages=3):
    """Pull buy-heavy candidates with pagination. min_liquidity=0 means no API-level filter."""
    candidates = []
    seen_tokens = set()
    cursor = None
    # v0.3: only include wallet types from config (default ["1","2"] — dropping whales)
    wt_arg = ",".join(CONFIG["wallet_types"])
    for _ in range(pages):
        args = [
            "signal", "list",
            "--chain", chain,
            "--wallet-type", wt_arg,
            "--min-address-count", str(min_wallet),
            "--limit", "100",
        ]
        if min_liquidity > 0:
            args += ["--min-liquidity-usd", str(min_liquidity)]
        if cursor:
            args += ["--cursor", cursor]
        raw = cmd(*args)
        if not raw:
            break
        for row in raw:
            sold = float(row.get("soldRatioPercent", 100))
            if sold > CONFIG["max_sold_ratio_pct"]:
                continue
            token_addr = row["token"]["tokenAddress"]
            if token_addr in seen_tokens:
                continue
            seen_tokens.add(token_addr)
            candidates.append(row)
        cursor = raw[-1].get("cursor") if raw else None
        if not cursor:
            break
    return candidates


def apply_filter(signal_row):
    """Apply the 10-rule risk filter via `token report`. Return (passed, failed_rule, snapshot)."""
    addr = signal_row["token"]["tokenAddress"]
    data = cmd("token", "report", "--chain", "solana", "--address", addr, timeout=20)
    if not data:
        return False, "REPORT_UNAVAILABLE", {}
    adv = data.get("advancedInfo", {})
    price_list = data.get("priceInfo", [])
    sec_list = data.get("security", [])
    if not price_list or not sec_list:
        return False, "REPORT_INCOMPLETE", {}
    price = price_list[0]
    sec = sec_list[0]
    snapshot = {
        "risk_level": sec.get("riskLevel"),
        "is_mintable": sec.get("isMintable"),
        "is_frozen_auth": sec.get("isHasFrozenAuth"),
        "is_honeypot": sec.get("isHoneypot"),
        "lp_burned_pct": float(adv.get("lpBurnedPercent", 0) or 0),
        "top10_pct": float(adv.get("top10HoldPercent", 100) or 100),
        "bundle_pct": float(adv.get("bundleHoldingPercent", 100) or 100),
        # v0.4: sentinel 9999 if missing — R12 check then defaults to fail (per "default to fail" rule)
        "dev_rug_count": int(adv["devRugPullTokenCount"]) if adv.get("devRugPullTokenCount") not in (None, "") else 9999,
        "dev_holding_pct": float(adv.get("devHoldingPercent", 0) or 0),
        "create_time_ms": int(adv.get("createTime", 0) or 0),
        "holders": int(price.get("holders", 0) or 0),
        "liquidity_usd": float(price.get("liquidity", 0) or 0),
        "market_cap_usd": float(price.get("marketCap", 0) or 0),
        "price_usd": float(price.get("price", 0) or 0),
        "price_change_1h_pct": float(price.get("priceChange1H", 0) or 0),
        "price_change_4h_pct": float(price.get("priceChange4H", 0) or 0),
        "price_change_24h_pct": float(price.get("priceChange24H", 0) or 0),
        "tags": adv.get("tokenTags", []),
    }
    f = CONFIG["filter"]
    age_min = (time.time() * 1000 - snapshot["create_time_ms"]) / 60000 if snapshot["create_time_ms"] else 0
    snapshot["age_minutes"] = round(age_min, 1)
    checks = [
        ("R1", not snapshot["is_mintable"]),
        ("R2", not snapshot["is_frozen_auth"]),
        ("R3", snapshot["lp_burned_pct"] >= f["min_lp_burned_pct"]),
        ("R4", snapshot["top10_pct"] < f["max_top10_pct"]),  # using top10 as proxy
        ("R5", snapshot["top10_pct"] < f["max_top10_pct"]),
        ("R6", snapshot["bundle_pct"] < f["max_bundle_pct"]),
        ("R7", not snapshot["is_honeypot"]),
        ("R8", age_min >= f["min_age_minutes"]),
        ("R9", snapshot["holders"] >= f["min_holders"]),
        ("R10", snapshot["liquidity_usd"] >= f["min_liquidity_usd"]),
        ("R11", snapshot["market_cap_usd"] >= f["min_market_cap_usd"]),  # v0.3
        ("R12", snapshot.get("dev_rug_count", 9999) <= f["max_dev_rug_count"]),  # v0.4
    ]
    # Record EVERY check status for richer corpus data (vs. v0.2 spec which only records the first failure)
    rules_status = {name: ok for name, ok in checks}
    snapshot["rules_status"] = rules_status
    snapshot["failed_rules"] = [name for name, ok in checks if not ok]
    for name, ok in checks:
        if not ok:
            return False, name, snapshot
    return True, None, snapshot


def quote(from_addr, to_addr, amount_minimal):
    data = cmd(
        "swap", "quote",
        "--chain", "solana",
        "--from", from_addr,
        "--to", to_addr,
        "--amount", str(amount_minimal),
        timeout=15,
    )
    if not data:
        return None
    row = data[0] if isinstance(data, list) else data
    return {
        "price_impact_pct": float(row.get("priceImpactPercent", 100)),
        "to_amount_raw": int(row.get("toTokenAmount", 0)),
        "to_unit_price_usd": float(row.get("toToken", {}).get("tokenUnitPrice", 0)),
        "router": row.get("dexRouterList", [{}])[0].get("dexProtocol", {}).get("dexName", "unknown"),
    }


def get_sol_balance():
    data = cmd("wallet", "balance", "--chain", "solana")
    if not data:
        return 0.0, 0.0
    for asset in data.get("details", [{}])[0].get("tokenAssets", []):
        if asset.get("symbol") == "SOL":
            return float(asset["balance"]), float(asset["usdValue"])
    return 0.0, 0.0


def size_position(bankroll_usd):
    s = CONFIG["sizing"]
    edge = s["win_prob"] * s["avg_win_pct"] - (1 - s["win_prob"]) * s["avg_loss_pct"]
    kelly = max(0, edge / s["variance"])
    size_pct = min(kelly * s["kelly_fraction"], s["max_position_pct"])
    size_pct = max(size_pct, 0.09)  # floor at 9% for v0.2 (per spec)
    size_usd = bankroll_usd * size_pct
    if size_usd < s["min_position_usd"]:
        return None
    return {"size_pct": size_pct, "size_usd": size_usd}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trades", type=int, default=10)
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--min-wallet", type=int, default=3)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--chains", default="solana")
    args = parser.parse_args()

    open_tokens, ever_traded, recently_processed = read_journal_state(recent_hours=6)
    print(f"[state] journal: open={len(open_tokens)}  ever_traded={len(ever_traded)}  recently_processed={len(recently_processed)}")

    candidates = []
    for chain in args.chains.split(","):
        chain = chain.strip()
        chunk = listener(chain=chain, min_wallet=args.min_wallet, min_liquidity=0, pages=args.pages)
        print(f"[listener] {chain}: candidates (buy-heavy, dedup): {len(chunk)}")
        # tag chain on each
        for c in chunk:
            c["_chain"] = chain
        candidates.extend(chunk)
    if not candidates:
        return

    sol_bal, sol_usd = get_sol_balance()
    print(f"[wallet] SOL balance: {sol_bal:.4f} (${sol_usd:.2f})")

    new_paper_runs = 0
    rejected = []
    for sig in candidates:
        if new_paper_runs >= args.max_trades:
            break
        token = sig["token"]
        addr = token["tokenAddress"]
        sym = token["symbol"]
        sold = float(sig["soldRatioPercent"])
        wcount = int(sig["triggerWalletCount"])
        wtype = {"1": "smart_money_cluster", "2": "kol_cluster", "3": "whale_cluster"}.get(sig["walletType"], "unknown")

        if addr in ever_traded:
            print(f"  [skip] {sym}  already traded this token; skipping")
            continue
        if addr in recently_processed:
            print(f"  [skip] {sym}  scanned in last 6h; skipping")
            continue

        passed, fail_rule, snap = apply_filter(sig)
        run_id = str(uuid.uuid4())
        ts = now_iso()

        signal_block = {
            "source": wtype,
            "wallet_type": sig["walletType"],
            "wallet_count": wcount,
            "sold_ratio_pct": sold,
            "amount_usd": float(sig.get("amountUsd", 0) or 0),
            "market_cap_usd": snap.get("market_cap_usd"),
            "holders": snap.get("holders"),
            "top10_pct": snap.get("top10_pct"),
            "liquidity_usd": snap.get("liquidity_usd"),
            "price_change_1h_pct": snap.get("price_change_1h_pct"),
            "price_change_4h_pct": snap.get("price_change_4h_pct"),
            "price_change_24h_pct": snap.get("price_change_24h_pct"),
            "dev_rug_count": snap.get("dev_rug_count"),
            "dev_holding_pct": snap.get("dev_holding_pct"),
            "lp_burned_pct": snap.get("lp_burned_pct"),
            "bundle_holding_pct": snap.get("bundle_pct"),
            "tags": snap.get("tags", []),
        }

        if args.dry:
            print(f"  [dry] {sym:14} pass={passed} fail={fail_rule or '-'}")
            continue

        write_event({
            "ts": ts, "skill_version": SKILL_VERSION, "mode": "paper",
            "event": "signal_received", "run_id": run_id,
            "token": {"chain": "solana", "address": addr, "symbol": sym},
            "signal": signal_block,
        })

        if not passed:
            write_event({
                "ts": ts, "skill_version": SKILL_VERSION, "mode": "paper",
                "event": "filter_rejected", "run_id": run_id,
                "token": {"chain": "solana", "address": addr, "symbol": sym},
                "filter": {
                    "passed": False,
                    "failed_rule": fail_rule,
                    "failed_rules_all": snap.get("failed_rules", []),
                    "rules_status": snap.get("rules_status", {}),
                    "risk_level": snap.get("risk_level"),
                    "lp_burned_pct": snap.get("lp_burned_pct"),
                    "top10_pct": snap.get("top10_pct"),
                    "bundle_pct": snap.get("bundle_pct"),
                    "holders": snap.get("holders"),
                    "liquidity_usd": snap.get("liquidity_usd"),
                    "age_minutes": snap.get("age_minutes"),
                    "dev_rug_count": snap.get("dev_rug_count"),
                },
            })
            rejected.append((sym, fail_rule))
            print(f"  [reject] {sym:14} on {fail_rule}  also_fails={snap.get('failed_rules', [])}")
            continue

        sizing = size_position(sol_usd)
        if sizing is None:
            write_event({
                "ts": ts, "skill_version": SKILL_VERSION, "mode": "paper",
                "event": "filter_rejected", "run_id": run_id,
                "token": {"chain": "solana", "address": addr, "symbol": sym},
                "filter": {"passed": True, "failed_rule": "BANKROLL_TOO_SMALL"},
            })
            print(f"  [skip] {sym:14} bankroll too small")
            continue

        size_sol = sizing["size_usd"] / (sol_usd / sol_bal) if sol_bal > 0 else 0
        size_lamports = int(size_sol * 1e9)
        q = quote(WSOL, addr, size_lamports)
        if not q or q["price_impact_pct"] > CONFIG["filter"]["max_price_impact_pct"]:
            write_event({
                "ts": ts, "skill_version": SKILL_VERSION, "mode": "paper",
                "event": "filter_rejected", "run_id": run_id,
                "token": {"chain": "solana", "address": addr, "symbol": sym},
                "filter": {"passed": True, "failed_rule": "R7_quote_impact"},
                "quote": q,
            })
            print(f"  [reject] {sym:14} quote impact too high: {q['price_impact_pct'] if q else 'N/A'}%")
            continue

        # SIZER
        write_event({
            "ts": ts, "skill_version": SKILL_VERSION, "mode": "paper",
            "event": "size_decided", "run_id": run_id,
            "sizer": {
                "bankroll_usd": round(sol_usd, 2),
                "size_pct": round(sizing["size_pct"], 4),
                "size_usd": round(sizing["size_usd"], 4),
                "size_sol": round(size_sol, 6),
                "exit_class": "cluster_buy" if wcount >= 3 else "kol_solo",
            },
        })

        # EXECUTOR (virtual)
        slip = CONFIG["paper"]["simulated_slippage_pct"] / 100
        virtual_entry = q["to_unit_price_usd"] * (1 + slip)
        tokens_received = sizing["size_usd"] / virtual_entry if virtual_entry > 0 else 0
        write_event({
            "ts": now_iso(), "skill_version": SKILL_VERSION, "mode": "paper",
            "event": "position_opened", "run_id": run_id,
            "token": {"chain": "solana", "address": addr, "symbol": sym},
            "trade": {
                "side": "buy",
                "size_usd": round(sizing["size_usd"], 4),
                "size_sol": round(size_sol, 6),
                "quote_price_usd": q["to_unit_price_usd"],
                "simulated_slippage_pct": CONFIG["paper"]["simulated_slippage_pct"],
                "virtual_entry_price_usd": round(virtual_entry, 10),
                "tokens_received_virtual": round(tokens_received, 4),
                "price_impact_quote_pct": q["price_impact_pct"],
                "router": q["router"],
            },
        })

        # MONITOR setup
        exit_cfg = CONFIG["exits"]["cluster_buy"]  # default for cluster signals
        tp_price = virtual_entry * (1 + exit_cfg["tp_pct"])
        sl_price = virtual_entry * (1 + exit_cfg["sl_pct"])
        write_event({
            "ts": now_iso(), "skill_version": SKILL_VERSION, "mode": "paper",
            "event": "tp_set", "run_id": run_id,
            "tp": {"trigger_price_usd": round(tp_price, 10), "pct": exit_cfg["tp_pct"],
                   "amount_tokens": round(tokens_received, 4),
                   "timeout_hours": exit_cfg["timeout_h"]},
        })
        write_event({
            "ts": now_iso(), "skill_version": SKILL_VERSION, "mode": "paper",
            "event": "sl_set", "run_id": run_id,
            "sl": {"trigger_price_usd": round(sl_price, 10), "pct": exit_cfg["sl_pct"],
                   "amount_tokens": round(tokens_received, 4),
                   "timeout_hours": exit_cfg["timeout_h"]},
        })

        ever_traded.add(addr)
        open_tokens.add(addr)
        new_paper_runs += 1
        print(f"  [paper] {sym:14} entry=${virtual_entry:.8f}  tokens={tokens_received:.2f}  size=${sizing['size_usd']:.2f}  TP=${tp_price:.8f}  SL=${sl_price:.8f}")

    print(f"\n[summary] new paper runs: {new_paper_runs}  rejected: {len(rejected)}")
    if rejected:
        from collections import Counter
        reasons = Counter(r for _, r in rejected)
        print("[summary] rejection reasons:", dict(reasons))


if __name__ == "__main__":
    main()
