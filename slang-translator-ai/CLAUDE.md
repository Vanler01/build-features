# slang-translator-ai — project rules

Decodes Gen Z / Gen Alpha slang: short definition + example, backed by a scraped
vocabulary database so it stays current. Telegram bot MVP → Chrome MV3 extension
V2. Full spec: `REQUIREMENTS.md`.

**Status: spec-only.** No code yet. Read `REQUIREMENTS.md` and the open questions
at the bottom of it before proposing an implementation.

Shared rules for this project class: `../AI_PROJECTS.md`. This file holds only
what is specific to slang-translator-ai.

## Stack
- Node 20+ / TypeScript (`strict: true`), `grammY`, `@anthropic-ai/sdk`, SQLite
- V2: Chrome extension, Manifest V3, content script + host permissions
- TypeScript is deliberate: bot, scraper, and extension share one language

## Critical rules
1. **Database first, Claude second.** Every lookup hits the local `vocabulary`
   table before it hits the API. Claude is the fallback for genuinely unseen
   terms, and those go into `pending_terms` for review — not silently into
   `vocabulary` as if verified.
2. **Define, don't rewrite.** Given a whole sentence, the bot identifies the
   slang word(s) and defines those. It does not paraphrase or "translate" the
   user's message.
3. **Scraped text is untrusted input.** Urban Dictionary entries are
   user-submitted and go straight into Claude prompts for normalization — a
   classic injection surface. Fence scraped content clearly in the prompt and
   never let it be read as instruction.
4. **Filtering is a policy decision, not a default.** The open question of
   NSFW/offensive entries (flag vs. exclude) is unsettled — until it's settled,
   the pipeline marks entries rather than silently dropping them, so the choice
   stays reversible. Slurs are the exception: defined neutrally as "this is a
   slur against X", never endorsed, never with a usage example.
5. **The extension is personal-use, unpublished.** Reading chat content on
   Discord/Instagram/TikTok may violate their ToS if distributed. No Chrome Web
   Store listing without a per-platform ToS review first.
6. **The extension reads the page; it never ships the page anywhere.** Term
   detection runs against the local vocabulary list in the extension. Only an
   unrecognized single *term* may go to the backend — never message text,
   never usernames, never page context.
7. **No `<all_urls>`.** `host_permissions` lists specific domains, and the
   per-site toggle actually gates the content script — off means not injected.

## Data retention
- `vocabulary`, `pending_terms` — permanent (the product).
- `lookups` — term + timestamp only, to prioritize seeding. **Never the
  surrounding message.**
- Extension: no page content persisted anywhere, ever.

## Scope guard
The scraper is a **scheduled** job (~weekly), not a per-query fetch. If a
lookup path ever calls Urban Dictionary live, that's a bug.

## Agents
See `AGENTS.md` in this directory. Use `slang-*` agents only — the daemon-class
agents in the root `AGENTS.md` do not apply here.
