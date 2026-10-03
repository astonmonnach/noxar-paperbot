"""Localhost dashboard for the paper bot. Standard library only, no deps.

    python -m trackD.dashboard          # http://localhost:8787
    python -m trackD.dashboard --port 9000

Reads data/trackd/state.json and fills.jsonl on every request, so it always
shows current state and never needs restarting when the bot writes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATE = Path("data/trackd/state.json")
FILLS = Path("data/trackd/fills.jsonl")
START_EQUITY = 300.0

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0A0B0D;color:#E8E8E8;font-family:'IBM Plex Sans',-apple-system,
 'Segoe UI',sans-serif;padding:28px 20px 60px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1100px;margin:0 auto}
.eyebrow{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10px;
 letter-spacing:.16em;color:#00B366;text-transform:uppercase;margin-bottom:10px}
h1{font-size:26px;font-weight:600;letter-spacing:-.015em;margin-bottom:4px}
.sub{color:#8A8F98;font-size:13px;margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 gap:10px;margin-bottom:22px}
.card{background:#111316;border:1px solid #1F242C;border-radius:5px;padding:14px 16px}
.lab{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.14em;
 color:#555962;text-transform:uppercase;margin-bottom:7px}
.val{font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:600;
 letter-spacing:-.02em}
.g{color:#00FF88}.r{color:#FF3355}.a{color:#F5A623}.m{color:#8A8F98}
h2{font-size:12px;font-family:'IBM Plex Mono',monospace;letter-spacing:.14em;
 text-transform:uppercase;color:#8A8F98;margin:26px 0 10px}
table{width:100%;border-collapse:collapse;background:#111316;
 border:1px solid #1F242C;border-radius:5px;overflow:hidden}
th{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.12em;
 text-transform:uppercase;color:#555962;text-align:left;padding:10px 12px;
 border-bottom:1px solid #1F242C;font-weight:500}
td{padding:9px 12px;font-size:13px;border-bottom:1px solid #15181C}
tr:last-child td{border-bottom:none}
td.n{font-family:'IBM Plex Mono',monospace;text-align:right}
.note{background:#151820;border:1px solid #2A3038;border-left:2px solid #F5A623;
 border-radius:4px;padding:12px 14px;color:#8A8F98;font-size:12.5px;
 line-height:1.6;margin-top:26px}
.note b{color:#E8E8E8;font-weight:600}
.foot{color:#555962;font-size:11px;font-family:'IBM Plex Mono',monospace;
 margin-top:22px}
@media(max-width:640px){body{padding:18px 16px 40px}h1{font-size:21px}}
"""


def esc(x) -> str:
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def load():
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "equity": START_EQUITY, "cash": START_EQUITY, "open": {},
        "closed": 0, "realised": 0.0}
    rows = []
    if FILLS.exists():
        rows = [json.loads(l) for l in FILLS.read_text().splitlines() if l.strip()]
    return state, rows


def page() -> str:
    s, rows = load()
    ent = [r for r in rows if r.get("event") == "entry"]
    ex = [r for r in rows if r.get("event") == "exit"]
    eq = s["equity"]
    ret = eq / START_EQUITY - 1
    cls = "g" if ret > 0 else ("r" if ret < 0 else "m")

    if ent:
        t0 = min(datetime.fromisoformat(r["t"]) for r in ent)
        run_h = (datetime.now(timezone.utc) - t0).total_seconds() / 3600
    else:
        run_h = 0.0

    unreal = s.get("unrealised", 0.0)
    cost_open = sum(p["size_usd"] for p in s["open"].values())
    unreal_pct = (unreal / cost_open) if cost_open else 0.0
    wins = [r for r in ex if r["pnl"] > 0]
    wr = f"{len(wins)/len(ex)*100:.0f}%" if ex else "--"
    stops = sum(1 for r in ex if r.get("reason") == "stop")

    cards = [
        ("Equity", f"${eq:,.2f}", cls),
        ("Return", f"{ret:+.2%}", cls),
        ("Realised", f"${s['realised']:+.2f}",
         "g" if s["realised"] > 0 else ("r" if s["realised"] < 0 else "m")),
        ("Unrealised", f"${unreal:+.2f}",
         "g" if unreal > 0 else ("r" if unreal < 0 else "m")),
        ("Open P&L %", f"{unreal_pct:+.2%}",
         "g" if unreal > 0 else ("r" if unreal < 0 else "m")),
        ("Open", str(len(s["open"])), "m"),
        ("Closed", str(len(ex)), "m"),
        ("Win rate", wr, "m"),
        ("Stopped", str(stops), "a" if stops else "m"),
        ("Running", f"{run_h:.1f}h", "m"),
    ]
    cardhtml = "".join(
        f'<div class="card"><div class="lab">{l}</div>'
        f'<div class="val {c}">{v}</div></div>' for l, v, c in cards)

    # open positions
    orows = ""
    for p in sorted(s["open"].values(),
                    key=lambda q: (q.get("last_px", 0) / q["entry_px"] - 1)
                    if q.get("last_px") else 0, reverse=True):
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(p["entry_at"])).total_seconds() / 3600
        lp = p.get("last_px") or 0.0
        pc = (lp / p["entry_px"] - 1) if lp > 0 else 0.0
        pnl = p["size_usd"] * pc
        k = "g" if pc > 0 else ("r" if pc < 0 else "m")
        # live exit floor: hard stop, or the trail once it has armed
        peak = p.get("peak_px") or p["entry_px"]
        armed = peak >= p["entry_px"] * 1.50
        floor = max(p["stop_px"], peak * 0.70) if armed else p["stop_px"]
        dist = (lp / floor - 1) if lp > 0 and floor > 0 else 0.0
        dk = "a" if 0 < dist < 0.10 else "m"
        orows += (f'<tr><td>{esc(p["name"])}</td>'
                  f'<td class="n">${p["size_usd"]:.2f}</td>'
                  f'<td class="n">{p["entry_px"]:.3e}</td>'
                  f'<td class="n">{lp:.3e}</td>'
                  f'<td class="n {k}">{pc:+.1%}</td>'
                  f'<td class="n {k}">${pnl:+.2f}</td>'
                  f'<td class="n {dk}">{dist:+.0%}</td>'
                  f'<td class="n m">{max(72-age,0):.0f}h</td></tr>')
    if not orows:
        orows = '<tr><td colspan="8" class="m">no open positions</td></tr>'

    # closed
    crows = ""
    for r in sorted(ex, key=lambda x: x["t"], reverse=True)[:25]:
        pc = r["exit_px"] / r["entry_px"] - 1
        k = "g" if r["pnl"] > 0 else "r"
        crows += (f'<tr><td>{esc(r["name"])}</td>'
                  f'<td class="n {k}">{pc:+.1%}</td>'
                  f'<td class="n {k}">${r["pnl"]:+.2f}</td>'
                  f'<td class="m">{esc(r.get("reason",""))}</td>'
                  f'<td class="n m">{esc(r["t"][5:16].replace("T"," "))}</td></tr>')
    if not crows:
        crows = ('<tr><td colspan="5" class="m">no exits yet &mdash; positions run '
                 'to a &minus;35% stop or a 72h time stop</td></tr>')

    n = len(ex)
    if n < 20:
        verdict = (f"<b>{n} of ~20 closed trades.</b> Too few to mean anything. "
                   "No confidence interval is shown until there are enough, "
                   "because a tight-looking interval on overlapping samples is "
                   "exactly how the earlier backtests fooled me.")
    else:
        rs = [r["exit_px"]/r["entry_px"]-1 for r in ex]
        mean = sum(rs)/len(rs)
        verdict = (f"<b>{n} closed trades, mean {mean:+.2%}.</b> "
                   "Run <code>python -m trackD.report</code> for the bootstrap "
                   "interval.")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper Bot</title><meta http-equiv="refresh" content="30">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="wrap">
<div class="eyebrow">Onchain / Track D &middot; Paper</div>
<h1>Memecoin paper bot</h1>
<div class="sub">$6 clips on $300 &middot; stop &minus;35% &middot; no take profit
&middot; 72h time stop &middot; max 15 open &middot; <b>no real money</b></div>
<div class="grid">{cardhtml}</div>
<h2>Open positions &mdash; live mark</h2>
<table><tr><th>Name</th><th>Size</th><th>Entry</th><th>Last</th><th>P&amp;L %</th>
<th>P&amp;L $</th><th>To stop</th><th>Time left</th></tr>{orows}</table>
<h2>Closed trades</h2>
<table><tr><th>Name</th><th>Return</th><th>P&amp;L</th><th>Exit</th><th>When</th></tr>
{crows}</table>
<div class="note">{verdict}<br><br>
This bot does not predict. Four tests on 2026-10-03 found no observable
price or volume state that buys directional edge &mdash; the upside/downside
excursion ratio sits near 1.15 whatever you condition on. So it takes many
small shots, never concentrates, and caps nothing on the upside. The log is
the deliverable: forward data carries no survivorship bias, which is the
defect that contaminated every historical test.</div>
<div class="foot">auto-refresh 30s &middot; {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC</div>
</div></body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api"):
            s, rows = load()
            body = json.dumps({"state": s, "fills": rows}).encode()
            ctype = "application/json"
        else:
            body = page().encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--static", help="render once to this path and exit "
                                     "(used by the GitHub Pages workflow)")
    a = ap.parse_args()
    if a.static:
        out = Path(a.static)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(), encoding="utf-8")
        print(f"-> {out}")
        return
    print(f"dashboard -> http://localhost:{a.port}   (ctrl-c to stop)")
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
