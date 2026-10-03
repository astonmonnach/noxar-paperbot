"""Read the paper bot's fill log and report what it has actually done.

Only rows from the live run count. The first test runs were made with --dry
before that flag was honoured by the logger, so they are filtered out by time.

    python -m trackD.report
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

FILLS = Path("data/trackd/fills.jsonl")
STATE = Path("data/trackd/state.json")
LIVE_FROM = "2026-10-03T21:18"


def main() -> None:
    if not FILLS.exists():
        raise SystemExit("no fills yet")
    rows = [json.loads(l) for l in FILLS.read_text().splitlines() if l.strip()]
    df = pd.DataFrame(rows)
    df = df[df["t"] >= LIVE_FROM]
    if df.empty:
        raise SystemExit("no live fills yet")
    df["t"] = pd.to_datetime(df["t"], utc=True)
    ent = df[df["event"] == "entry"]
    ex = df[df["event"] == "exit"] if "exit" in set(df["event"]) else df.iloc[0:0]

    run_h = (datetime.now(timezone.utc) - df["t"].min()).total_seconds() / 3600
    print(f"running {run_h:.1f}h | {len(ent)} entries | {len(ex)} exits\n")

    if STATE.exists():
        s = json.loads(STATE.read_text())
        print(f"equity ${s['equity']:.2f}  cash ${s['cash']:.2f}  "
              f"open {len(s['open'])}  closed {s['closed']}  "
              f"realised ${s['realised']:+.2f}")
        print(f"return {s['equity']/300-1:+.2%} on $300\n")

    if not ent.empty:
        print(f"entries: median liquidity ${ent['liq'].median():,.0f}  "
              f"median age {ent['age_h'].median():.0f}h  "
              f"{ent['name'].nunique()} distinct names")

    if ex.empty:
        print("\nNo exits yet. Positions run to a -35% stop or a 72h time stop,")
        print("so the first exits land ~3 days after the first entries.")
        return

    r = ex["exit_px"] / ex["entry_px"] - 1
    print(f"\nclosed trades: win {(ex['pnl'] > 0).mean():.1%}  "
          f"mean {r.mean():+.2%}  median {r.median():+.2%}")
    print(f"  best {r.max():+.1%}  worst {r.min():+.1%}  "
          f"net ${ex['pnl'].sum():+.2f}")
    print(f"  stopped out {(ex['reason'] == 'stop').mean():.1%}  "
          f"timed out {(ex['reason'] == 'time').mean():.1%}")
    print(f"  P(>+50%) {(r > 0.5).mean():.1%}   P(>+100%) {(r > 1.0).mean():.1%}")
    if len(ex) >= 20:
        boot = [np.mean(np.random.choice(r, len(r))) for _ in range(2000)]
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"  mean 95% CI [{lo:+.2%}, {hi:+.2%}] -> "
              f"{'positive' if lo > 0 else 'not distinguishable from zero'}")
    else:
        print(f"  (need ~20+ closed trades before a CI means anything; "
              f"have {len(ex)})")


if __name__ == "__main__":
    main()
