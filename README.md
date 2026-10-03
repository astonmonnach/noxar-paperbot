# noxar-paperbot

A memecoin paper-trading bot that runs itself on GitHub Actions. **No real money,
no API keys, no dependencies** — pure Python standard library.

Live dashboard: enable **Settings → Pages → Deploy from a branch → main /docs**.

## What it does

Every 15 minutes it marks its open positions, applies the exit rules, and opens
new ones if it has room. State lives in `data/trackd/state.json` and every fill
is appended to `data/trackd/fills.jsonl`, both committed back by the workflow —
so the commit history is a tamper-evident log of the experiment.

| rule | value |
|---|---|
| clip size | $6 on a $300 book (2%) |
| max open | 15, one position per token |
| hard stop | −35% |
| trailing stop | arms at +50%, then 30% below the high-water mark |
| time stop | 72h |
| take profit | **none** |
| universe | $20k–$400k liquidity, >24h and <120d old, >$5k daily volume, no majors or stables |

## Why it is built this way

It does not predict. Testing on 2026-10-03 found no observable price or volume
state that buys directional edge in this market — the upside/downside excursion
ratio sits near 1.15 whatever you condition on. Filters that cut the downside cut
the right tail by roughly the same factor.

So it takes many small shots, never concentrates, and caps nothing on the upside.
The trailing stop exists because a bare time stop gave back ~100% of the best
move a position ever showed; arming a 30% trail at +50% raises that capture to
~21% without touching the >+50% hit rate.

**This is not a demonstrated edge.** Every exit rule tested still had a negative
mean on clean data. The point of running it is that forward data carries no
survivorship bias, which contaminated every historical test. The log is the
deliverable.

## Local use

```bash
python -m trackD.bot --once          # one cycle
python -m trackD.bot --loop 300      # continuous, 5-min poll
python -m trackD.dashboard           # http://localhost:8787
python -m trackD.report              # summary; withholds a CI until ~20 closed trades
```

Run **either** Actions or a local loop, never both — they would fight over
`state.json`.
