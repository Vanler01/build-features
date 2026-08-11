# slang-translator-ai — Requirements

## Vision

Decodes Gen Z and Gen Alpha slang the moment you hit it — a term, an acronym, a
phrase — and gives back a short plain definition plus an example. Telegram bot
first, browser extension second, one vocabulary store behind both.

> Status: Phases 0–5 built. Every roadmap item is implemented; what remains is
> use — working the review queue down, and deciding the sharing question below.
> Nothing has been looked up yet, so the demand-ordered queue and the hit rate
> are both waiting on the bot actually being run.

---

## 0. What changed from the first draft, and why

Two findings reshaped this, both verified against current terms of service
rather than assumed. They are recorded here so they are not re-litigated later.

**Urban Dictionary is not a usable source.** Their
[terms of service](https://urbandictionary.help/tos/) require express permission
for API access and prohibit automated access. The "unofficial API" is a third
party scraping them, so using it does not route around the ToS — it just adds a
dependency that disappears the day they receive a cease-and-desist.
`AI_PROJECTS.md` rule 8 forbids this outright.

**Discord is the worst possible first target for a content script.** Their
[terms](https://support.discord.com/hc/en-us/articles/4469963531415-Terms-of-Service-Updates)
prohibit *"scraping our services without our written consent, including by using
any robot, spider, crawler, scraper, or other automatic device, process, or
software."* A content script reading messages is exactly that. Enforcement is
currently inconsistent, which is luck rather than permission.

So the two structural decisions below:

| Original plan | Now | Why |
|---|---|---|
| Scrape Urban Dictionary + glossary sites, normalise with Claude, store | **Cache what Claude answers**, hand-verify into the permanent set | Removes the scraper, the troll filter, the normaliser and the entire ToS problem. Also *more* current, not less. |
| Content script reading Discord / Instagram / TikTok | **Context-menu lookup on selected text** | No continuous page reading, no per-site selectors, works on every site immediately, and the user explicitly invokes it on their own selection. |

---

## 1. The vocabulary store: a cache, not a scrape

The first draft's premise was that scraping keeps the database current, and that
the model alone would go stale. That is backwards.

Urban Dictionary's top entry for a term is routinely a joke, somebody's friend's
name, or three years out of date. Curated glossary sites lag by months. Neither
is fresher than a model that can also read the surrounding context. What a local
database genuinely buys is **latency and cost** — not currency.

So the flow is:

```
lookup → hit the store        → answer (fast, free)
       → miss → ask Claude    → answer, and write it to the store as unverified
                              → queue for human review
```

- **Seed by hand.** ~50 current staples, hand-written and verified, so day one
  is useful rather than empty.
- **Grow from real use.** Terms people actually look up are exactly the terms
  worth storing. Nothing else earns a row.
- **Verification is a human step.** An entry Claude produced is marked
  `unverified` and stays that way until a person confirms it. Answering from an
  unverified entry is fine; *promoting* it to verified is not automatic. A
  guess that gets stored is still a guess.

There is no scraper, scheduled job, or normalisation pipeline. If a curated
glossary is useful, a human reads it and adds entries by hand — that is
research, not automated collection, and it is the only form of it here.

---

## 2. The hard part: precision, not coverage

This deserves to be a named constraint rather than a bullet, because it is the
thing most likely to kill the product.

**Most slang words are also ordinary English.** `bet`, `mid`, `cap`, `fire`,
`sick`, `slaps`, `bussin`, `ate`, `left no crumbs` — a system that flags every
occurrence is worse than no system. In the extension it would be unusable, and
in the bot it produces confidently wrong answers about plain sentences.

Consequences for the design:

- Detection must use **context**, not a word list. "I'll bet you £5" is not
  slang; "bet" as a standalone reply is.
- When a message contains no slang, the correct answer is **"nothing unusual
  here"**, not a strained interpretation of an ordinary word.
- The bot **defines, never rewrites**. Asked about a sentence, it names the
  slang terms in it and defines those. It does not paraphrase the message.
- Confidence is surfaced. A low-confidence read says so.

---

## 3. Terms have multiple senses

A single definition per term is a modelling error that shows up in week one.

| Term | Senses |
|---|---|
| `cap` | a lie · a hat · an upper limit |
| `bet` | agreement/"okay" · a wager |
| `sick` | excellent · unwell |
| `slaps` | is very good · hits |

The store keys senses to a term, and a lookup can legitimately return more than
one. Where context is available, the reply leads with the sense that fits it and
mentions the others briefly.

---

## 4. Slang decays

Terms die, and worse, they shift meaning while keeping the same spelling.
"Skibidi" is already dated. A store with no notion of recency will confidently
give a 2023 meaning for a term whose sense has moved.

- Every sense carries `first_seen` and `last_seen`.
- Confidence **decays** with time since `last_seen`. An entry nobody has looked
  up in months is a re-verification candidate, not a fact.
- A term looked up frequently but answered with low confidence is the strongest
  signal that the store needs a human's attention.

---

## 5. Bot (V1)

**Platform: Telegram.** Free, instant setup, no business approval.

**Flow**
- User sends a term, or a whole message they did not understand
- Store first; Claude on a miss
- Reply: **short definition + example**, e.g.
  `"rizz" = charisma, especially flirting skill. "he's got mad rizz."`
- Multiple senses → lead with the contextual fit, note the others in one line
- No slang found → say so plainly

**Commands**: `/help`, and a report path so a user can flag a wrong definition —
which is the cheapest possible source of review signal.

---

## 6. Extension (V2) — context menu, not content script

**Select text → right-click → definition.** Built on `contextMenus` rather than
a content script that reads pages.

Compared with the original plan:

| | Content script | Context menu |
|---|---|---|
| Reads pages continuously | yes | **no** |
| Per-site selectors to maintain | yes | **none** |
| Sites supported | 1–2 at first | **every site, immediately** |
| Breaks on a site redesign | constantly | **never** |
| ToS exposure | high | **low — the user invokes it on their own selection** |

It is less code, more robust, and does not require choosing which platform to
risk first. `activeTab` plus `contextMenus` is enough; no broad host
permissions, and no `<all_urls>`.

**Still personal-use and unpublished** until each target platform's terms have
been reviewed individually. That caveat survives from the first draft.

**Only the selected term leaves the browser.** Never the page, never the
surrounding conversation, never a URL.

---

## 7. What Claude does

1. **Definition on a miss** — defines an unseen term in the house format, with a
   confidence level, and the result is stored as unverified.
2. **Slang detection in context** — identifies which words in a message are
   actually slang, and says "none" when that is the answer.
3. **Sense disambiguation** — picks which stored sense fits the context.

Claude does **not** normalise scraped text, because there is no scraped text.

---

## 8. Content policy

The purpose is comprehension. Someone met a word they did not know and wants to
understand it — including crude and offensive words. A person who does not
realise a slur is being aimed at them is exactly who this should help. So the
policy is **explain accurately, do not endorse**, not "refuse".

- **Slurs** are defined neutrally and descriptively — "a derogatory term for X"
  — and **never with a usage example**, since an example models using it. This
  is the one hard rule.
- Entries carry content flags (`sexual`, `vulgar`, `slur`, `violent`). The flag
  is **shown next to the definition, not used to hide it** — see §12. Somebody
  asked; the answer is the product.
- Definitions are short, neutral and in plain English. The tool explains; it
  does not lecture, and it does not perform the register it is describing.

**Gen Alpha slang means some users are children.** That is a reason the flags
must actually be applied, and a reason the audience question below matters.

---

## 9. Privacy

What somebody looks up is more sensitive than it appears — a teenager checking a
sexual term, or someone checking a slur that was aimed at them.

- `lookups` stores the **term and a timestamp only**. Never the surrounding
  message, never the page, never the URL.
- Retention is short, and aggregate counts are kept rather than per-user rows
  once a term has been reviewed.
- Flags describe the term, never the person who asked.

---

## 10. Data model

```sql
terms(id, term, normalised, first_seen, last_seen)
senses(id, term_id, definition, example, register, content_flags,
       confidence, verified, source, first_seen, last_seen)
aliases(term_id, variant)              -- "no cap" / "nocap" / "🧢"
lookups(term_id, looked_up_at, found_locally)   -- no user id after review
review_queue(sense_id, reason, queued_at)       -- unverified, decayed, reported
```

`source` is `manual_seed`, `claude`, or `user_report`. A sense sourced `claude`
is never `verified` without a human.

---

## 11. Roadmap

**Phase 0 — Prep** ✅
Telegram bot via @BotFather. Hand-write the ~50-term seed list with senses,
examples and flags. *Shipped as 56 terms / 67 senses — written by Claude rather
than by hand, so they carry `source: claude`, `verified: false` and all went
into the review queue. Calling them `manual_seed` would have been the
convenient lie.*

**Phase 1 — Bot** ✅
Store, lookup, sense disambiguation, Claude fallback on a miss, reply
formatting, the "no slang here" path, `/report`.

**Phase 2 — Review** ✅
Review queue, verification flow, confidence decay, promotion from unverified.
*(This is what remains of the old "data pipeline" phase — much smaller.)*

Two things worth recording, because both are places the design was wrong and
had to change rather than be worked around:

- **§10's schema needed amending before promotion was possible at all.**
  Phase 1 encoded "a Claude entry is never auto-verified" as
  `CHECK (NOT (source = 'claude' AND verified = 1))`, which forbids *any*
  verification, including a person's. Since every entry in the store is
  `source: claude`, nothing could ever have been promoted. Migration 002
  rebuilds the table with `verified_by` / `verified_at`, and the constraint
  becomes "not verified with nobody's name on it". `source` still records the
  real origin after promotion — a verified entry stays `claude`.
- **Decay measured from `last_seen` cannot see a popular wrong entry.** Every
  lookup refreshes `last_seen`, so a frequently-asked term never looks stale
  however unsure its definition is. That is why §4's second signal — looked up
  often, answered with low confidence — is implemented as its own sweep rather
  than being treated as a restatement of the first.

**Phase 3 — Extension** ✅
Manifest V3, `contextMenus`, `activeTab`. Same store as the bot.

Two things the spec did not anticipate:

- **It needed a backend, which did not exist.** Rule 17 forbids an API key in
  the extension bundle, and until now the only entry points were a
  long-polling bot and a CLI. `src/server/` is a one-endpoint HTTP surface on
  loopback that calls the *same* `handleMessage` the bot does — one lookup
  path and one formatter across both clients, so the content rules are
  enforced in one place rather than re-implemented in the extension where they
  could drift.
- **`activeTab` turned out to be unnecessary.** `contextMenus.onClicked`
  delivers `selectionText` on its own, and nothing in the extension ever
  touches the page, so the manifest ships with `contextMenus` alone — tighter
  than §6 and rule 15 allow rather than merely within them.

A selection cap (300 characters) enforces "never the page" against the obvious
defeat, which is Ctrl+A followed by a right-click.

**Phase 4 — Polish** ✅
Aliases and variants, regional senses, most-looked-up prioritisation.

- **Variants are resolved, not stored.** Aliases stay curated — a person
  decided "nocap" and "🧢" mean "cap". Mechanical shapes of the same word
  ("capping", "capped", "no-cap", "bussin'") are generated at lookup time and
  tried only after an exact and an alias match have both missed, so a wrong
  guess falls through to Claude rather than answering as the wrong entry.
  Matching is separator-insensitive on *both* sides, because "no cap" can
  generate "nocap" but nothing can tell you where to put the space back.
  Deliberately not recorded: which variant a user typed. That is their own
  text, and `lookups` holds a term id and a timestamp (§9).
- **Regional senses are rows, with a `region`.** See §13.
- **The queue is ordered by demand.** Within a reason, the terms people
  actually ask about come first, so the entries served most often are the ones
  a human has checked. `npm run review -- top` shows demand directly, marking
  what is still unverified — the top unverified row there is the highest-value
  review in the store.

**Phase 5 — Correction, control, and context** ✅
Reviewer editing, a routing fix, an inverted alias, and cost.

- **A reviewer can correct an entry, not only bless or bounce it.** `verify`
  and `reject` were the whole vocabulary, so a definition Claude got slightly
  wrong could only be promoted with the error in it or left unverified for
  ever. `src/review/edit.ts` adds edit, example, flags, region, confidence,
  sense add/rm, and add. Editing never promotes, never rewrites `source` — a
  corrected Claude definition is still a Claude definition — and editing an
  entry that is already verified re-stamps the reviewer's name, because the
  previous one never saw the new wording. Changes validate as a whole sense
  through `parseSense`, which is what catches flagging a sense as a slur while
  it still carries an example (§8's one hard rule, arriving by the back door).
  `add` is the only path that produces `manual_seed`.
- **A short sentence is a sentence.** The bare-term branch treated three words
  or fewer as a named term, and `defineTerm` returns the string it was handed
  verbatim, so "he's got rizz" was written into `terms` as a row with that
  name. Multi-word terms were never affected — store-first answers them — so
  only the miss path changed, and it now asks detection what the slang is.
- **An alias must mean the same thing as its term.** "no cap" shipped as an
  alias of "cap" and answered with the opposite meaning under a headword the
  user never typed. It is its own term now. Nothing mechanical can catch this
  class, so it is written down where the next alias gets added.
- **Cost is counted and capped.** `lookups.found_locally` had been written on
  every lookup since Phase 0 and read by nothing; `review -- stats` now shows
  the hit rate. `claude_calls` records model, purpose and time — never the term
  — and `SLANG_DAILY_CALL_LIMIT` (default 200 per UTC day) stops a loop
  spending unwatched. Past the ceiling the store keeps answering.

---

## 12. Audience: everybody, non-specific

**Settled.** This is a dictionary, and a dictionary does not have a target
demographic. A parent reading their kid's messages, a teacher marking an essay,
a non-native speaker reading anything at all, and someone who is merely curious
all want the same thing from it: what does this word mean.

That is a real decision, not a deferral, and three things follow from it.

**Plain language, no in-group register.** Definitions are written for a reader
with no context whatsoever. No slang inside the explanation, no "iykyk", no
assuming they know an adjacent term. `"delulu" = deluded, usually said
half-jokingly about someone's unrealistic hopes` — not `"delulu" = when you're
being lowkey unhinged about your situationship`. The second is funnier and
useless to most of the people asking. Short sentences and simple English also
serve the non-native reader, who is a large part of "everybody".

**Flag visibly; never hide, never embellish.** Somebody asked what a word
means, and refusing to say is the single failure that breaks this for every
audience at once — most sharply for the person who was called something and
wants to know what it was. So the definition always appears. What changes is
the framing around it: a short label (`vulgar`, `sexual`, `slur`) sits with the
entry so nobody is ambushed, the wording stays clinical rather than colourful,
and slurs carry no usage example. That resolves the old "filter or flag"
question — **flag, and show**.

**No age gate.** It cannot be verified and would not help; the flags carry the
information a reader needs to decide for themselves. Gen Alpha slang means some
readers are children, which is a reason the flags must actually be applied, not
a reason to withhold meanings.

It also confirms the context-menu extension. A context menu works identically
for a parent reading a text, a teacher reading an essay, and a reader on a site
nobody thought to integrate with — which a per-site content script would not.

## 13. Open questions

- ~~Personal use only, or shared with friends?~~ **Personal use, for now** —
  which is what §6 and rule 18 already required regardless ("unpublished and
  personal-use until each target platform's terms have been reviewed
  individually"), so Phase 3 built for it rather than treating the question as
  open. Still genuinely undecided is whether to *do* that ToS review and
  share. It is a bigger change than it sounds: the backend currently binds
  loopback with no auth and no rate limiting, and sharing turns it into a
  hosted service holding a Claude key on other people's behalf. Not a
  deployment step — a different product with different obligations.
- ~~Do regional and community-specific senses need their own rows, or a note on
  the sense?~~ **Their own rows**, each carrying a `region`. This is §3's
  argument one level down: "a single definition per term is a modelling error
  that shows up in week one", and a single sense covering two regions is the
  same error again. UK "bare" (meaning "very") is not a shade of some other
  sense of *bare*; it is a separate meaning that happens to be geographically
  bounded. A note inside another sense's prose would hide a real sense in a
  footnote, where disambiguation cannot reach it and context cannot lead a
  reader to it. `region` is NULL by default, which reads as "not known to be
  regional" rather than as a claim to be universal.

Stack per `../AI_PROJECTS.md`: Node 20+ / TypeScript, grammY,
`@anthropic-ai/sdk`, SQLite.
