# AGENTS.md — slang-translator-ai

Project rules: `CLAUDE.md` (this dir). Shared class rules: `../AI_PROJECTS.md`.
Spec: `REQUIREMENTS.md`.

## Key Commands
```bash
npm install                 # grammY, @anthropic-ai/sdk, better-sqlite3
npm run dev                 # bot, long polling
npm test                    # vitest
npx eslint .
npm run scrape -- --dry-run # vocabulary pipeline, no writes
```
(No code exists yet — these are the intended commands once Phase 1 starts.)

## Agents

| agent | when to use |
|---|---|
| `slang-bot-specialist` | any grammY handler, lookup flow, sentence slang-detection, or reply formatting |
| `slang-vocab-pipeline-validator` | any change to the scraper, the Claude normalization step, or the vocabulary schema. MUST BE USED before changing the pipeline |
| `slang-content-filter` | any change to filtering, flagging, or how offensive terms are defined. MUST BE USED before shipping definition output |
| `slang-extension-specialist` | any Manifest V3, content-script, permissions, or tooltip work. MUST BE USED before committing extension code |

Do **not** use the daemon-class agents from the root `AGENTS.md` here.

## File ownership (planned)
| area | owner agent |
|---|---|
| `src/bot/*.ts` | `slang-bot-specialist` |
| `src/scrape/*.ts`, `src/normalize/*.ts` | `slang-vocab-pipeline-validator` |
| filtering rules, `pending_terms` review | `slang-content-filter` |
| `extension/manifest.json`, `extension/content/*.ts` | `slang-extension-specialist` |

## Testing rules
- Mock Telegram, Claude, and every scrape target. The scraper must never hit a
  live site in tests.
- Keep a recorded Urban Dictionary response and a curated-glossary page as
  fixtures; assert the normalizer against them.
- Filtering has explicit test cases for: joke/troll entry, NSFW-but-harmless
  term, and slur. All three must behave as `CLAUDE.md` specifies.
- 80% coverage on lookup, detection, and normalization logic.
