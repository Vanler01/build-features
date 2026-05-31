# build-features — macOS Background Daemons

Two Python daemons for macOS: en-th-word-swap (keyboard layout fix)
and num-to-text (number-to-words overlay).

## Stack
- Python 3.10+ (Homebrew), PyObjC ≥10.0, macOS 12+
- CGEventTap for global keyboard monitoring
- NSPanel for floating overlay UI
- PyThaiNLP (en-th-word-swap), num2words (num-to-text)

## Commands
- Run: `python3 <project>/main.py`
- Check imports: `python3 -c "import Quartz; import AppKit; print('ok')"`
- Lint: `ruff check . --fix`
- Test (en-th): `python3 -m pytest en-th-word-swap/tests/`
- Test (num): `python3 -m pytest num-to-text/tests/`

## Critical Rules
1. NEVER run CGEventTap code in tests — mock it with unittest.mock
2. NEVER log raw keystrokes anywhere (security requirement)
3. Accessibility permission required before any live test
4. Each project has its own cache/ directory — do not cross-contaminate
5. NSPanel must use NSNonActivatingPanelMask to avoid stealing focus
6. All daemon threads must be daemon=True (exit with main process)

## Workflow
- Shift+Tab×2 before any feature touching ≥3 files
- Use macos-api-specialist subagent for any CGEventTap/NSPanel code
- Use thai-lang-validator subagent before changing keyboard_map.py
- Run build-error-resolver immediately on any ImportError or AttributeError

## Project Paths
- en-th-word-swap: ~/build-features/en-th-word-swap/
- num-to-text: ~/build-features/num-to-text/

@AGENTS.md
