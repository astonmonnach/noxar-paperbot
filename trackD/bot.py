"""Paper-trading memecoin bot. Free data, no keys, no money at risk.

WHY IT IS BUILT THIS WAY
Everything measured on 2026-10-03 says the same thing: no observable price or
volume state in this market buys directional edge - the upside/downside
excursion ratio sits near 1.15 no matter what you condition on. Copying
profitable wallets captured -2.4% in Thomas's own July forward test, and 2.3%
on the moves that mattered. Across his 48-wallet screen, USD deployed per trade
correlates +0.684 with profit while being early correlates -0.006.

So this bot does not predict. It takes many small shots, never dies, and lets
the right tail do the work:
  - equal-weight tiny clips, so no single coin can hurt the account
  - a hard stop, because the left tail is what kills small accounts
  - NO take profit, because capping gains removes the only outcome that pays
  - a cap on concurrent positions and on daily deployment

It runs in PAPER mode and writes every fill to disk. That log is the only honest
way to answer the question the historical data cannot: forward data has no
survivorship bias in it.

    python -m trackD.bot --once        # single pass, prints what it would do
    python -m trackD.bot --loop 300    # run continuously, 5-minute cycle
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import urllib.request

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
STATE = Path("data/trackd/state.json")
FILLS = Path("data/trackd/fills.jsonl")
PAUSE = 2.2  # GeckoTerminal free tier is ~30 calls/min

# --- risk rules, fixed before the bot ever ran -------------------------------
START_EQUITY = 300.0
CLIP_FRAC = 0.02        # 2% of starting equity per shot -> ~50 shots of runway
MAX_OPEN = 15
STOP = -0.35            # hard stop, applies until the trail arms
TRAIL_ARM = 0.50        # trail only arms once the position is +50%
TRAIL = 0.30            # then exit 30% below the high-water mark
# Measured 2026-10-03: a bare 72h time stop gives back ~100% of the best move a
# position ever showed (MFE captured -0.8%). Arming a 30% trail at +50% lifts
# that to 21.2% while leaving the +50% hit rate alone and the mean unchanged.
# It costs about a third of the >+100% rate. It changes the SHAPE of outcomes,
# it does not create edge - every exit rule tested still has a negative mean.
TIME_STOP_H = 72        # give the right tail time to show up
MAX_NEW_PER_CYCLE = 3
COST_SIDE = 0.0025      # direct Jupiter, per side
# universe gates: liquid enough to exit, old enough not to be a fresh rug
MIN_LIQ, MAX_LIQ = 20_000, 400_000
MAX_AGE_H = 24 * 120     # nothing older than ~4 months; majors are years old
# Never take a major or a stable as the position. A lottery-ticket bot holding
# SOL/USDC has no right tail at all - it just pays fees.
MAJORS = {"SOL", "WSOL", "USDC", "USDT", "WETH", "ETH", "WBTC", "BTC", "JUP",
          "JITOSOL", "MSOL", "BSOL", "JLP", "PYUSD", "USDE", "WNEAR", "NEAR",
          "RAY", "BONK", "USDG", "EURC", "CBBTC", "JTO", "W", "INF"}
QUOTES_OK = {"SOL", "WSOL", "USDC", "USDT"}   # price must be in a real quote
MIN_AGE_H = 24
MIN_VOL24 = 5_000


def get(url: str, tries: int = 3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "trackD"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if a < tries - 1:
                time.sleep(4)
                continue
            return None
    return None


@dataclass
class Position:
    pool: str
    name: str
    entry_px: float
    entry_at: str
    size_usd: float
    stop_px: float
    base: str = ""
    last_px: float = 0.0
    last_px_at: str = ""
    peak_px: float = 0.0

    def age_h(self) -> float:
        t = datetime.fromisoformat(self.entry_at)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"equity": START_EQUITY, "cash": START_EQUITY, "open": {},
            "closed": 0, "realised": 0.0, "started": datetime.now(timezone.utc).isoformat()}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def log_fill(rec: dict, dry: bool = False) -> None:
    if dry:          # a --dry test run must not pollute the real fill log
        return
    FILLS.parent.mkdir(parents=True, exist_ok=True)
    with FILLS.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def universe() -> list[dict]:
    """Candidate pools: liquid enough to exit, not a fresh launch."""
    out, seen = [], set()
    for dex in ("raydium", "pumpswap", "meteora"):
        for page in (1, 2):
            b = get(f"{GT}/dexes/{dex}/pools?page={page}&sort=h24_volume_usd_desc")
            for p in (b or {}).get("data", []):
                a = p["attributes"]
                pool = p["id"].split("_")[-1]
                if pool in seen:
                    continue
                seen.add(pool)
                liq = float(a.get("reserve_in_usd") or 0)
                vol = float((a.get("volume_usd") or {}).get("h24") or 0)
                created = a.get("pool_created_at")
                try:
                    age = (datetime.now(timezone.utc)
                           - datetime.fromisoformat(created.replace("Z", "+00:00"))
                           ).total_seconds() / 3600
                except Exception:
                    age = 0.0
                nm = str(a.get("name") or "")
                parts = [x.strip().upper() for x in nm.split("/")]
                base_sym = parts[0] if parts else ""
                quote_sym = parts[1] if len(parts) > 1 else ""
                if (MIN_LIQ <= liq <= MAX_LIQ and vol >= MIN_VOL24
                        and MIN_AGE_H <= age <= MAX_AGE_H
                        and base_sym not in MAJORS
                        and quote_sym in QUOTES_OK):
                    base = (((p.get("relationships") or {}).get("base_token")
                             or {}).get("data") or {}).get("id", pool)
                    out.append({"pool": pool, "name": a.get("name"), "liq": liq,
                                "vol24": vol, "age_h": age, "base": base,
                                "px": float(a.get("base_token_price_usd") or 0)})
            time.sleep(PAUSE)
    return out


def price(pool: str) -> float | None:
    b = get(f"{GT}/pools/{pool}")
    a = ((b or {}).get("data") or {}).get("attributes") or {}
    p = a.get("base_token_price_usd")
    return float(p) if p else None


def cycle(state: dict, dry: bool) -> None:
    now = datetime.now(timezone.utc)
    open_pos = {k: Position(**v) for k, v in state["open"].items()}

    # 1. manage what is already on
    for key, pos in list(open_pos.items()):
        px = price(pos.pool)
        time.sleep(PAUSE)
        if px is None or px <= 0:
            continue
        pos.last_px = px
        pos.last_px_at = now.isoformat()
        pos.peak_px = max(pos.peak_px or pos.entry_px, px)
        # the trail only arms once the position has actually run
        floor = pos.stop_px
        armed = pos.peak_px >= pos.entry_px * (1 + TRAIL_ARM)
        if armed:
            floor = max(floor, pos.peak_px * (1 - TRAIL))
        reason = None
        if px <= floor:
            reason = "trail" if armed else "stop"
        elif pos.age_h() >= TIME_STOP_H:
            reason = "time"
        if reason:
            gross = pos.size_usd * (px / pos.entry_px)
            net = gross * (1 - COST_SIDE)
            pnl = net - pos.size_usd
            state["cash"] += net
            state["realised"] += pnl
            state["closed"] += 1
            del open_pos[key]
            rec = {"t": now.isoformat(), "event": "exit", "reason": reason,
                   "pool": pos.pool, "name": pos.name, "entry_px": pos.entry_px,
                   "exit_px": px, "size_usd": pos.size_usd, "pnl": pnl}
            log_fill(rec, dry)
            print(f"  EXIT  {pos.name[:22]:24} {reason:5} "
                  f"{(px/pos.entry_px-1)*100:+7.1f}%  pnl ${pnl:+.2f}")

    # 2. open new shots
    room = MAX_OPEN - len(open_pos)
    if room > 0:
        held_bases = {p.base for p in open_pos.values()}
        cands = [c for c in universe()
                 if c["pool"] not in open_pos and c["px"] > 0
                 and c["base"] not in held_bases]
        # no prediction: take the ones with the most room to move, tie-broken
        # by liquidity so an exit is possible
        cands.sort(key=lambda c: c["vol24"] / max(c["liq"], 1), reverse=True)
        clip = START_EQUITY * CLIP_FRAC
        taken = 0
        for c in cands:
            if taken >= min(room, MAX_NEW_PER_CYCLE) or state["cash"] < clip:
                break
            if c["base"] in held_bases:   # one position per TOKEN, not per pool
                continue
            held_bases.add(c["base"])
            taken += 1
            fill = c["px"] * (1 + COST_SIDE)
            pos = Position(pool=c["pool"], name=str(c["name"]), entry_px=fill,
                           entry_at=now.isoformat(), size_usd=clip,
                           stop_px=fill * (1 + STOP), base=c["base"],
                           last_px=c["px"], last_px_at=now.isoformat(),
                           peak_px=fill)
            open_pos[c["pool"]] = pos
            state["cash"] -= clip
            log_fill({"t": now.isoformat(), "event": "entry", "pool": c["pool"],
                      "name": c["name"], "px": fill, "size_usd": clip,
                      "liq": c["liq"], "age_h": c["age_h"]}, dry)
            print(f"  ENTRY {str(c['name'])[:22]:24} ${clip:.2f} @ {fill:.3e}  "
                  f"liq ${c['liq']:,.0f}")

    state["open"] = {k: asdict(v) for k, v in open_pos.items()}
    mtm = sum(p.size_usd * (p.last_px / p.entry_px if p.last_px > 0 else 1.0)
              for p in open_pos.values())
    state["equity"] = state["cash"] + mtm
    state["unrealised"] = mtm - sum(p.size_usd for p in open_pos.values())
    if not dry:
        save_state(state)
    print(f"  -- equity ${state['equity']:.2f} | cash ${state['cash']:.2f} | "
          f"open {len(open_pos)} | closed {state['closed']} | "
          f"realised ${state['realised']:+.2f} | "
          f"unrealised ${state.get('unrealised', 0.0):+.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0, help="seconds between cycles")
    ap.add_argument("--dry", action="store_true", help="do not persist state")
    a = ap.parse_args()
    state = load_state()
    print(f"PAPER bot | equity ${state['equity']:.2f} | "
          f"clip ${START_EQUITY*CLIP_FRAC:.2f} | stop {STOP:.0%} | "
          f"no take profit | max {MAX_OPEN} open")
    if a.loop:
        while True:
            print(f"\n[{datetime.now(timezone.utc):%H:%M:%S}]")
            cycle(state, a.dry)
            time.sleep(a.loop)
    else:
        cycle(state, a.dry)


if __name__ == "__main__":
    main()
