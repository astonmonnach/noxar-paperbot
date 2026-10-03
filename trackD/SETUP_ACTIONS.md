# Running the paper bot on GitHub Actions

The bot is pure standard library, needs no API keys, and carries its own state
in the repo, so it runs on Actions with nothing to configure.

## One-time setup

```bash
# from C:\Users\thoma\Desktop\onchain
gh repo create noxar-paperbot --public --source=. --remote=paperbot --push
```

Or by hand: create an empty repo, then

```bash
git remote add paperbot https://github.com/<you>/noxar-paperbot.git
git push paperbot HEAD:main
```

Then in the repo: **Settings → Pages → Source: Deploy from a branch →
main /docs**. The dashboard appears at
`https://<you>.github.io/noxar-paperbot/`.

## Public or private?

**Public is the right choice here.** Actions minutes are unlimited on public
repos. On a private repo the free tier gives 2,000 minutes/month, and a
15-minute cadence burns roughly 6,500 — so a private repo would have to drop to
hourly, which costs stop fidelity (see below).

There is nothing secret to protect: no keys, no wallet, no edge that depends on
obscurity. The logic is already written up in `docs/wallet-copy-trade-test.md`.

## The real trade-off: stop fidelity

The bot only checks its stops when a tick runs. At 15 minutes a position can
gap well past −35% before the bot sees it, so realised losses will be worse
than the stop implies. That is honest and worth keeping — a live bot on a slow
poll would suffer exactly the same thing, and pretending otherwise would make
the paper record flattering.

Running it locally via `run_bot.bat` polls every 5 minutes instead, which is
tighter. Running both at once is the one thing to avoid: they would fight over
`state.json`.

## Checking on it

- dashboard: the Pages URL above, or `python -m trackD.dashboard` locally
- raw: `data/trackd/fills.jsonl`, one JSON object per entry and exit
- summary: `python -m trackD.report`

The commit history doubles as a tamper-evident log — every tick is a commit, so
the state cannot be quietly rewritten after the fact.
