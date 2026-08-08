# AGENTS.md — job-prep-ai

Project rules: `CLAUDE.md` (this dir) — read the privacy floor before anything
else. Shared class rules: `../AI_PROJECTS.md`. Spec: `REQUIREMENTS.md`.

## Key Commands
```bash
pip3 install fastapi uvicorn anthropic httpx --break-system-packages
python3 -m pytest job-prep-ai/tests -q
ruff check job-prep-ai/
```
(No code exists yet — these are the intended commands once Phase 1 starts.
Platform is still undecided: FastAPI web app vs. Telegram bot.)

## Agents

| agent | when to use |
|---|---|
| `jobprep-privacy-guard` | **MUST BE USED before any commit.** Enforces the non-negotiable privacy floor: no phone, no ID/biometrics, no verification, resume-text retention |
| `jobprep-source-validator` | any JobThai/Adzuna/JobsDB integration, normalization, caching, or quota change. MUST BE USED before adding a source |
| `jobprep-matching-validator` | any change to the Claude ranking prompt or scoring. MUST BE USED — checks fairness and prompt injection from listing text |
| `jobprep-commute-guard` | any Google Directions/Distance Matrix call, caching, or deep link |

Do **not** use `security-reviewer` here — it checks for keystroke logging.
`jobprep-privacy-guard` is this project's equivalent and is stricter about what
matters here.

## File ownership (planned)
| area | owner agent |
|---|---|
| schema/migrations, auth, retention jobs | `jobprep-privacy-guard` |
| `sources/jobthai.py`, `sources/adzuna.py`, `sources/jobsdb.py` | `jobprep-source-validator` |
| `matching/*.py`, ranking prompt | `jobprep-matching-validator` |
| `commute/*.py` | `jobprep-commute-guard` |

## Testing rules
- Mock JobThai, Adzuna, Google, and Claude. **Adzuna's free tier is 1,000
  calls/month total** — a test suite that hits it live will exhaust the budget.
- Keep one recorded response per source as a fixture; assert normalization
  against it.
- Privacy tests are mandatory and assert absence: no `phone` column, no
  document-upload route, resume text absent from logs and from storage after the
  request completes.
- Ranking tests include a listing containing an injection attempt; ranking must
  be unchanged by it.
- 80% coverage on normalization and matching logic.
