#!/usr/bin/env python3
"""Deeper analysis of backtest results: per-feature lift, sample warnings, recommendations."""
import json
from collections import defaultdict

with open("/tmp/agentic-backtest-results.json") as f:
    results = json.load(f)

# Collect every trade across all strategies (with strategy ID)
all_trades = []
for r in results:
    for t in r.get("trades", []):
        t_copy = dict(t)
        t_copy["strategy_id"] = r["id"]
        t_copy["strategy_name"] = r["name"]
        all_trades.append(t_copy)

print(f"total trades across all strategies: {len(all_trades)}")

# Dedup to unique (strategy_id, token) pairs already done. But we want signal-level lift, which requires per-signal aggregation.
# For lift, let me use trades from the "no filter" S24 strategy as the universal corpus — it touched every signal.
s24_trades = [t for t in all_trades if t["strategy_id"] == "S24"]
print(f"\nS24 (universal — every signal traded): {len(s24_trades)} trades")
print(f"  win rate: {100*sum(1 for t in s24_trades if t['pnl_pct']>0)/len(s24_trades):.1f}%")
print(f"  mean pnl_pct: {100*sum(t['pnl_pct'] for t in s24_trades)/len(s24_trades):+.2f}%")

# Per-feature lift: bucket S24 trades by feature
def bucket(value, edges):
    for e in edges:
        if value < e: return f"<{e}"
    return f">={edges[-1]}"

# wallet_type
wt = defaultdict(list)
for t in s24_trades:
    wt[{"1":"SmartMoney","2":"KOL","3":"Whale"}.get(t["wallet_type"], "?")].append(t["pnl_pct"])
print(f"\n--- Lift by wallet_type ---")
for k, pnls in wt.items():
    n = len(pnls); wr = sum(1 for p in pnls if p>0)/n; mp = sum(pnls)/n
    print(f"  {k:14} n={n:>3}  win_rate={wr*100:>5.1f}%  mean_pnl={mp*100:>+6.2f}%")

# wallet_count buckets
wc = defaultdict(list)
for t in s24_trades:
    k = "≥5" if t["wallet_count"]>=5 else ("4" if t["wallet_count"]==4 else ("3" if t["wallet_count"]==3 else "2"))
    wc[k].append(t["pnl_pct"])
print(f"\n--- Lift by wallet_count ---")
for k in ["2","3","4","≥5"]:
    pnls = wc.get(k, [])
    if not pnls: continue
    n = len(pnls); wr = sum(1 for p in pnls if p>0)/n; mp = sum(pnls)/n
    print(f"  wc={k:<4} n={n:>3}  win_rate={wr*100:>5.1f}%  mean_pnl={mp*100:>+6.2f}%")

# sold_ratio buckets
sr = defaultdict(list)
for t in s24_trades:
    s = t["sold_ratio_pct"]
    k = "<10" if s<10 else ("10-30" if s<30 else ("30-50" if s<50 else ("50-70" if s<70 else "70-100")))
    sr[k].append(t["pnl_pct"])
print(f"\n--- Lift by sold_ratio_pct ---")
for k in ["<10","10-30","30-50","50-70","70-100"]:
    pnls = sr.get(k, [])
    if not pnls: continue
    n = len(pnls); wr = sum(1 for p in pnls if p>0)/n; mp = sum(pnls)/n
    print(f"  sold={k:<7} n={n:>3}  win_rate={wr*100:>5.1f}%  mean_pnl={mp*100:>+6.2f}%")

# market_cap buckets
mc = defaultdict(list)
for t in s24_trades:
    m = t["market_cap_usd"]
    if m < 50_000: k="<50K"
    elif m < 200_000: k="50K-200K"
    elif m < 1_000_000: k="200K-1M"
    elif m < 10_000_000: k="1M-10M"
    else: k=">10M"
    mc[k].append(t["pnl_pct"])
print(f"\n--- Lift by market_cap ---")
for k in ["<50K","50K-200K","200K-1M","1M-10M",">10M"]:
    pnls = mc.get(k, [])
    if not pnls: continue
    n = len(pnls); wr = sum(1 for p in pnls if p>0)/n; mp = sum(pnls)/n
    print(f"  mc={k:<8} n={n:>3}  win_rate={wr*100:>5.1f}%  mean_pnl={mp*100:>+6.2f}%")

# Exit-event distribution overall
ed = defaultdict(int)
for t in s24_trades:
    ed[t["exit_event"]] += 1
total = sum(ed.values())
print(f"\n--- Exit distribution (S24, all 97 trades) ---")
for k, v in sorted(ed.items(), key=lambda x: -x[1]):
    print(f"  {k:<18} {v:>3}  {100*v/total:>5.1f}%")

# Top winners and losers (S24)
sorted_trades = sorted(s24_trades, key=lambda t: -t["pnl_pct"])
print(f"\n--- Top 5 best trades (S24 universe) ---")
for t in sorted_trades[:5]:
    print(f"  {t['token']:14} wt={t['wallet_type']} wc={t['wallet_count']} sold={t['sold_ratio_pct']:>5}% mc=${t['market_cap_usd']:>10,.0f}  pnl={t['pnl_pct']*100:+.2f}%  exit={t['exit_event']}")
print(f"\n--- Top 5 worst trades (S24 universe) ---")
for t in sorted_trades[-5:]:
    print(f"  {t['token']:14} wt={t['wallet_type']} wc={t['wallet_count']} sold={t['sold_ratio_pct']:>5}% mc=${t['market_cap_usd']:>10,.0f}  pnl={t['pnl_pct']*100:+.2f}%  exit={t['exit_event']}")
