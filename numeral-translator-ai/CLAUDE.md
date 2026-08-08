# numeral-translator-ai — project rules

Translates any number to any other form: between numeral systems (Arabic 123,
Thai ๑๒๓, Roman CXXIII, Chinese 一二三…) and between number words across
languages, both directions. Telegram bot. Full spec: `REQUIREMENTS.md`.

**Status: spec-only.** No code yet. Read `REQUIREMENTS.md` first, including the
open question about this project's relationship to the existing `num-to-text`
submodule.

Shared rules for this project class: `../AI_PROJECTS.md`. This file holds only
what is specific to numeral-translator-ai.

## Stack
- Python 3.11+ (forced — `num2words` has no real JS equivalent)
- `num2words` (30+ languages, cardinal/ordinal/year/currency)
- `unicodedata` / CLDR for positional digit scripts
- `unicode-rbnf` for CLDR RBNF spellout rules
- `anthropic` — parsing ambiguous input, and **labeled** fallback only

## Critical rules

1. **Correctness outranks coverage.** A wrong number is a real error, not an
   imperfect vibe. It is always better to say "not supported" than to guess.
2. **Every answer carries its source.** The resolution order is
   **library/Unicode → seeded or scraped reference data → Claude**, and the reply
   states which tier answered ("via num2words" vs "AI estimate — verify for
   critical use"). An unlabeled Claude answer is a bug, not a cosmetic issue.
3. **Claude never writes to the reference tables.** Fallback output is returned
   to the user and may be queued for human review. It does not become seed data
   by being emitted once.
4. **Algorithms, not model calls, for anything deterministic.** Roman numerals,
   digit-script transliteration, and Chinese/Japanese numerals are solved
   problems with exact rules. Never route these through Claude.
5. **Round-trip is the test standard.** For every supported system, `to(from(n))
   == n` across the system's full valid range, not a handful of examples.
6. **State the bounds.** Roman numerals are 1–3999 in standard form; many
   historical systems have no zero and no negatives; some scripts have no
   fractional form. Out-of-range input gets an explicit error, never a
   best-effort mangling.
7. **Thai/Chinese/Japanese need more than digits.** Classifiers/counters change
   the word form depending on what's being counted, and Thai has a financial
   form (บาท/สตางค์) already implemented in `num-to-text`. Don't reimplement that
   logic blindly — see the overlap rule below.
8. **Scraped reference data is untrusted and unverified until checked.**
   Wikipedia/Omniglot entries enter as `source='scraped'` with lower confidence
   and are spot-checked before they're allowed to outrank a library answer.
   They never outrank one, in fact — the tier order in rule 2 is fixed.

## Relationship to `num-to-text`
The existing `num-to-text` submodule already does English/Thai/Chinese/Japanese
number-to-words with a financial mode, and has its own
`num-converter-validator` agent. This project is a **generalized successor or
sibling** — undecided (Phase 4). Until that's decided:
- Read `../num-to-text/` before writing conversion logic that already exists there.
- Don't modify `num-to-text` from this project.
- Where behaviour should match (Thai financial form especially), match it and
  note the source, rather than deriving a second, subtly different answer.

## Data retention
- `numeral_systems`, `number_words` — permanent reference data.
- `lookups` — input, resolved value, target, source tier, timestamp. Used to see
  which systems get requested most. No user content beyond the number itself.

## Agents
See `AGENTS.md` in this directory. `numeral-provenance-guard` MUST be run before
any commit — the source-labeling rule is the one that makes this project
trustworthy. The daemon-class agents in the root `AGENTS.md` do not apply here.
