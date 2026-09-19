# build-features — macOS Daemons + AI Products

Monorepo umbrella holding **two classes of project**.

**Class 1 — macOS background daemons** (Python, PyObjC). Each is an independent
git submodule with its own repo, tests, and `cache/`. **Everything in this file
below applies to class 1 only.**

- **en-th-word-swap** — keyboard layout fix (EN↔TH mistype correction)
- **num-to-text** — number-to-words floating overlay
- **morse-code** — text ↔ Morse converter panel (Option+M hotkey)

**Class 2 — server-side AI products** (Claude API + Telegram bots). Plain
directories, not submodules. Rules live in **`AI_PROJECTS.md`** — read that
instead of this file when working in one of them.

- **hydration-drink-ai** — drink/hydration tracker (bot → mobile app)
- **slang-translator-ai** — Gen Z/Alpha slang decoder (bot → Chrome extension)
- **job-prep-ai** — intern/first-jobber job search + prep (privacy-minimal)
- **numeral-translator-ai** — universal numeral & number-word translator
- **news-digest-ai** — daily science/tech/stocks digest (scheduled push, not a
  conversational bot)

None of the class-1 rules (CGEventTap, NSPanel, Accessibility, `_synth_pending`,
`cache/`) apply to class 2, and vice versa.

## Session notes (both classes)

Four local notes files sit at the repo root. They are **git-ignored** because
this repo is public and they hold personal working notes; they may be absent on
a fresh clone. They are written in Thai.

| file | what it holds |
|---|---|
| `PROGRESS.md` | status of every project + a dated work log, newest first |
| `PARTNER.md` | how Blanc works: instruction style, git/push rules, what they value |
| `SKILL.md` | pre-"done" checklists, traps hit before, open task list |
| `LEARN.md` | how to do this work without AI — written for Blanc to learn from |

**Start of session:** read `PROGRESS.md` and `PARTNER.md`, and the matching
section of `SKILL.md`. If a note disagrees with git history or the running
system, trust the real state and fix the note.

**End of any work (finished, prepared, or paused halfway):**
- Add an entry at the top of the log in `PROGRESS.md`:
  `### YYYY-MM-DD — <project> — <topic>` with **ทำอะไรไป / สถานะ / ไฟล์ที่เกี่ยว /
  ทำต่อครั้งหน้า**. Record only what was run and verified. Keep ~10 full
  entries; fold older ones into one line each under "เก่ากว่านั้น".
- Update the status tables at the top of `PROGRESS.md` when a status changed.
- New preference or instruction style from Blanc → `PARTNER.md`.
- New trap, check, or bug pattern → `SKILL.md`; tick or add items in its task list.
- A technique worth learning by hand → `LEARN.md`.

Never commit these four files; check `git diff --cached` before every commit.

> Per-project rules live in each project's own `CLAUDE.md`. When working
> inside one, Claude Code loads this root file **and** the project's
> file (closer file overrides). This root file holds only what is **shared**.

## Stack (shared)
- Python 3.10+ (Homebrew), PyObjC ≥10.0, macOS 12+
- CGEventTap for global keyboard monitoring
- NSPanel for floating overlay UI

## Shared Critical Rules
1. NEVER run CGEventTap code in tests — mock it with `unittest.mock`
2. NEVER log raw keystrokes anywhere (security requirement)
3. Accessibility permission required before any live test
4. Each project has its own `cache/` directory — do not cross-contaminate
5. NSPanel must use `NSNonActivatingPanelMask` to avoid stealing focus
6. All daemon threads must be `daemon=True` (exit with main process)

## Shared Architecture Patterns
- CGEventTap: `kCGSessionEventTap` + `kCGHeadInsertEventTap` (intercept before apps)
- `_synth_pending` counter guards synthetic events from re-entering the callback
- `_in_password_field()` via Accessibility API checks `AXSecureTextField`
- `_kill_existing()` kills the prior instance via PID file; `atexit` cleans the PID
- NSPanel: `NSNonActivatingPanelMask` + `NSFloatingWindowLevel`
  + `NSWindowCollectionBehaviorCanJoinAllSpaces`
- 30s retry loop when Accessibility permission is missing

## Git Submodule Workflow
- Outer repo tracks submodule commit pointers only
- Commit inside the submodule first, then update the pointer in the outer repo
- `git push` prompts for approval (it is in the `ask` list in
  `.claude/settings.json`); merge to main is done by the user

Note: en-th-word-swap and num-to-text monitor/inject keystrokes system-wide;
morse-code uses CGEventTap only for its Option+M hotkey (no injection).

@AGENTS.md
