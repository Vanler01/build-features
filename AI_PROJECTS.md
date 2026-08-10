# AI_PROJECTS.md — shared conventions for the Claude-backed bot/app projects

build-features now holds **two classes of project**:

1. **macOS background daemons** — `en-th-word-swap`, `num-to-text`, `morse-code`.
   Rules live in root `CLAUDE.md` / `AGENTS.md`.
2. **Server-side AI products** (this file) — `hydration-drink-ai`,
   `slang-translator-ai`, `job-prep-ai`, `numeral-translator-ai`,
   `news-digest-ai`.

Nothing in the daemon rules (CGEventTap, NSPanel, Accessibility permission,
`_synth_pending`) applies to class 2. Nothing here applies to class 1.
Per-project rules live in each project's own `CLAUDE.md`. Read the project's
`REQUIREMENTS.md` before proposing any implementation — each one ends with open
questions that are still open.

---

## Per-project stack

| project | backend | client(s) | key deps |
|---|---|---|---|
| hydration-drink-ai | Python 3.11+ | Telegram + LINE bots → Flutter app + native widgets | anthropic, httpx, fastapi, SQLite |
| slang-translator-ai | Node 20+ / TypeScript | Telegram bot → Chrome MV3 extension | grammY, @anthropic-ai/sdk, SQLite |
| job-prep-ai | Python 3.11+ | web (FastAPI) or bot — **undecided** | fastapi, anthropic, httpx |
| numeral-translator-ai | Python 3.11+ | Telegram bot | num2words, unicode-rbnf, anthropic |
| news-digest-ai | Python 3.11+ | Telegram scheduled push → app (V2) | anthropic, httpx, APScheduler, SQLite |

slang-translator-ai is TypeScript because its V2 is a Chrome extension — one
language for bot, scraper, and extension. The rest are Python; for
numeral-translator-ai this is forced (`num2words` has no real JS equivalent).

news-digest-ai is the odd one out in shape, not stack: it is a **scheduled
sender**, not a conversational bot. There are no handler flows to build in
Phase 1 — a cron-like job pulls its sources, Claude summarizes, one message
goes out. Its `REQUIREMENTS.md` does not name a backend language; Python is
assumed here for consistency with the other non-extension projects.

---

## Critical rules (all five projects)

1. **No secrets in the repo, ever.** Bot tokens, Claude API keys, Google Maps
   keys, Adzuna App ID/Key, data.gov keys live in a per-project `.env` that is
   git-ignored. Code reads them via env var only. A key committed once is
   burned — rotate it, don't just delete the line.
2. **No API key ships to a client.** Mobile apps and the browser extension talk
   to *your* backend; the backend holds the keys. Never embed a Claude or Google
   key in a React Native bundle or a content script.
3. **Every Claude call is structured or it isn't parsed.** Use tool-use /
   structured output with an explicit JSON schema. Never regex a model's prose.
4. **Every Claude answer that could be wrong is labeled.** Where a library or
   dataset can answer, prefer it; when Claude is the fallback, the reply must say
   so. This is a hard requirement in numeral-translator-ai (a wrong number is a
   real error) and in news-digest-ai, where an arXiv preprint must carry an
   explicit "preprint / not yet peer-reviewed" label and may never be phrased as
   settled fact. Soft requirement elsewhere.
5. **User content is not training data and not logs.** Never log message bodies,
   photos, resume text, or locations. Log IDs, timestamps, and outcomes.
6. **Treat all external text as untrusted input.** Job listings, arXiv abstracts,
   Hacker News titles, outlet headlines, and any other fetched text flow into
   Claude prompts — they are an injection surface, and news-digest-ai's whole
   Phase 1 is fetched text. Never let fetched text reach a prompt where it can be
   read as an instruction. User message text counts too, on every project.
7. **Cache external API results.** Google Places/Directions, Adzuna, USDA, NASA,
   Finnhub, and Alpha Vantage all have free-tier ceilings; an uncached call per
   user action will blow them. Alpha Vantage's free tier is 25 requests/day —
   it is a backup source in news-digest-ai, never the primary.
8. **Scrape only what's permitted.** Check `robots.txt` and ToS before adding any
   scraper, honour a rate limit, and set a real User-Agent. Where an official API
   exists (JobThai, Open Food Facts), use it instead of scraping.
   Applying this honestly has already removed two planned scrapers:
   slang-translator-ai now caches Claude's answers instead of scraping Urban
   Dictionary, whose ToS forbids it. Read the ToS before the code, not after.

---

## Secrets layout

Per project:

```
<project>/.env            # git-ignored, real values
<project>/.env.example    # committed, keys with empty values + a comment each
```

`.env.example` is the contract — if a new env var is added, it goes there in the
same commit. Never put a real value in the example file.

---

## Claude API usage

- Read the `claude-api` skill before writing any Claude call — model IDs,
  pricing, and structured-output syntax change; don't write them from memory.
- Default model: Sonnet for parsing/classification/ranking, Haiku for
  high-volume cheap passes (slang detection, classification). Reserve Opus
  for nothing here yet.
- Set `max_tokens` deliberately. Structured extraction needs far less than the
  default anyone copies from a tutorial.
- Vision (hydration photo logging) costs per image — resize before upload.
- Retry on 429/5xx with backoff; surface a plain "try again" to the user rather
  than a stack trace.

## Telegram bot patterns

- Long polling for local dev, webhook for anything deployed. Both must be
  behind one abstraction so switching doesn't touch handler code.
- Never trust `update.message.text` length — Telegram allows 4096 chars.
- Photo messages: fetch the largest `photo[]` size, not `photo[0]`.
- Location shares are opt-in per message; store them only if the project's data
  model says to, and never as a persistent trail.
- Bot tokens in `.env` (see above). A leaked token = full control of the bot.

## Data & storage

- SQLite for MVPs, with a migration file from day one (not `CREATE TABLE IF NOT
  EXISTS` scattered through the code). Postgres only when a project actually
  needs concurrency.
- Timestamps: store UTC, render in the user's timezone. Every one of these
  projects has a per-user timezone problem (reminders, "today's" summary).
- Retention: each project's `CLAUDE.md` states what is kept and for how long.
  If it isn't written down there, it isn't kept.

## Testing

- Mock every network call — Telegram, Claude, Google, Adzuna, scrapers. No test
  may hit a live API or consume quota.
- Record one real response per external API as a fixture; assert the parser
  against the fixture, not against a hand-written ideal shape.
- Coverage target: 80% on parsing/conversion/normalization logic. UI and bot
  wiring are exempt.
- Python: `pytest` + `ruff`. TypeScript: `vitest` + `eslint`.

## Code style

- Python: 3.11+ type hints required, `%`-style log formatting, no bare `except`,
  100-char lines, docstrings on public functions. (Same as the daemons.)
- TypeScript: `strict: true`, no `any` without a comment justifying it, named
  exports, 100-char lines.
- Conventional commits (`feat:`, `fix:`, `docs:`, …), branch `feat/<name>`.

---

## Agents

Each project has its own sub-agents (four each so far), listed in that project's
`AGENTS.md`. Naming convention is `<project-prefix>-<role>`:

| prefix | project |
|---|---|
| `hydration-` | hydration-drink-ai |
| `slang-` | slang-translator-ai |
| `jobprep-` | job-prep-ai |
| `numeral-` | numeral-translator-ai |
| `newsdigest-` | news-digest-ai (no agents written yet) |

The daemon-class agents (`macos-api-specialist`, `thai-lang-validator`,
`num-converter-validator`, `security-reviewer`) do **not** apply to these
projects — `security-reviewer` in particular checks for keystroke logging and
will report a meaningless pass here.
