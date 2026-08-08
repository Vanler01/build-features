# AGENTS.md — numeral-translator-ai

Project rules: `CLAUDE.md` (this dir). Shared class rules: `../AI_PROJECTS.md`.
Spec: `REQUIREMENTS.md`.

## Key Commands
```bash
pip3 install num2words unicode-rbnf python-telegram-bot anthropic --break-system-packages
python3 -m pytest numeral-translator-ai/tests -q
ruff check numeral-translator-ai/
python3 -c "from num2words import CONVERTER_CLASSES as c; print(len(c), sorted(c)[:20])"
```
(No code exists yet — these are the intended commands once Phase 1 starts.)

## Agents

| agent | when to use |
|---|---|
| `numeral-system-validator` | Mode A — digit scripts, Roman, Chinese/Japanese numerals, historical systems. MUST BE USED before changing any conversion algorithm |
| `numeral-wordform-validator` | Mode B — num2words coverage, CLDR RBNF, ordinals/gender/classifiers, Thai financial form. MUST BE USED before changing word-form logic |
| `numeral-provenance-guard` | **MUST BE USED before any commit.** Enforces the tier order and that every answer states its source; catches unlabeled Claude output |
| `numeral-bot-specialist` | any Telegram handler, ambiguous-input flow, target-selection UI, or output formatting |

Do **not** use `num-converter-validator` here — it belongs to the `num-to-text`
submodule and asserts that project's overlay behaviour. Read `../num-to-text/`
for reference, but validate this project with the `numeral-*` agents.

## File ownership (planned)
| area | owner agent |
|---|---|
| `systems/*.py` (roman, cjk, unicode digits) | `numeral-system-validator` |
| `words/*.py` (num2words, rbnf, classifiers) | `numeral-wordform-validator` |
| resolution order, source labels, `lookups` | `numeral-provenance-guard` |
| `bot/*.py` | `numeral-bot-specialist` |

## Testing rules
- Mock Telegram and Claude. `num2words` and `unicodedata` are deterministic
  local libraries — call them for real in tests.
- **Round-trip property tests are the standard**: for each supported system,
  `parse(render(n)) == n` across the full valid range, not sampled examples.
- Every system declares its bounds and has an explicit out-of-range test
  (Roman > 3999, negatives, fractionals in scripts that lack them).
- Provenance tests assert that a Claude-fallback answer is always labeled and
  never written to `numeral_systems` / `number_words`.
- Cross-check Thai financial output against `../num-to-text/` behaviour.
- 90% coverage on conversion logic — higher than the class default of 80%,
  because a wrong number is a real error.
