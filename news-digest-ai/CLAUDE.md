# news-digest-ai — project rules

A daily digest of science (astrophysics), technology, and stocks — curated, not
noisy. Two fun facts a day (one space, one tech) plus real news on what happened
and what's coming. Telegram scheduled push → app in V2. Full spec:
`REQUIREMENTS.md`.

Read `REQUIREMENTS.md` first. Three questions in it are **still open** — the send
time, which outlets seed the tech allowlist, and how the stock watchlist gets
managed. Don't assume answers to them in code.

Shared rules for this project class are imported below; this file holds only
what is specific to news-digest-ai.

@../AI_PROJECTS.md

## Stack
- Python 3.11+ — **assumed, not specified.** `REQUIREMENTS.md` never names a
  backend language; this follows the other non-extension projects. Overturn it
  here if that's wrong, don't leave the two docs disagreeing.
- `anthropic` (summarization, filtering, fun facts), `httpx`, SQLite
- A scheduler (APScheduler or equivalent) — the send loop, not a bot loop
- Sources: NASA Open APIs, Launch Library 2, arXiv, Hacker News API, Finnhub,
  Alpha Vantage (backup only)

## Critical rules

### Shape
1. **This is a sender, not a bot.** Phase 1 has no conversational flow: a
   scheduled job pulls sources, Claude summarizes, one message goes out. Don't
   build handler/state machinery the product doesn't have. Setup commands
   (watchlist, send time) are the *only* inbound messages, and that surface is
   still an open question — see above.
2. **A failed digest is silent, not wrong.** If a source is down or a section
   comes back empty, send the digest without that section (or skip the day) and
   log the failure. Never fill a gap with model-generated filler to keep the
   shape intact.

### Trust and labeling
3. **arXiv items are preprints and must say so.** Any item sourced from a
   preprint rather than a peer-reviewed publication or an official agency
   (NASA/ESA) carries an explicit "preprint — not yet peer-reviewed" label in
   the digest text itself, not just in the database. Presenting one as settled
   fact is a critical bug, not a wording nit.
4. **Prefer primary sources for science.** Official agency and established
   science journalism outrank aggregators. When two sources cover the same
   result, cite the primary one.
5. **Fun facts come from the day's pulled data, not from memory.** Derive them
   from the APOD explanation, a launch record, or a fetched tech item. A fun
   fact Claude invented unprompted is a fabrication with a friendly tone, and it
   is the easiest thing in this project to get wrong without noticing.
6. **Every fetched item is untrusted text.** Headlines, abstracts, and HN titles
   go into the summarization prompt as *data* — never in a position where they
   can be read as instructions. This project is almost entirely fetched text
   flowing into a model; treat the prompt boundary as the security boundary.

### Filtering
7. **Allowlist, never open-web scraping.** Tech items come from the
   `source_allowlist` table plus the Hacker News API. Adding a source means
   adding a row, not widening a crawler. Honour each API's published rate limit
   and send a real User-Agent (arXiv in particular publishes one — check it
   before writing the client, don't guess a number).
8. **"AI slop" has a definition, so use it.** Filter PR-driven hype, sponsored
   posts dressed as news, and low-substance funding-round churn. Hacker News
   score and discussion volume are a community-vetted cross-check on whether a
   tech item has substance — a signal, not the sole gate.
9. **Filtering thresholds are tunable data, not constants in code.** Score
   floors and trust levels live in the database next to the allowlist, because
   Phase 4 is explicitly about tuning them against what noise actually shows up.

### Stocks
10. **Report news; never advise.** The stock section says what happened and to
    which ticker. No buy/sell framing, no price targets, no "poised to" verbs,
    no sentiment score presented as a recommendation. This is a briefing, and it
    must not read like an analyst note.
11. **Finnhub is primary, Alpha Vantage is backup.** Alpha Vantage's free tier
    is 25 requests/day — one careless loop exhausts it. Never wire it into the
    per-item path.
12. **A watchlist is personal financial interest.** Tickers leave the system only
    as query parameters to the market API. Never log them, never put them in a
    prompt that isn't the watchlist-matching call, and never share them across
    users.

### Delivery
13. **"Today" is the user's today.** `digest_send_time` resolves against the
    user's timezone, not the server's. A digest that arrives at 3am because the
    scheduler ran in UTC is a broken product, not a rounding error.

## Data retention
- `digest_log` — kept indefinitely; it *is* the V2 archive feature.
- `source_allowlist` — permanent config, hand-maintained.
- `users` — send time, timezone, watchlist tickers. Tickers are deletable.
- Raw fetched article text — not persisted. Keep the summarized digest entry and
  the source URL, discard the body.

## Agents
None written yet. The reserved prefix is `newsdigest-` (see `AI_PROJECTS.md`).
When they're added, this project's non-negotiable one is a provenance/labeling
guard for rules 3–5 — the same role `numeral-provenance-guard` plays next door.
The daemon-class agents in the root `AGENTS.md` do not apply here.
