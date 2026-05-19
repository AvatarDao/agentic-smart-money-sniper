#!/usr/bin/env python3
"""
run_backtest_daily.py — daily backtest runner. Pulls 24h of signals, fetches
klines, runs the 25-strategy sweep, and archives results to
~/.agentic-sniper/backtest/YYYY-MM-DD/.

Designed for launchd: idempotent, self-contained, fails closed on network
issues, writes a progress log to ~/.agentic-sniper/backtest.log.

Schedule via scripts/launchd/com.agentic-sniper.backtest.plist (daily 04:00).
"""
import json, os, math, subprocess, sys, time
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.expanduser("~/.agentic-sniper/backtest")
LOG = os.path.expanduser("~/.agentic-sniper/backtest.log")
BANKROLL_USD = 10_000.0
SIM_ENTRY_SLIPPAGE = 0.015
SIM_EXIT_SLIPPAGE  = 0.015
GAS_PER_TRADE_USD  = 0.05

# Note: when launchd kicks this off in a fresh shell, PATH may not include ~/.local/bin
os.environ["PATH"] = f"{os.path.expanduser('~/.local/bin')}:/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH','')}"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def cli(args, tries=3, timeout=45):
    for t in range(tries):
        try:
            out = subprocess.run(["onchainos"] + args, capture_output=True, text=True, timeout=timeout)
            d = json.loads(out.stdout)
            if d.get("ok"):
                return d.get("data")
            log(f"  [warn] cli !ok try{t+1}: {str(d.get('error',''))[:80]}")
        except Exception as e:
            log(f"  [warn] try{t+1}: {e}")
        time.sleep(2 + t * 2)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Step 1 — pull signals
# ────────────────────────────────────────────────────────────────────────────
def pull_signals():
    all_sigs = []
    cursor = None
    pages = 0
    TS_NOW_MS = time.time() * 1000
    HORIZON_MS = 24 * 3600 * 1000
    while pages < 30:
        args = ["signal","list","--chain","solana",
                "--wallet-type","1,2,3","--min-address-count","2","--limit","100"]
        if cursor: args += ["--cursor", cursor]
        rows = cli(args)
        if rows is None or not rows:
            break
        pages += 1
        oldest = int(rows[-1].get("timestamp", 0))
        all_sigs.extend(rows)
        cursor = rows[-1].get("cursor")
        log(f"  page {pages}: +{len(rows)}  total={len(all_sigs)}  oldest_age_min={(TS_NOW_MS-oldest)/60000:.0f}")
        if oldest and (TS_NOW_MS - oldest) > HORIZON_MS:
            break
        if not cursor:
            break
    # dedup by (token, walletType) — keep latest
    seen = {}
    for r in all_sigs:
        k = (r["token"]["tokenAddress"], r["walletType"])
        if k not in seen or int(r["timestamp"]) > int(seen[k]["timestamp"]):
            seen[k] = r
    return list(seen.values())


# ────────────────────────────────────────────────────────────────────────────
# Step 2 — fetch klines (with cache)
# ────────────────────────────────────────────────────────────────────────────
def fetch_klines(tokens, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    klines = {}
    done = 0; failed = 0
    for i, addr in enumerate(tokens):
        cache = f"{out_dir}/{addr}.json"
        if os.path.exists(cache):
            with open(cache) as f: klines[addr] = json.load(f)
            done += 1
            continue
        bars = cli(["market","kline","--chain","solana","--address",addr,"--bar","5m","--limit","299"])
        if bars is None:
            failed += 1
            continue
        with open(cache, "w") as f: json.dump(bars, f)
        klines[addr] = bars
        done += 1
        if (i+1) % 20 == 0:
            log(f"  klines [{i+1}/{len(tokens)}] done={done} failed={failed}")
    log(f"  klines: total={len(tokens)} cached={done} failed={failed}")
    return klines


# ────────────────────────────────────────────────────────────────────────────
# Step 3 — strategy matrix (same as backtest.py)
# ────────────────────────────────────────────────────────────────────────────
def make_strategy(sid, name, **kw):
    base = dict(
        wallet_types=["1","2","3"],
        min_wallet_count=3,
        sold_ratio_max=30,
        sold_ratio_min=0,
        min_holders=50,
        max_top10_pct=50,
        min_market_cap=20000,
        max_market_cap=10_000_000_000,
        tp_pct=0.30,
        sl_pct=-0.15,
        timeout_h=4,
        size_pct=0.09,
    )
    base.update(kw)
    base["id"] = sid
    base["name"] = name
    return base


def strategy_matrix():
    return [
        # v0.2 baseline
        make_strategy("S01","v0.2 default"),
        # v0.3 — all 6 changes
        make_strategy("V03","v0.3 default",
                      sold_ratio_max=15, wallet_types=["1","2"],
                      min_market_cap=200_000,
                      tp_pct=0.50, sl_pct=-0.20, timeout_h=6),
        # ablation: each single v0.3 change vs v0.2 baseline
        make_strategy("A01","+R11 ($200K MC) only", min_market_cap=200_000),
        make_strategy("A02","-whales only", wallet_types=["1","2"]),
        make_strategy("A03","soldRatio<15 only", sold_ratio_max=15),
        make_strategy("A04","TP+50/SL-20 only", tp_pct=0.50, sl_pct=-0.20),
        make_strategy("A05","timeout=6h only", timeout_h=6),
        # additional grid
        make_strategy("G01","v0.3 + size 15%", sold_ratio_max=15, wallet_types=["1","2"],
                      min_market_cap=200_000, tp_pct=0.50, sl_pct=-0.20, timeout_h=6, size_pct=0.15),
        make_strategy("G02","v0.3 + size 5%", sold_ratio_max=15, wallet_types=["1","2"],
                      min_market_cap=200_000, tp_pct=0.50, sl_pct=-0.20, timeout_h=6, size_pct=0.05),
        make_strategy("G03","v0.3 + tighter sold<10", sold_ratio_max=10, wallet_types=["1","2"],
                      min_market_cap=200_000, tp_pct=0.50, sl_pct=-0.20, timeout_h=6),
        make_strategy("G04","v0.3 + MC≥$500K", sold_ratio_max=15, wallet_types=["1","2"],
                      min_market_cap=500_000, tp_pct=0.50, sl_pct=-0.20, timeout_h=6),
        make_strategy("G05","v0.3 + MC≥$1M", sold_ratio_max=15, wallet_types=["1","2"],
                      min_market_cap=1_000_000, tp_pct=0.50, sl_pct=-0.20, timeout_h=6),
        # counter-factuals (sanity)
        make_strategy("C01","no filter (sanity)", min_wallet_count=2, sold_ratio_max=100,
                      min_market_cap=0, min_holders=0, max_top10_pct=100),
        make_strategy("C02","contrarian sold>70", sold_ratio_min=70, sold_ratio_max=100),
    ]


# ────────────────────────────────────────────────────────────────────────────
# Step 4 — simulate
# ────────────────────────────────────────────────────────────────────────────
def filter_signal(sig, S):
    if sig["walletType"] not in S["wallet_types"]:
        return False
    if int(sig["triggerWalletCount"]) < S["min_wallet_count"]:
        return False
    sr = float(sig["soldRatioPercent"])
    if sr < S["sold_ratio_min"] or sr > S["sold_ratio_max"]:
        return False
    t = sig["token"]
    mc = float(t.get("marketCapUsd") or 0)
    if mc < S["min_market_cap"] or mc > S["max_market_cap"]:
        return False
    if int(t.get("holders") or 0) < S["min_holders"]:
        return False
    top10 = float(t.get("top10HolderPercent") or 100)
    if top10 >= S["max_top10_pct"]:
        return False
    return True


def simulate(sig, S, bars):
    sig_ts = int(sig["timestamp"])
    bars = sorted(({"ts":int(b["ts"]),"o":float(b["o"]),"h":float(b["h"]),"l":float(b["l"]),"c":float(b["c"])} for b in bars), key=lambda b:b["ts"])
    eb = next((i for i,b in enumerate(bars) if b["ts"] >= sig_ts), None)
    if eb is None: return None
    entry = bars[eb]["o"] * (1 + SIM_ENTRY_SLIPPAGE)
    tp = entry * (1 + S["tp_pct"]); sl = entry * (1 + S["sl_pct"])
    timeout = sig_ts + S["timeout_h"]*3600*1000
    for j in range(eb, len(bars)):
        b = bars[j]
        if b["l"] <= sl:
            return ("sl_fired", sl*(1-SIM_EXIT_SLIPPAGE)/entry - 1)
        if b["h"] >= tp:
            return ("tp_fired", tp*(1-SIM_EXIT_SLIPPAGE)/entry - 1)
        if b["ts"] >= timeout:
            return ("timeout_close", b["c"]*(1-SIM_EXIT_SLIPPAGE)/entry - 1)
    last = bars[-1]
    return ("data_exhausted", last["c"]*(1-SIM_EXIT_SLIPPAGE)/entry - 1)


def run_strategy(S, sigs, klines):
    bankroll = BANKROLL_USD
    trades = []
    opened = set()
    for sig in sorted(sigs, key=lambda s: int(s["timestamp"])):
        addr = sig["token"]["tokenAddress"]
        if addr in opened: continue
        if not filter_signal(sig, S): continue
        bars = klines.get(addr)
        if not bars: continue
        r = simulate(sig, S, bars)
        if r is None: continue
        exit_evt, pnl_pct = r
        size = bankroll * S["size_pct"]
        pnl_usd = size * pnl_pct - GAS_PER_TRADE_USD*2
        bankroll += pnl_usd
        trades.append({
            "token": sig["token"]["symbol"],
            "wallet_type": sig["walletType"],
            "wallet_count": int(sig["triggerWalletCount"]),
            "sold_ratio_pct": float(sig["soldRatioPercent"]),
            "market_cap_usd": float(sig["token"].get("marketCapUsd") or 0),
            "size_usd": round(size, 2),
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 4),
            "exit_event": exit_evt,
        })
        opened.add(addr)
    return trades, bankroll


def metrics(trades, final):
    if not trades:
        # v0.3.1 fix: include all keys the summary loop reads, prevents KeyError
        return {
            "n": 0, "final_bankroll": BANKROLL_USD, "return_pct": 0.0,
            "win_rate": 0.0, "total_pnl_usd": 0.0,
            "mean_pnl_pct": 0.0, "std_pnl_pct": 0.0, "sharpe_eq": 0.0,
            "best_pnl_pct": 0.0, "worst_pnl_pct": 0.0, "exits": {},
        }
    pnls_pct = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls_pct if p > 0]
    mean = sum(pnls_pct)/len(pnls_pct)
    var = sum((p-mean)**2 for p in pnls_pct)/len(pnls_pct)
    std = math.sqrt(var) if var > 0 else 1e-9
    exits = defaultdict(int)
    for t in trades: exits[t["exit_event"]] += 1
    return {
        "n": len(trades),
        "win_rate": round(len(wins)/len(trades), 4),
        "total_pnl_usd": round(sum(t["pnl_usd"] for t in trades), 2),
        "final_bankroll": round(final, 2),
        "return_pct": round((final/BANKROLL_USD - 1)*100, 2),
        "mean_pnl_pct": round(mean*100, 2),
        "std_pnl_pct": round(std*100, 2),
        "sharpe_eq": round(mean/std, 3),
        "best_pnl_pct": round(max(pnls_pct)*100, 2),
        "worst_pnl_pct": round(min(pnls_pct)*100, 2),
        "exits": dict(exits),
    }


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = f"{ROOT}/{today}"
    os.makedirs(out_dir, exist_ok=True)
    log(f"=== backtest {today} → {out_dir} ===")

    log("[1/4] pulling signals…")
    sigs = pull_signals()
    log(f"  {len(sigs)} unique (token, walletType) signals")
    with open(f"{out_dir}/signals.json","w") as f: json.dump(sigs, f)

    tokens = sorted({s["token"]["tokenAddress"] for s in sigs})
    log(f"[2/4] fetching klines for {len(tokens)} tokens…")
    klines = fetch_klines(tokens, f"{out_dir}/klines")

    log("[3/4] running strategy matrix…")
    results = []
    for S in strategy_matrix():
        trades, final = run_strategy(S, sigs, klines)
        m = metrics(trades, final)
        m["id"] = S["id"]; m["name"] = S["name"]
        m["config"] = {k: S[k] for k in ("tp_pct","sl_pct","timeout_h","size_pct","sold_ratio_max","min_wallet_count","wallet_types","min_market_cap")}
        m["trades"] = trades
        results.append(m)

    with open(f"{out_dir}/results.json","w") as f: json.dump(results, f, indent=2)

    log("[4/4] writing summary…")
    results_sorted = sorted(results, key=lambda r: r.get("final_bankroll", BANKROLL_USD), reverse=True)
    lines = [f"# Backtest {today}\n", f"Bankroll: ${BANKROLL_USD:,.0f}  Signals: {len(sigs)}  Tokens: {len(tokens)}  Strategies: {len(results)}\n"]
    lines.append("\n| ID | name | n | win% | total $ | ret% | mean% | std% | sharpe | best% | worst% | exits |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in results_sorted:
        if r["n"] == 0:
            lines.append(f"| {r['id']} | {r['name']} | 0 | — | 0 | 0 | — | — | — | — | — | — |")
            continue
        lines.append(f"| {r['id']} | {r['name']} | {r['n']} | {r['win_rate']*100:.0f}% | {r['total_pnl_usd']:+.2f} | {r['return_pct']:+.2f}% | {r['mean_pnl_pct']:+.2f}% | {r['std_pnl_pct']:.2f}% | {r['sharpe_eq']:+.3f} | {r['best_pnl_pct']:+.2f}% | {r['worst_pnl_pct']:+.2f}% | {r['exits']} |")
    with open(f"{out_dir}/report.md","w") as f: f.write("\n".join(lines))

    # quick stdout banner
    log("=== top 5 by final bankroll ===")
    for r in results_sorted[:5]:
        log(f"  {r['id']:<5} {r['name']:<28} n={r['n']:>3} ret={r['return_pct']:+.2f}% mean={r['mean_pnl_pct']:+.2f}%")
    log(f"=== done. archive: {out_dir} ===\n")


if __name__ == "__main__":
    main()
