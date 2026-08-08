# Project 2: Gen Z / Gen Alpha Slang Translator — Build Plan

## Vision
An AI that decodes Gen Z and Gen Alpha slang the moment you hit it in a conversation — a term, an acronym, a phrase you don't recognize — and gives you a short, plain definition plus an example. Built from a scraped vocabulary base so it stays current, not just relying on the model's training data. Same phased approach as Project 1: a bot MVP first, a browser extension as the fuller version.

---

## 1. Bot MVP

**Platform: Telegram** (same reasoning as Project 1 — free, instant setup, no business approval, supports text).

**Flow:**
- User pastes a term or a whole message ("what does 'he's got mad rizz' mean")
- Bot looks up the term in the scraped vocabulary database first; if not found, falls back to Claude to define it using context
- Replies with: **short definition + example** (e.g., "'rizz' = charisma/flirting skill. Ex: 'he's got mad rizz.'")
- If a whole sentence is pasted, bot picks out the slang word(s) in it and defines just those, rather than rewriting the sentence

**Stack:** Telegram Bot API + small backend (Node.js or Python) + Claude API (text) + a local vocabulary database (see below).

---

## 2. Browser Extension (V2)

**Platform:** Chrome extension, Manifest V3, for live definitions inline while you're actually in a chat (Discord, Instagram DMs, TikTok comments, etc.).

**How it works technically:** a content script injected on the target site's domain can read the page's text (chat messages) and overlay a tooltip/definition — this is a standard, supported Manifest V3 pattern (content scripts + host permissions), not a workaround.

**Important caveat:** this only works on **sites you grant the extension domain permission for**, and it's for personal use (unpublished/sideloaded extension), not distributed via the Chrome Web Store — reading chat content programmatically may run against some platforms' terms of service if turned into a public product, so keep it personal-use only, not published, unless we later review each platform's ToS individually.

**Behavior:**
- Highlights or underlines recognized slang terms on the page
- Hover/tap shows the short definition + example (same format as the bot)
- Small popup toggle to turn detection on/off per site

---

## 3. Vocabulary Data Pipeline

**Sources to scrape/pull from** (mix of structured and unstructured):
- **Unofficial Urban Dictionary API** — free, no key, no rate limit, community-sourced definitions (can be inconsistent/vulgar, needs filtering)
- **Curated slang glossary sites** (e.g., ZSlang.com's weekly-updated Gen Z dictionary, GenPPT's Gen Alpha glossary) — good for the newest terms, cleaner definitions, updated more often than Urban Dictionary
- **Manual seed list** — the obvious/current staples (rizz, skibidi, gyat, delulu, sigma, aura, cap/no cap, bet, mid, etc.) hand-verified so the bot doesn't launch with an empty or messy database

**Pipeline shape:**
1. Scraper pulls raw entries from the sources above on a schedule (e.g., weekly)
2. Claude cleans/normalizes each entry into the consistent short format (term, definition, example, source) and filters out joke/troll entries from Urban Dictionary
3. Cleaned entries go into the vocabulary database; new/unrecognized terms encountered live by users get queued for review and addition

This keeps the database current without needing a scrape on every single user query — lookups are fast (local DB), and Claude is only the fallback for genuinely new/unseen terms.

---

## 4. AI Components (what Claude actually does)

1. **Definition fallback** — when a term isn't in the vocabulary database yet, Claude defines it from context and general knowledge of slang, in the same short format.
2. **Entry cleaning/normalization** — turns messy scraped source text into consistent term/definition/example entries, filtering low-quality or joke submissions.
3. **Slang detection in a full message** — given a pasted sentence, identifies which word(s) are the actual slang vs. normal English, so the bot doesn't over-flag common words.

---

## 5. Data Model (rough)

- `vocabulary` — term, definition, example, category (Gen Z / Gen Alpha / both), source, date_added, confidence
- `users` — id, platform (telegram/extension), enabled_sites (for extension)
- `lookups` — user_id, term, timestamp, found_locally (bool) — lets you see which new terms are showing up often and should get added
- `pending_terms` — terms Claude had to define live that aren't in the database yet, queued for review

---

## 6. Build Roadmap

**Phase 0 — Prep**
- Create Telegram bot via @BotFather (can reuse Project 1's bot-creation know-how)
- Set up the scraper for Urban Dictionary (unofficial API) + 1-2 curated glossary sites
- Hand-write the manual seed list (~50 current terms) so the bot launches useful on day one

**Phase 1 — Bot MVP**
- Vocabulary database + lookup
- Claude fallback for unknown terms
- Slang-detection-in-a-sentence logic
- Bot reply formatting (definition + example)

**Phase 2 — Data Pipeline**
- Scheduled scraper job
- Claude-based cleaning/normalization step
- Pending-terms review queue

**Phase 3 — Browser Extension**
- Manifest V3 skeleton, content script on 1-2 target sites first (e.g., Discord web, Instagram web)
- Term highlighting + hover tooltip
- Per-site on/off toggle
- Same backend/vocabulary database as the bot (shared, like Project 1's bot↔app setup)

**Phase 4 — Polish**
- Expand to more sites
- Track which terms are looked up most to prioritize the seed list
- Handle regional/community-specific slang variants

---

## Open Questions to Settle Before Coding
- Which sites should the extension support first — Discord, Instagram, TikTok, all three?
- Should the bot/extension filter out NSFW or offensive slang entries from Urban Dictionary, or include them with a content flag?
- Personal use only, or would you want to eventually share this with friends (changes the ToS/publishing consideration for the extension)?

Sources: [Unofficial Urban Dictionary API](https://unofficialurbandictionaryapi.com/), [ZSlang.com Gen Z Slang Dictionary](https://zslang.com/), [GenPPT Gen Alpha Slang Guide](https://genppt.com/blog/gen-alpha-slang), [Manifest V3 content scripts & host permissions](https://extension.js.org/docs/concepts/manifest-v3)
