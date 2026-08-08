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

None of the class-1 rules (CGEventTap, NSPanel, Accessibility, `_synth_pending`,
`cache/`) apply to class 2, and vice versa.

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
- `git push` + merge to main are done by the user (see `.claude/settings.json`)

## Project Paths

Class 1 — daemons (submodules):
- en-th-word-swap: ~/build-features/en-th-word-swap/  (rules: its own CLAUDE.md)
- num-to-text:     ~/build-features/num-to-text/      (rules: its own CLAUDE.md)
- morse-code:      ~/build-features/morse-code/       (rules: its own CLAUDE.md)

Class 2 — AI products (plain dirs, spec-only for now):
- hydration-drink-ai:     ~/build-features/hydration-drink-ai/
- slang-translator-ai:    ~/build-features/slang-translator-ai/
- job-prep-ai:            ~/build-features/job-prep-ai/
- numeral-translator-ai:  ~/build-features/numeral-translator-ai/

  Shared rules: AI_PROJECTS.md. Per-project rules: each dir's own CLAUDE.md.

Note: en-th-word-swap and num-to-text monitor/inject keystrokes system-wide;
morse-code uses CGEventTap only for its Option+M hotkey (no injection).

@AGENTS.md
@AI_PROJECTS.md
