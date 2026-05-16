#!/usr/bin/env python3
"""Page through signal API as far as the cursor allows. Retry on TLS errors."""
import json, subprocess, time, sys

all_sigs = []
cursor = None
pages = 0
TS_NOW_MS = time.time() * 1000
TARGET_HORIZON_MS = 24 * 3600 * 1000  # 24h back

def call(args, tries=3):
    for t in range(tries):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=45)
            d = json.loads(out.stdout)
            if d.get("ok"):
                return d
            print(f"    [warn] cli !ok try{t+1}: {d.get('error','?')[:80]}", file=sys.stderr)
        except Exception as e:
            print(f"    [warn] try{t+1}: {e}", file=sys.stderr)
        time.sleep(2 + t * 2)
    return None

while pages < 50:
    args = ["onchainos","signal","list","--chain","solana",
            "--wallet-type","1,2,3","--min-address-count","2","--limit","100"]
    if cursor: args += ["--cursor", cursor]
    d = call(args)
    if d is None:
        print(f"  page {pages+1}: gave up after retries; stopping")
        break
    rows = d.get("data", [])
    if not rows:
        print(f"  page {pages+1}: empty — end of history")
        break
    pages += 1
    oldest_ts = int(rows[-1].get("timestamp", 0))
    age_min = (TS_NOW_MS - oldest_ts) / 60000 if oldest_ts else -1
    all_sigs.extend(rows)
    cursor = rows[-1].get("cursor")
    print(f"  page {pages}: +{len(rows)}  oldest_age_min={age_min:.0f}  total={len(all_sigs)}")
    if oldest_ts and (TS_NOW_MS - oldest_ts) > TARGET_HORIZON_MS:
        print(f"  hit 24h horizon — stopping")
        break
    if not cursor:
        print(f"  no cursor — stopping")
        break

print(f"\ntotal signals pulled: {len(all_sigs)}")

# Dedup keeping the LATEST occurrence per (token, walletType) — most recent state of that smart-money cluster
seen = {}
for r in all_sigs:
    k = (r["token"]["tokenAddress"], r["walletType"])
    if k not in seen or int(r["timestamp"]) > int(seen[k]["timestamp"]):
        seen[k] = r
unique = list(seen.values())
print(f"unique (token, walletType): {len(unique)}")
print(f"unique tokens: {len(set(r['token']['tokenAddress'] for r in unique))}")

import collections
sr_bucket = collections.Counter()
wt_bucket = collections.Counter()
for r in unique:
    sr = float(r["soldRatioPercent"])
    b = "<10" if sr<10 else ("10-30" if sr<30 else ("30-50" if sr<50 else ">50"))
    sr_bucket[b] += 1
    wt_bucket[{"1":"SM","2":"KOL","3":"WHL"}.get(r["walletType"], "?")] += 1
print(f"soldRatio buckets: {dict(sr_bucket)}")
print(f"wallet-type buckets: {dict(wt_bucket)}")

with open("/tmp/agentic-backtest-signals.json", "w") as f:
    json.dump(unique, f)
print(f"\nsaved → /tmp/agentic-backtest-signals.json")
