# build-features — macOS Background Daemons

Monorepo umbrella for Python background daemons on macOS. Each program is an
independent git submodule with its own repo, tests, and `cache/`.

- **en-th-word-swap** — keyboard layout fix (EN↔TH mistype correction)
- **num-to-text** — number-to-words floating overlay

> Per-project rules live in each submodule's own `CLAUDE.md`. When working
> inside a submodule, Claude Code loads this root file **and** the submodule's
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
- en-th-word-swap: ~/build-features/en-th-word-swap/  (rules: its own CLAUDE.md)
- num-to-text:     ~/build-features/num-to-text/      (rules: its own CLAUDE.md)

@AGENTS.md
