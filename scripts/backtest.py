#!/usr/bin/env python3
"""
Backtest engine: replay 24h of signals through ~25 strategy variants on $10K bankroll.

For each strategy:
- Filter signals (soldRatio, wallet types, signal-row safety fields)
- For each passing signal:
    - Entry at the open of the first 5m bar after signal_ts
    - Walk candles forward: SL hit first, else TP, else timeout
    - Record realized PnL
- Aggregate: n_trades, win_rate, total_pnl_usd, mean_pnl_pct, median_pnl_pct,
  sharpe-equivalent, max_drawdown, best/worst trade.
"""
import json, os, math, time
from collections import defaultdict, OrderedDict

KLINE_DIR = "/tmp/agentic-backtest-klines"
SIG_PATH = "/tmp/agentic-backtest-signals.json"
BANKROLL_USD = 10_000.0
SIM_ENTRY_SLIPPAGE = 0.015      # 1.5%
SIM_EXIT_SLIPPAGE  = 0.015
GAS_PER_TRADE_USD  = 0.05       # solana

# ─────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────
with open(SIG_PATH) as f:
    signals = json.load(f)

klines = {}
for fname in os.listdir(KLINE_DIR):
    addr = fname.replace(".json", "")
    try:
        with open(f"{KLINE_DIR}/{fname}") as f:
            bars = json.load(f)["5m"]
        # sort ascending by ts
        bars = sorted(bars, key=lambda b: int(b["ts"]))
        klines[addr] = [{
            "ts": int(b["ts"]),
            "o": float(b["o"]),
            "h": float(b["h"]),
            "l": float(b["l"]),
            "c": float(b["c"]),
            "vol_usd": float(b.get("volUsd", 0)),
        } for b in bars]
    except Exception:
        pass

print(f"loaded: {len(signals)} signals, {len(klines)} kline series")

# ─────────────────────────────────────────────────────────────
# Strategy definitions
# ─────────────────────────────────────────────────────────────
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
        require_lp_burned=False,    # we don't have lpBurnedPercent in signal row → can't enforce in backtest
    )
    base.update(kw)
    base["id"] = sid
    base["name"] = name
    return base

STRATEGIES = [
    make_strategy("S01","v0.2 default"),
    make_strategy("S02","tight tp/sl",         tp_pct=0.20, sl_pct=-0.10, timeout_h=2),
    make_strategy("S03","wide tp/sl",          tp_pct=0.50, sl_pct=-0.25, timeout_h=8),
    make_strategy("S04","moonshot",            tp_pct=1.00, sl_pct=-0.30, timeout_h=8),
    make_strategy("S05","scalp",               tp_pct=0.10, sl_pct=-0.05, timeout_h=1),
    make_strategy("S06","strong cluster (≥5)", min_wallet_count=5, size_pct=0.15),
    make_strategy("S07","loose cluster (≥2)",  min_wallet_count=2),
    make_strategy("S08","SM only",             wallet_types=["1"]),
    make_strategy("S09","KOL only",            wallet_types=["2"]),
    make_strategy("S10","Whale only",          wallet_types=["3"]),
    make_strategy("S11","very buy-heavy <10%", sold_ratio_max=10),
    make_strategy("S12","permissive sold <50%",sold_ratio_max=50),
    make_strategy("S13","strict top10 < 25%",  max_top10_pct=25),
    make_strategy("S14","small size 5%",       size_pct=0.05),
    make_strategy("S15","big size 20%",        size_pct=0.20),
    make_strategy("S16","big MC > $500K only", min_market_cap=500_000),
    make_strategy("S17","small MC < $100K",    max_market_cap=100_000, tp_pct=0.50, sl_pct=-0.20),
    make_strategy("S18","hold longer 12h",     timeout_h=12),
    make_strategy("S19","TP only (no SL)",     sl_pct=-0.99),
    make_strategy("S20","very tight scalp",    tp_pct=0.05, sl_pct=-0.03, timeout_h=1),
    make_strategy("S21","KOL + permissive",    wallet_types=["2"], sold_ratio_max=50, min_wallet_count=2),
    make_strategy("S22","contrarian sell>70%", sold_ratio_min=70, sold_ratio_max=100),
    make_strategy("S23","SM + tight",          wallet_types=["1"], tp_pct=0.20, sl_pct=-0.10),
    make_strategy("S24","no filter all-in",    min_wallet_count=2, sold_ratio_max=100, min_market_cap=0, min_holders=0, max_top10_pct=100),
    make_strategy("S25","≥4 wallets + wide",   min_wallet_count=4, tp_pct=0.50, sl_pct=-0.20, timeout_h=8),
]

# ─────────────────────────────────────────────────────────────
# Simulation core
# ─────────────────────────────────────────────────────────────
def filter_signal(sig, S):
    if sig["walletType"] not in S["wallet_types"]:
        return False, "walletType"
    if int(sig["triggerWalletCount"]) < S["min_wallet_count"]:
        return False, "wallet_count"
    sr = float(sig["soldRatioPercent"])
    if sr < S["sold_ratio_min"] or sr > S["sold_ratio_max"]:
        return False, "soldRatio"
    t = sig["token"]
    mc = float(t.get("marketCapUsd") or 0)
    if mc < S["min_market_cap"] or mc > S["max_market_cap"]:
        return False, "marketCap"
    if int(t.get("holders") or 0) < S["min_holders"]:
        return False, "holders"
    top10 = float(t.get("top10HolderPercent") or 100)
    if top10 >= S["max_top10_pct"]:
        return False, "top10"
    return True, None


def simulate_trade(sig, S, bars):
    """Walk through bars from signal_ts forward; return (exit_event, exit_price, exit_ts, pnl_pct)."""
    sig_ts = int(sig["timestamp"])
    # find first bar with ts >= sig_ts (the "next" candle after signal)
    entry_bar = None
    entry_idx = None
    for i, b in enumerate(bars):
        if b["ts"] >= sig_ts:
            entry_bar = b
            entry_idx = i
            break
    if entry_bar is None:
        return None  # no data
    entry_price_raw = entry_bar["o"]
    entry_price = entry_price_raw * (1 + SIM_ENTRY_SLIPPAGE)  # buy: paying more
    tp_price = entry_price * (1 + S["tp_pct"])
    sl_price = entry_price * (1 + S["sl_pct"])
    timeout_ts = sig_ts + S["timeout_h"] * 3600 * 1000

    # walk forward starting from the entry bar (use it for SL/TP testing too — within-bar movement)
    for j in range(entry_idx, len(bars)):
        b = bars[j]
        # within-bar order: assume worst-case → check SL first
        if b["l"] <= sl_price:
            exit_price = sl_price * (1 - SIM_EXIT_SLIPPAGE)
            return ("sl_fired", exit_price, b["ts"], exit_price / entry_price - 1)
        if b["h"] >= tp_price:
            exit_price = tp_price * (1 - SIM_EXIT_SLIPPAGE)
            return ("tp_fired", exit_price, b["ts"], exit_price / entry_price - 1)
        if b["ts"] >= timeout_ts:
            exit_price = b["c"] * (1 - SIM_EXIT_SLIPPAGE)
            return ("timeout_close", exit_price, b["ts"], exit_price / entry_price - 1)
    # ran out of bars before any exit fired — assume close at last bar's close
    last = bars[-1]
    exit_price = last["c"] * (1 - SIM_EXIT_SLIPPAGE)
    return ("data_exhausted", exit_price, last["ts"], exit_price / entry_price - 1)


def run_strategy(S, sigs):
    bankroll = BANKROLL_USD
    trades = []
    equity_curve = [bankroll]
    open_tokens = set()  # don't re-enter same token
    for sig in sorted(sigs, key=lambda s: int(s["timestamp"])):
        addr = sig["token"]["tokenAddress"]
        if addr in open_tokens:
            continue
        ok, _why = filter_signal(sig, S)
        if not ok:
            continue
        bars = klines.get(addr)
        if not bars:
            continue
        result = simulate_trade(sig, S, bars)
        if result is None:
            continue
        exit_event, exit_price, exit_ts, pnl_pct = result
        size_usd = bankroll * S["size_pct"]
        pnl_usd = size_usd * pnl_pct - GAS_PER_TRADE_USD * 2  # entry+exit gas
        bankroll += pnl_usd
        trades.append({
            "token": sig["token"]["symbol"],
            "wallet_type": sig["walletType"],
            "wallet_count": int(sig["triggerWalletCount"]),
            "sold_ratio_pct": float(sig["soldRatioPercent"]),
            "market_cap_usd": float(sig["token"].get("marketCapUsd") or 0),
            "size_usd": round(size_usd, 2),
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usd": round(pnl_usd, 4),
            "exit_event": exit_event,
        })
        equity_curve.append(bankroll)
        open_tokens.add(addr)
    return trades, equity_curve


def metrics(trades, equity_curve):
    if not trades:
        return {"n": 0}
    pnls_pct = [t["pnl_pct"] for t in trades]
    pnls_usd = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls_pct if p > 0]
    losses = [p for p in pnls_pct if p <= 0]
    mean_pct = sum(pnls_pct) / len(pnls_pct)
    var = sum((p - mean_pct) ** 2 for p in pnls_pct) / len(pnls_pct)
    std = math.sqrt(var) if var > 0 else 1e-9
    # max drawdown
    peak = equity_curve[0]; max_dd = 0
    for e in equity_curve:
        peak = max(peak, e)
        dd = (peak - e) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    exit_dist = defaultdict(int)
    for t in trades:
        exit_dist[t["exit_event"]] += 1
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "total_pnl_usd": round(sum(pnls_usd), 2),
        "final_bankroll": round(equity_curve[-1], 2),
        "return_pct": round((equity_curve[-1] / BANKROLL_USD - 1) * 100, 2),
        "mean_pnl_pct": round(mean_pct * 100, 2),
        "median_pnl_pct": round(sorted(pnls_pct)[len(pnls_pct)//2] * 100, 2),
        "std_pnl_pct": round(std * 100, 2),
        "sharpe_eq": round(mean_pct / std, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "best_pnl_pct": round(max(pnls_pct) * 100, 2),
        "worst_pnl_pct": round(min(pnls_pct) * 100, 2),
        "exits": dict(exit_dist),
    }


# ─────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────
results = []
for S in STRATEGIES:
    trades, ec = run_strategy(S, signals)
    m = metrics(trades, ec)
    m["id"] = S["id"]
    m["name"] = S["name"]
    m["config"] = {k: S[k] for k in ("tp_pct","sl_pct","timeout_h","size_pct","sold_ratio_max","min_wallet_count","wallet_types","min_market_cap","max_market_cap","max_top10_pct")}
    m["trades"] = trades
    results.append(m)

with open("/tmp/agentic-backtest-results.json","w") as f:
    json.dump(results, f, indent=2)

# Sort by final_bankroll
results.sort(key=lambda r: r.get("final_bankroll", BANKROLL_USD), reverse=True)

# Print summary table
print("\n" + "=" * 120)
print(f"{'ID':<4} {'name':<26} {'n':>4} {'win%':>6} {'tot$':>9} {'ret%':>7} {'mean%':>7} {'med%':>7} {'std%':>7} {'sharpe':>7} {'maxDD%':>7} {'best%':>7} {'worst%':>8}")
print("=" * 120)
for r in results:
    if r["n"] == 0:
        print(f"{r['id']:<4} {r['name']:<26} {'  0':>4}  —")
        continue
    print(f"{r['id']:<4} {r['name']:<26} {r['n']:>4} {r['win_rate']*100:>5.0f}% "
          f"{r['total_pnl_usd']:>+9.2f} {r['return_pct']:>+6.2f}% "
          f"{r['mean_pnl_pct']:>+6.2f}% {r['median_pnl_pct']:>+6.2f}% {r['std_pnl_pct']:>6.2f}% "
          f"{r['sharpe_eq']:>+7.3f} {r['max_drawdown_pct']:>6.2f}% "
          f"{r['best_pnl_pct']:>+6.2f}% {r['worst_pnl_pct']:>+7.2f}%")
print("=" * 120)
print(f"bankroll: ${BANKROLL_USD:,.0f}  entry_slip: {SIM_ENTRY_SLIPPAGE*100:.1f}%  exit_slip: {SIM_EXIT_SLIPPAGE*100:.1f}%  gas: ${GAS_PER_TRADE_USD}/side")
print(f"saved → /tmp/agentic-backtest-results.json")
