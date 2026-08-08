# AGENTS.md — hydration-drink-ai

Project rules: `CLAUDE.md` (this dir). Shared class rules: `../AI_PROJECTS.md`.
Spec: `REQUIREMENTS.md`. Approved plan: `~/.claude/plans/gentle-weaving-candy.md`.

## Key Commands
```bash
pip3 install -r requirements.txt --break-system-packages
python3 -m pytest -q      # from hydration-drink-ai/
ruff check .
```

Adapters call the Telegram and LINE HTTP APIs through `httpx` directly, not
through the vendor SDKs — `MessagingPort` already owns the handler model, and
each SDK would bring a competing one. See `requirements.txt` for the reasoning.

## Agents

| agent | when to use |
|---|---|
| `hydration-bot-specialist` | any Telegram or LINE handler, reminder scheduler, photo/location message, or inline keyboard |
| `hydration-parse-validator` | any change to Claude text/vision parsing or the log-entry schema. MUST BE USED before changing a prompt or schema |
| `hydration-drink-sourcer` | building or expanding the seed drink catalog from Open Food Facts / USDA / caffeine references |
| `hydration-drink-data-validator` | any change to catalog values. MUST BE USED after the sourcer runs and before editing the catalog by hand |
| `hydration-privacy-guard` | **MUST BE USED before any commit** touching users, body weight, the age gate, email auth, or location |
| `hydration-places-guard` | any Google Places call, quota/field-mask change, deep link, or location handling |

The sourcer and the data-validator are a pair: **sourcer acquires, validator
verifies.** Never let the sourcer's output ship without the validator's pass —
its whole design assumes an independent check.

Do **not** use `security-reviewer`, `macos-api-specialist`, or the other
daemon-class agents here — they check for CGEventTap and keystroke logging and
will pass meaninglessly.

## File ownership (planned)
| area | owner agent |
|---|---|
| `adapters/telegram.py`, `adapters/line.py`, scheduler | `hydration-bot-specialist` |
| `ai/parse.py`, prompt + JSON schema | `hydration-parse-validator` |
| `data/drinks_seed.json` (writes) | `hydration-drink-sourcer` |
| `data/drinks_seed.json` (verification) | `hydration-drink-data-validator` |
| `core/users.py`, health/age/auth, migrations | `hydration-privacy-guard` |
| `places/*.py`, deep links | `hydration-places-guard` |

## Testing rules
- Mock Telegram, LINE, Claude, Google Places, and the nutrition APIs in every
  test — no live calls, no quota burn. LINE's free tier is 300 pushes/month.
- Keep one recorded fixture per external API; assert parsers against the fixture.
- Vision tests use a committed sample image + a recorded Claude response.
- **Sync property test (highest risk):** widget-offline adds, app edits, and bot
  logs must converge to the same day total regardless of arrival order, with
  duplicate UUIDs applied exactly once.
- **Timezone tests:** day rollover and bedtime states for a user several zones
  from the server.
- Privacy tests assert absence: no DOB column, no weight in any prompt or log,
  no alcohol in a bot-facing list.
- 80% coverage on parsing, sync, and nutrition-lookup logic.

## Manual verification (widgets)
Emulators do not reproduce iOS timeline budgets or Android launcher gesture
interception. On real hardware, verify: tap latency, the 4s undo window, color
transitions at bedtime−10min, Android resize, and Android haptic strength on +
versus −.
