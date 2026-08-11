# AGENTS.md — slang-translator-ai

Project rules: `CLAUDE.md` (this dir). Shared class rules: `../AI_PROJECTS.md`.
Spec: `REQUIREMENTS.md`.

## Key Commands
```bash
npm install                 # grammY, @anthropic-ai/sdk, better-sqlite3
npm run dev                 # bot, long polling
npm test                    # vitest
npm run lint                # eslint + tsc --noEmit
npm run seed                # load the seed vocabulary (idempotent)
npm run review              # work the review queue — see below
npm run serve               # backend for the extension, 127.0.0.1:8787
npm run build:extension     # extension/src/*.ts → extension/dist/*.js
```
Note there is no `scrape` command, and there should never be one.

### Extension (Phase 3)
Load `extension/` unpacked at `chrome://extensions` with Developer mode on;
`npm run serve` must be running. Details and the permission rationale are in
`extension/README.md`. The manifest asks for `contextMenus` and nothing else —
no `activeTab`, no `host_permissions`, no content script.

### Review queue (Phase 2)
```bash
npm run review                                   # open items, reports first
npm run review -- show <term>                    # senses, flags, stored vs aged confidence
npm run review -- verify <term> --by <you>       # the only path to verified
npm run review -- reject <term>                  # looked, not confirmed; clears the item
npm run review -- unverify <term>                # send a verified entry back
npm run review -- alias <term> = <variant>       # record an irregular spelling
npm run review -- top                            # most looked-up terms
npm run review -- sweep                          # queue stale + low-confidence entries
npm run review -- stats
```

Correcting an entry (Phase 5) — sense numbers are the ones `show` prints:
```bash
npm run review -- edit <term> <n> = <definition>       # rewrite one sense
npm run review -- example <term> <n> = <text>          # empty text clears it
npm run review -- flags <term> <n> = vulgar,slur       # empty clears them
npm run review -- region <term> <n> = UK               # empty clears it
npm run review -- confidence <term> <n> = medium
npm run review -- sense add <term> = <definition>
npm run review -- sense rm <term> <n>                  # never the last one
npm run review -- add <term> = <definition> --by <you> # the only manual_seed path
```
Editing never promotes anything to verified and never rewrites `source` — a
corrected Claude definition is still a Claude definition. Editing an entry that
is *already* verified needs `--by`, because the name on it belongs to whoever
confirmed the old wording; the change is validated as a whole sense, so
flagging one as a slur while it still carries an example is refused (rule 11).

`list` and `top` are ordered by how often a term is looked up, so the entries
being served most are reviewed first. `alias` is for irregular spellings only —
plurals, `-ing`/`-ed` and run-together phrases resolve on their own via
`src/store/variants.ts` and are never written to the database. An alias must
mean the *same* thing as its term: a negation or an antonym gets its own entry,
because "no cap" aliased to "cap" answers with the opposite meaning.
The `--` matters: without it npm eats `--by` and the reviewer name is lost.
`SLANG_REVIEWER=<you>` works instead of the flag. The CLI needs no API keys and
makes no network calls — re-verification is a person reading an entry, not a
model grading its own homework.

## Agents

| agent | when to use |
|---|---|
| `slang-bot-specialist` | any grammY handler, lookup flow, sense disambiguation, or reply formatting |
| `slang-cache-validator` | any change to the store or the lookup path. **MUST BE USED** — it is the check that no scraper has reappeared and that no Claude answer was auto-verified |
| `slang-content-filter` | any change to how definitions are worded or flagged. MUST BE USED before shipping definition output |
| `slang-extension-specialist` | any Manifest V3 work. MUST BE USED before committing extension code |

`slang-cache-validator` replaced `slang-vocab-pipeline-validator`, which policed
a scraping pipeline that no longer exists. If you find a reference to the old
name, it predates the redraft.

Do **not** use the daemon-class agents from the root `AGENTS.md` here.

## File ownership (planned)
| area | owner agent |
|---|---|
| `src/bot/*.ts`, `src/server/*.ts` | `slang-bot-specialist` |
| `src/store/*.ts`, `src/review/*.ts`, `data/seed.json` | `slang-cache-validator` |
| definition wording, content flags | `slang-content-filter` |
| `extension/manifest.json`, `extension/src/*.ts` | `slang-extension-specialist` |

(The ownership table predates the code and said `extension/background.ts`; the
file landed at `extension/src/background.ts` because the extension needs its
own TypeScript build.)

## Testing rules
- Mock Telegram and Claude. Nothing may reach a network — and since there is no
  scraper, a test that makes an outbound request to a vocabulary source is
  itself a defect worth investigating.
- **The precision cases are mandatory**, because over-flagging is what kills
  this product. At minimum: a sentence with one slang term, a sentence with
  none, and a sentence using a slang word in its ordinary sense
  ("I'll bet you £5"). "Nothing unusual here" must be a passing answer.
- **Sense cases**: `cap` (lie / hat / limit) and `bet` (agreement / wager) must
  each return more than one sense, and the contextual one must lead.
- **Cache cases**: a miss writes back as unverified; a second lookup of the same
  term is served locally; nothing is promoted to `verified` without an explicit
  review action.
- **Decay**: an entry with an old `last_seen` loses confidence and reaches the
  review queue.
- **Content cases**: a slur returns a neutral definition and **no example**; a
  vulgar-but-harmless term is flagged rather than dropped.
- **Privacy assertion**: `lookups` never contains a message body, page or URL.
- 80% coverage on lookup, detection, and sense-resolution logic.
