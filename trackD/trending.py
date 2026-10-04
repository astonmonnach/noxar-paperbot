"""Snapshot Solana trending / new pools, so the trending-listing effect can be tested.

THE HYPOTHESIS (Thomas's, 2026-10-04): inflow -> the coin lands on a trending
list -> more eyes -> more transactions -> price rises. If that loop is real, two
things must be true and both are measurable:

  1. ENTRY PAYS. A coin's return after it enters the list beats a matched
     control that never entered.
  2. ENTRY IS PREDICTABLE. The transaction/inflow trajectory in the snapshots
     BEFORE entry separates coins that are about to enter from ones that are not.

(2) is the valuable half, because (1) alone is unexploitable - by the time you
read the list, everyone else has too.

This only works forward. Reading today's trending page tells you nothing: it is
a list of things that already won, which is the survivorship trap that
contaminated every historical test in this repo. A snapshot taken every few
minutes has no such bias, because it records the coins that were about to fail
alongside the ones that were about to run.

Costs nothing: GeckoTerminal needs no key.

    python -m trackD.trending --once
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
OUT = Path("data/trending/snapshots.jsonl")
PAUSE = 2.2


def get(url: str, tries: int = 3):
    for a in range(tries):
        try:
            r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(r, timeout=30) as x:
                return json.loads(x.read())
        except Exception:
            if a < tries - 1:
                time.sleep(4)
                continue
            return None
    return None


def rows(body, source: str, now: str) -> list[dict]:
    out = []
    for i, p in enumerate((body or {}).get("data", [])):
        a = p.get("attributes") or {}
        tx = a.get("transactions") or {}
        pc = a.get("price_change_percentage") or {}

        def txn(k):
            d = tx.get(k) or {}
            return (d.get("buys") or 0) + (d.get("sells") or 0)

        def buys(k):
            return (tx.get(k) or {}).get("buys") or 0

        out.append({
            "t": now, "source": source, "rank": i,
            "pool": p.get("id", "").split("_")[-1],
            "name": a.get("name"),
            "px": float(a.get("base_token_price_usd") or 0),
            "mcap": float(a.get("market_cap_usd") or 0) if a.get("market_cap_usd") else None,
            "fdv": float(a.get("fdv_usd") or 0) if a.get("fdv_usd") else None,
            "liq": float(a.get("reserve_in_usd") or 0),
            "created": a.get("pool_created_at"),
            "vol_h24": float((a.get("volume_usd") or {}).get("h24") or 0),
            "tx_m5": txn("m5"), "tx_m15": txn("m15"), "tx_h1": txn("h1"),
            "tx_h24": txn("h24"),
            "buys_m5": buys("m5"), "buys_m15": buys("m15"), "buys_h1": buys("h1"),
            "pc_m5": pc.get("m5"), "pc_m15": pc.get("m15"), "pc_h1": pc.get("h1"),
            "pc_h6": pc.get("h6"), "pc_h24": pc.get("h24"),
        })
    return out


def snapshot() -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    got = []
    for path, src in (("/trending_pools?page=1", "trending"),
                      ("/trending_pools?page=2", "trending"),
                      ("/new_pools?page=1", "new"),
                      ("/pools?page=1&sort=h24_volume_usd_desc", "volume")):
        got += rows(get(f"{GT}{path}"), src, now)
        time.sleep(PAUSE)
    if not got:
        print("no data")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        for r in got:
            f.write(json.dumps(r) + "\n")
    by = {}
    for r in got:
        by[r["source"]] = by.get(r["source"], 0) + 1
    print(f"{now}  {len(got)} rows  {by}")
    return len(got)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0)
    a = ap.parse_args()
    if a.loop:
        while True:
            snapshot()
            time.sleep(a.loop)
    else:
        snapshot()


if __name__ == "__main__":
    main()
