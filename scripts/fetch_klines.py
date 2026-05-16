#!/usr/bin/env python3
"""Fetch 5m and 1m kline data for each candidate token; cache to disk."""
import json, subprocess, time, os, sys

SIG_PATH = "/tmp/agentic-backtest-signals.json"
KLINE_DIR = "/tmp/agentic-backtest-klines"
os.makedirs(KLINE_DIR, exist_ok=True)

with open(SIG_PATH) as f:
    sigs = json.load(f)

# Keep tokens that have AT LEAST ONE signal with soldRatio < 50% (so loosest buy strategy could trade)
# Actually pull ALL — gives data for sell-side strategies too. We have only 97 tokens.
tokens = sorted({s["token"]["tokenAddress"] for s in sigs})
print(f"fetching klines for {len(tokens)} tokens...")

def call(args, tries=3, timeout=30):
    for t in range(tries):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            d = json.loads(out.stdout)
            if d.get("ok"):
                return d.get("data", [])
        except Exception as e:
            pass
        time.sleep(1 + t)
    return None

done = 0; failed = 0
for i, addr in enumerate(tokens):
    cache = f"{KLINE_DIR}/{addr}.json"
    if os.path.exists(cache):
        done += 1
        continue
    # 5m bars, 299 limit → 1495 min = ~25h
    k5m = call(["onchainos","market","kline","--chain","solana","--address",addr,"--bar","5m","--limit","299"])
    if k5m is None:
        print(f"  [{i+1}/{len(tokens)}] {addr[:12]}... FAIL")
        failed += 1
        continue
    with open(cache, "w") as f:
        json.dump({"5m": k5m}, f)
    done += 1
    if (i+1) % 10 == 0:
        print(f"  [{i+1}/{len(tokens)}] cached so far: {done}  failed: {failed}")

print(f"\nfinal: cached={done}  failed={failed}  total_tokens={len(tokens)}")
