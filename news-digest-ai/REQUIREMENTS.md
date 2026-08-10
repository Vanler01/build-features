# Project 5: Science, Tech & Stocks Daily Digest AI — Build Plan

## Vision
A daily digest AI covering science (astrophysics), technology, and stocks — curated, not noisy. No AI-hype filler, no unproven theories presented as fact. Two daily fun facts (one space/astronomy, one tech), plus real news on what's happened and what's coming up.

---

## 1. Delivery Recommendation

**Telegram push digest first, no interactive bot logic needed for MVP.** This is a read-only daily briefing, not a back-and-forth tool like the other projects — so instead of building conversational bot flows, the "bot" is really just a scheduled message sender (same free Telegram infrastructure, much simpler build). A full app comes later if you want a searchable archive of past digests, charts for the watchlist, or a nicer reading UI than a chat message.

**Phase 1 (MVP):** Telegram scheduled push, one message per day at a set time, no interaction required.
**Phase 2 (later):** App with digest archive, watchlist management UI, and richer formatting.

---

## 2. Content Pillars (per the reminder)

1. **Science / Astrophysics news** — real developments, not speculation. Space, astronomy, space events (upcoming and recently happened).
2. **Technology news** — from spacecraft/scientific tech down to consumer-casual (phones, chips, laptops, AI models) — but filtered, not hype.
3. **Stocks** — general market-moving news, plus a personal watchlist section if you add tickers.
4. **Two daily fun facts** — one about space/astronomy/space events, one about technology (spacecraft, scientific, or casual consumer tech/AI models).

---

## 3. Filtering / Quality Criteria (the core ask: "filter the noisy stuff")

- **"AI slop tech"** — treat this as PR-driven hype content, sponsored posts dressed as news, and low-substance "AI startup raises $X" churn. Filter using a source allowlist (see below) rather than open web scraping, and optionally cross-check tech items against Hacker News score/discussion volume as a community-vetted signal before including them.
- **"Unproven theory"** — astrophysics research from arXiv preprints is real and often the most current news, but it hasn't been peer-reviewed yet. Rule: if a science item comes from a preprint (arXiv) rather than a published/peer-reviewed source or an official agency (NASA/ESA), it must be **explicitly labeled "preprint / not yet peer-reviewed"** in the digest, never presented as settled fact.
- Prefer official/primary sources (NASA, ESA, established science journalism) over aggregators for the science section.

---

## 4. Data Sources

**Science / Space:**
- **NASA Open APIs** — APOD (Astronomy Picture of the Day), NEO (near-earth objects), DONKI (space weather), EONET (natural events) — free, official, well documented
- **Launch Library 2 API** (thespacedevs.com) — upcoming and past rocket launches, exactly matches "space events about to happen and have happened"
- **arXiv API** — free, public, for cutting-edge astrophysics research — used only with the preprint label per the filtering rule above

**Technology:**
- **Hacker News API** (Firebase-backed, official, no rate limit) — top stories filtered by score threshold as a quality signal, good for catching real tech/science developments without hype
- Curated outlet sources (e.g., Ars Technica, IEEE Spectrum) for the more "casual" consumer tech angle (phones, chips, laptops, AI models) — an allowlist of a handful of trusted outlets rather than broad scraping

**Stocks:**
- **Finnhub** — generous free tier (60 requests/minute), covers both general market news and ticker-specific company news plus sentiment — primary source given the "both general and watchlist" scope
- **Alpha Vantage** — free tier is much more limited (25 requests/day) but has a news + sentiment API; useful as a secondary/backup source, not primary given the low request cap

---

## 5. AI Components (what Claude actually does)

1. **Summarization** — condense the day's pulled items (NASA/launch data, Hacker News items, Finnhub news) into a short, readable digest rather than a raw feed dump.
2. **Fun fact generation** — writes the two daily fun facts from the underlying source data (e.g., today's APOD explanation, an interesting note tied to an upcoming launch or a notable tech item).
3. **Noise filtering** — scores/filters tech items for substance vs. hype before inclusion, and flags preprint vs. peer-reviewed science claims.
4. **Watchlist relevance** — for stock items, matches news to the user's specific tickers vs. general market relevance.

---

## 6. Data Model (rough)

- `users` — id, platform (telegram/app), digest_send_time, timezone, watchlist (list of tickers)
- `digest_log` — date, science_items, tech_items, stock_items, fun_fact_space, fun_fact_tech — archived so a future app can show history
- `source_allowlist` — outlet/domain, category (science/tech), trust_level — the curated list driving the "no noise" filter

---

## 7. Build Roadmap

**Phase 0 — Prep**
- Get a free NASA API key (api.nasa.gov)
- Get a free Finnhub API key
- Optionally an Alpha Vantage key as backup
- Decide the initial trusted-outlet allowlist for tech (start small, e.g. 3-5 outlets)
- Create/reuse the Telegram bot for pushing the daily message

**Phase 1 — Science + Space Digest**
- Pull APOD, upcoming/recent launches (Launch Library 2), relevant arXiv items
- Claude summarizes + labels preprint items
- Daily space/astronomy fun fact generation

**Phase 2 — Tech Digest**
- Pull Hacker News top stories (score-filtered) + allowlisted outlet items
- Claude scores for substance vs. hype, filters
- Daily tech fun fact generation

**Phase 3 — Stocks Digest**
- General market news via Finnhub
- Watchlist-specific news matching (user-provided tickers)
- Combine into one daily message with clear sections

**Phase 4 — Polish**
- Scheduled send at user's preferred time/timezone
- Digest archive (once app phase starts)
- Tune the allowlist and filtering thresholds based on what actually shows up as noise

---

## Open Questions to Settle Before Coding
- What time of day should the digest send?
- Which specific outlets should seed the tech "trusted allowlist" to start?
- How do you want to manage your stock watchlist — send tickers to the bot as a one-time setup message, or a small settings command?

Sources: [NASA Open APIs](https://parse.bot/marketplace/fd03028c-26dd-4a43-91cd-a3f4ffbb8f65/api-nasa-gov-api), [Launch Library 2 API](https://ll.thespacedevs.com/2.0.0/launch/upcoming/), [Hacker News Official API](https://github.com/hackernews/api), [Finnhub vs Alpha Vantage free tiers 2026](https://apiscout.dev/guides/best-stock-market-financial-apis-2026), [Alpha Vantage free API](https://www.alphavantage.co/)
