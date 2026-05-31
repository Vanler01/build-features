# AGENTS.md — build-features

## Project Overview
macOS Python background daemons using CGEventTap for system-wide
keyboard monitoring. Both projects share identical architecture patterns.

## Key Commands
- Install deps (en-th): `pip3 install pyobjc pythainlp --break-system-packages`
- Install deps (num): `pip3 install pyobjc num2words --break-system-packages`
- Install daemon: `bash <project>/install.sh`
- Uninstall: `bash <project>/uninstall.sh`
- View logs: `tail -f ~/Library/Logs/<project>.log`
- View exclusion list: `cat ~/build-features/en-th-word-swap/cache/user_learned.json`

## Code Style
- Python 3.10+ type hints required
- No f-strings for log messages (use % formatting for performance)
- All public functions need docstrings
- Max line length: 100 chars
- No bare `except:` — always catch specific exceptions

## Git Workflow
- Branch: `feat/<name>`, `fix/<name>`, `refactor/<name>`
- Commit: conventional commits (feat:, fix:, refactor:, docs:, test:)
- Never commit `cache/` directory contents
- Never commit files containing real keylog data
- Always run security-reviewer before merging to main

## Testing Rules
- Mock CGEventTap in ALL tests (never call real event tap in CI)
- Test Thai conversion logic in keyboard_map.py independently
- Test number conversion in converter.py independently
- Coverage target: 80% on conversion logic files
- Use `unittest.mock.patch` for all PyObjC/macOS API calls

## Architecture Constraints
- CGEventTap: `kCGHeadInsertEventTap` (intercept before apps)
- NSPanel: `NSNonActivatingPanelMask` + `NSFloatingWindowLevel`
- Cache files: JSON format in each project's own `cache/` directory
- Daemon threads: always `daemon=True`
- Network: only in updater.py, max once per 24h per project

## File Ownership
| File | Project | Purpose |
|------|---------|---------|
| main.py | both | CGEventTap + state machine |
| keyboard_map.py | en-th-word-swap | Kedmanee mapping + validation |
| overlay.py | both | NSPanel floating window |
| updater.py | en-th-word-swap | corpus updater + UserTracker |
| converter.py | num-to-text | number → text conversion |
| languages.py | num-to-text | AppleLanguages detection |
