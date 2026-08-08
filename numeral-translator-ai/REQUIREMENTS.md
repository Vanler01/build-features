# Project 4: Universal Numeral Translator — Build Plan

## Vision
Translate any number, in any form, to any other form: between **numeral systems** (how digits are written — Arabic 123, Thai ๑๒๓, Roman CXXIII, Chinese 一二三, Devanagari, etc.) and between **number words** (how numbers are spoken/written out — "one hundred twenty-three" vs "หนึ่งร้อยยี่สิบสาม" vs "cent vingt-trois"), across languages, both directions. Same bot-first pattern as the other three projects unless you'd rather start elsewhere.

**Note:** this overlaps conceptually with the existing `num-to-text` submodule already in this folder (English number-to-words overlay) — worth treating this project as either a generalized successor to it or a sibling that shares logic, decide when we get to implementation.

---

## 1. Scope — Two Conversion Modes

**Mode A — Numeral systems (digit scripts):** converting how a number is *written as symbols*.
- Most of this doesn't need scraping — Unicode already encodes digit properties for many scripts (Arabic-Indic, Devanagari, Thai, Bengali, etc.), so digit-to-digit conversion across those is a lookup/algorithm, not a data-gathering problem.
- Roman numerals, Chinese/Japanese numeral characters, and other non-positional systems need dedicated conversion algorithms (well-documented, not scraped).
- Scraping matters here mainly for **historical/rare systems**: Mayan, Babylonian cuneiform, Egyptian hieroglyphic, Attic Greek, Chinese counting rods, Kaktovik Iñupiaq (Base-20 Inuit numerals), etc. — these aren't in standard libraries and need to be sourced from reference sites.

**Mode B — Number words (spoken/written-out form):** converting a number into the actual words of a language.
- **num2words** (open-source Python library) already covers 30+ languages for cardinal/ordinal/year/currency word forms including Thai, Chinese, and most major European/Asian languages — this should be the backbone rather than scraping from scratch.
- Scraping fills the gap for languages num2words doesn't cover (many regional/minority/indigenous languages) and for richer grammatical forms (gendered numbers, counters/classifiers in languages like Thai/Japanese/Chinese that change words depending on what's being counted).

---

## 2. Data Sourcing (scraping targets, for the gaps)

- **Wikipedia — "List of numeral systems"** and individual numeral-system articles — good structured starting point for historical/regional systems (Mode A gaps)
- **Omniglot's numbers pages** — per-language number word lists, useful for languages missing from num2words (Mode B gaps)
- **Unicode CLDR RBNF (rule-based number format) data** — the same data ICU/CLDR uses to spell out numbers in many languages; coverage varies by language (complete for English, partial elsewhere, notably expanded for Arabic, Thai, and others) — a stronger source than ad hoc scraping where it's available, since it's structured rule data rather than a prose page
- **Claude as fallback** for anything not covered by the above — flagged in the output as an AI best-effort estimate rather than a verified conversion, since accuracy matters more here than in the slang translator (a wrong number is a real error, not just an imperfect vibe)

---

## 3. Bot MVP

**Platform: Telegram** (consistent with the other projects).

**Flow:**
- User sends a number in any form: digits, words, or a mixed/ambiguous phrase ("๑๒๓", "one hundred twenty-three", "CXXIII")
- User specifies (or the bot asks) the target: which numeral system or which language's word form
- Bot resolves: library/Unicode lookup first (fast, reliable) → scraped reference data second → Claude fallback last, with the source of the answer shown so the user knows how confident to be ("via num2words" vs "AI estimate — verify for critical use")

---

## 4. AI Components (what Claude actually does)

1. **Parsing ambiguous input** — recognizing what number and what system/language the user typed, especially for mixed-script or informal input.
2. **Fallback conversion** — generating a best-effort answer for systems/languages not covered by the library or scraped dataset, clearly labeled as unverified.
3. **Data cleaning** — normalizing scraped Wikipedia/Omniglot content into a consistent lookup format (number → system/language → written form).

---

## 5. Data Model (rough)

- `numeral_systems` — id, name, type (positional/additive/etc.), script, source (unicode/algorithm/scraped), notes
- `number_words` — language, number_value, cardinal_form, ordinal_form, source (num2words/CLDR/scraped/AI-fallback)
- `lookups` — user_id, input, resolved_value, target, source_used, timestamp — useful for seeing which systems/languages get requested most, to prioritize filling gaps

---

## 6. Build Roadmap

**Phase 0 — Prep**
- Stand up num2words as a dependency, confirm which languages/features (cardinal/ordinal/currency) are actually usable out of the box
- Pull Unicode digit-script data (via Python's `unicodedata` or CLDR) for the major positional numeral systems
- Pick an initial short list of historical/rare systems to hand-seed (Roman, Chinese/Japanese, Mayan) before wider scraping

**Phase 1 — Numeral System Conversion (Mode A)**
- Digit-to-digit conversion across Unicode-covered scripts
- Roman numeral algorithm (both directions)
- Chinese/Japanese numeral character conversion

**Phase 2 — Number Word Conversion (Mode B)**
- Wire in num2words for its full supported language list
- Bot flow: input parsing → target language selection → word-form output

**Phase 3 — Data Gap Filling**
- Scrape Wikipedia/Omniglot for systems and languages missing from Phase 1/2
- Pull CLDR RBNF spellout data where available for additional language coverage
- Claude fallback + clear "unverified" labeling for anything still missing

**Phase 4 — Polish**
- Historical/rare numeral systems (Mayan, Babylonian, hieroglyphic, counting rods)
- Grammatical richness for Mode B: ordinals, gendered forms, counters/classifiers
- Decide relationship to the existing `num-to-text` submodule (merge, share code, or keep separate)

---

## Open Questions to Settle Before Coding
- Priority order: which languages/systems matter most to you first (e.g., Thai + English + Chinese covers a lot of your existing projects' audience)?
- How important are the historical/rare systems (Mayan, hieroglyphic, etc.) vs. keeping this focused on living languages people actually need day-to-day?
- Should this stay a standalone bot, or does it make sense to fold into the existing `num-to-text` overlay tool as a language/system expansion?

Sources: [num2words GitHub](https://github.com/savoirfairelinux/num2words), [num2words language support (Cybrosys)](https://www.cybrosys.com/blog/digits-to-words-using-num2words), [Unicode CLDR RBNF spellout](https://unicode-org.github.io/cldr/ldml/tr35-numbers.html), [unicode-rbnf Python implementation](https://github.com/rhasspy/unicode-rbnf)
