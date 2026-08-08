# slang-translator-ai — project rules

Decodes Gen Z / Gen Alpha slang: short definition + example. Telegram bot →
Chrome context-menu extension. Full spec: `REQUIREMENTS.md`.

**Status: spec-only.** No code yet.

Shared rules for this project class: `../AI_PROJECTS.md`. This file holds only
what is specific to slang-translator-ai.

## Stack
- Node 20+ / TypeScript (`strict: true`), `grammY`, `@anthropic-ai/sdk`, SQLite
- V2: Chrome extension, Manifest V3, `contextMenus` + `activeTab`

## The two decisions everything else follows from

Both were verified against current terms of service, and both are recorded in
`REQUIREMENTS.md` §0 so they are not quietly reversed later.

**There is no scraper.** Urban Dictionary's ToS requires express permission for
API access; the "unofficial API" is a third party scraping them, so using it
does not route around anything. The vocabulary store is a **cache of Claude's
answers**, seeded by hand and grown from real lookups.

**The extension is a context menu, not a content script.** Discord's ToS
prohibits scraping their service by any automated means, which is what a content
script reading messages is. Selecting text and right-clicking is the user
invoking a lookup on their own selection.

## Critical rules

### The store
1. **No scraper. Ever.** Not Urban Dictionary, not glossary sites, not a
   "just this once" fetch. A human reading a glossary and typing entries in is
   research; a scheduled job is not. Any network call in a data-collection path
   is a defect.
2. **A Claude-sourced entry is never auto-promoted to verified.** It may be
   *served* while unverified — that is the point of the cache — but `verified`
   is set by a person. Auto-promotion launders a guess into a fact.
3. **`source` names the real origin**: `manual_seed`, `claude`, or
   `user_report`. Never a generic value.
4. **Confidence decays with `last_seen`.** Slang shifts meaning while keeping
   its spelling; an entry nobody has touched in months is a re-verification
   candidate, not a fact.

### Answering
5. **Store first, Claude second.** A lookup that calls Claude before checking
   the store is a cost and latency bug.
6. **Define, don't rewrite.** Given a sentence, name the slang in it and define
   those words. Never paraphrase the user's message.
7. **"Nothing unusual here" is a correct answer.** Most slang words are also
   ordinary English — `bet`, `mid`, `cap`, `fire`, `sick`, `slaps`. A system
   that strains to find slang in a plain sentence is worse than no system.
   Over-flagging is the failure mode that kills this product.
8. **Terms have multiple senses.** `cap` is lie / hat / limit. Lead with the
   sense that fits the context and mention the others in one line.
9. **Scraped-text injection is gone, but user text is not.** Message text still
   reaches prompts. Fence it and constrain output with a schema.

### Content
10. **Explain accurately, don't endorse.** The purpose is comprehension,
    including of crude and offensive words. Someone who does not realise a slur
    is aimed at them is exactly who this should help.
11. **Slurs are defined neutrally and never with a usage example.** An example
    models using it. This is the one hard rule in the content policy.
12. **Flag and show; never hide.** Entries carry `sexual` / `vulgar` / `slur` /
    `violent` flags, and the flag is displayed *beside* the definition rather
    than used to suppress it. Somebody asked what a word means — refusing to
    say is the one failure that breaks this for every reader at once, most
    sharply for the person who was called something. Settled in
    `REQUIREMENTS.md` §12.
13. **Write for a reader with no context.** The audience is everybody, so
    definitions use plain English and contain no slang themselves. No "iykyk",
    no assuming an adjacent term is known, no performing the register being
    described. Short sentences; a large part of "everybody" is reading in a
    second language.
14. **Gen Alpha slang means some readers are children.** That is a reason the
    flags must actually be applied — not a reason to withhold meanings, and not
    a reason for an age gate that cannot be verified anyway.

### The extension
15. **`contextMenus` + `activeTab` only.** No content script, no
    `host_permissions` list, never `<all_urls>`.
16. **Only the selected term leaves the browser.** Never the page, the
    surrounding conversation, the URL, or a username.
17. **No API key in the extension bundle.** It talks to your backend; the
    backend holds keys.
18. **Unpublished and personal-use** until each target platform's terms have
    been reviewed individually.

### Privacy
19. **`lookups` stores term + timestamp only.** What someone looks up is
    sensitive — a teenager checking a sexual term, or someone checking a slur
    aimed at them. Never the surrounding message, page or URL. Short retention,
    aggregate counts once reviewed.

## Data retention
- `terms` / `senses` — permanent; the product.
- `lookups` — term and timestamp, short window, then aggregate.
- `review_queue` — until reviewed.
- Page content, message bodies, URLs — never stored anywhere.

## Agents
See `AGENTS.md` in this directory. Use `slang-*` agents only — the daemon-class
agents in the root `AGENTS.md` do not apply here.
