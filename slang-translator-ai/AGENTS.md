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
```
Note there is no `scrape` command, and there should never be one.

### Review queue (Phase 2)
```bash
npm run review                                   # open items, reports first
npm run review -- show <term>                    # senses, flags, stored vs aged confidence
npm run review -- verify <term> --by <you>       # the only path to verified
npm run review -- reject <term>                  # looked, not confirmed; clears the item
npm run review -- unverify <term>                # send a verified entry back
npm run review -- sweep                          # queue stale + low-confidence entries
npm run review -- stats
```
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
| `src/bot/*.ts` | `slang-bot-specialist` |
| `src/store/*.ts`, `src/review/*.ts`, `data/seed.json` | `slang-cache-validator` |
| definition wording, content flags | `slang-content-filter` |
| `extension/manifest.json`, `extension/background.ts` | `slang-extension-specialist` |

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
