# AGENTS.md — build-features (shared)

Shared conventions for both daemons. Per-project triggers, test rules, and
file-ownership tables live in each submodule's own `AGENTS.md`.

## Project Overview
macOS Python background daemons. en-th-word-swap and num-to-text use
CGEventTap for system-wide keyboard monitoring; morse-code uses CGEventTap
only for its Option+M hotkey. All three share the architecture patterns
documented in the root `CLAUDE.md`.

## Key Commands
- Install deps (en-th): `pip3 install pyobjc pythainlp --break-system-packages`
- Install deps (num):   `pip3 install pyobjc num2words --break-system-packages`
- Install deps (morse): `pip3 install pyobjc --break-system-packages`
- Install daemon: `bash <project>/install.sh`
- Uninstall:      `bash <project>/uninstall.sh`
- View logs:      `tail -f ~/Library/Logs/<project>.log`

## Code Style
- Python 3.10+ type hints required
- No f-strings for log messages (use `%` formatting for performance)
- All public functions need docstrings
- Max line length: 100 chars
- No bare `except:` — always catch specific exceptions

## Git Workflow
- Branch: `feat/<name>`, `fix/<name>`, `refactor/<name>`
- Commit: conventional commits (feat:, fix:, refactor:, docs:, test:)
- Never commit `cache/` directory contents
- Never commit files containing real keylog data
- Always run security-reviewer before merging to main

## Shared Testing Rules
- Mock CGEventTap in ALL tests (never call a real event tap in CI)
- Use `unittest.mock.patch` for all PyObjC/macOS API calls
- Coverage target: 80% on conversion logic files
- Per-project test details: see each submodule's `AGENTS.md`

## Shared Architecture Constraints
- CGEventTap: `kCGHeadInsertEventTap` (intercept before apps)
- NSPanel: `NSNonActivatingPanelMask` + `NSFloatingWindowLevel`
- Cache files: JSON format in each project's own `cache/` directory
- Daemon threads: always `daemon=True`
- Network: only in `updater.py`, max once per 24h per project

## Shared Agents
| agent | when to use |
|-------|-------------|
| `macos-api-specialist` | any CGEventTap / NSPanel code |
| `build-error-resolver` | immediately on any ImportError / AttributeError |
| `code-reviewer` | immediately after writing or modifying code |
| `security-reviewer` | before any merge to main |

Domain-specific agents (`thai-lang-validator`, `num-converter-validator`) are
documented in their respective submodule `AGENTS.md`.
