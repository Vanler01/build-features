# Project 3: Intern / First-Jobber Job-Prep AI — Build Plan

## Vision
A non-profit helping tool for interns and first-time job seekers — finds relevant openings (Bangkok/Thailand-focused, plus global/remote), filters by what actually matters to a first jobber (commute distance, pay, fit with their major/goal), and helps them get ready: prep tips, resume guide, interview help. It's a suggestion tool, not a data broker — it doesn't collect identity data, and it doesn't sell or profile users.

---

## 0. Core Principles (non-negotiable)
- **No sensitive personal data collected** — no full legal name required beyond a display name, no ID numbers, no face/biometric data, no degree/transcript verification.
- **No phone number** — email-only login (magic link or simple password).
- **Non-profit framing** — the tool exists to help, not to harvest data for recruiters or advertisers. No selling user data, no dark patterns.
- Users self-describe their major/field and goals in plain text — nothing is verified or cross-checked against official records.

---

## 1. Job Search & Matching

**Thailand / Bangkok focus:**
- **JobThai** has a public GraphQL API (`api.jobthai.com/v1/graphql`) that's openly accessible with no proxy needed — supports filtering by keyword, province, job type, salary range, and work arrangement (hybrid/WFH). This is the primary Thailand source since it's a real API, not a scrape.
- **JobsDB Thailand** has no official public API, so it'd need a scraping layer as a secondary source to broaden coverage beyond JobThai alone.

**Global / remote:**
- **LinkedIn and Indeed have no public self-serve job-search APIs** — LinkedIn's official API is partner-only (LinkedIn isn't accepting new partners) and Indeed requires paid scraping tools. Rather than scraping those directly (ToS risk for a personal project), lean on an aggregator.
- **Adzuna API** — genuinely free tier (1,000 calls/month), covers ~16-19 countries (US, UK, Singapore, India, Australia, etc.) but **not Thailand** — good fit for the "global/remote" half specifically, complementing JobThai for the Thailand half.

**Matching logic:** user describes their major and goal in plain text (e.g., "marketing major, want an internship, prefer Bangkok, ok with hybrid"), Claude scores/ranks pulled listings against that description — no resume required just to search.

---

## 2. Distance & Location (Google Maps)

Reuses the same pattern as Project 1's Nearby Places feature:
- User sets a home/base location (or lets the app use current location)
- For each job listing with an address, call **Google Maps Directions API** (or Distance Matrix API) to get commute distance/time by the user's preferred mode (transit, car, walk)
- Let the user sort/filter listings by commute time, not just distance — more useful for Bangkok traffic than raw km
- Tapping a listing's location opens Google Maps for the office address, same deep-link pattern as Project 1

**Cost note:** Distance Matrix/Directions API is a different SKU from Places Nearby Search (used in Project 1) — has its own free monthly allowance under the same Google Cloud project, worth checking actual current limits when this phase starts since Google's pricing tiers shift.

---

## 3. Prep Features

- **Basic prep tips** — for a given role/industry, Claude generates a short "what to expect" brief: typical interview format, common early tasks, skills worth brushing up on.
- **Resume guide** — user pastes or uploads resume text, Claude gives structured feedback (clarity, relevant keywords for the role, formatting suggestions) — doesn't store the resume longer than needed to give feedback.
- **Interview help** — Claude generates likely questions for the specific role/company type, and helps the user practice answers (e.g., mock Q&A in the bot/app).

---

## 4. Data Model (rough, privacy-minimal)

- `users` — id, email, display_name, base_location (optional, user-set), major/field (free text), goal (free text)
- `job_sources` — cached listings pulled from JobThai/JobsDB/Adzuna: title, company, location, salary_range, work_type, source, url, fetched_at
- `saved_jobs` — user_id, job_id, commute_time (cached), notes
- `resume_sessions` — user_id, resume_text (temporary, purge after N days), feedback_given
- No `id_verification`, `phone`, or `document_upload` tables — intentionally excluded

---

## 5. Build Roadmap

**Phase 0 — Prep**
- Register for JobThai API access (public, no key noted as required — confirm exact auth needs when building)
- Get an Adzuna free API key (App ID + App Key, free signup)
- Reuse Project 1's Google Cloud project/API key, enable Directions or Distance Matrix API
- Decide auth approach (email magic-link library, e.g., Supabase Auth or a simple custom email-link flow)

**Phase 1 — Core Search**
- Pull + normalize listings from JobThai (Thailand) and Adzuna (global/remote) into one schema
- Basic keyword/location filter UI (bot or simple web form)
- Claude-based matching against user's major/goal description

**Phase 2 — Distance Integration**
- Google Maps commute calculation per listing
- Sort/filter by commute time
- Deep-link to Google Maps for the address

**Phase 3 — Prep Tools**
- Resume feedback flow (paste text → Claude feedback, no long-term storage)
- Role-specific prep tips generator
- Interview mock Q&A flow

**Phase 4 — Polish**
- JobsDB Thailand secondary source (scraper) to widen Thai coverage beyond JobThai
- Saved-jobs list + simple tracking (applied/interviewing/etc., all self-reported, nothing verified)
- Expand Adzuna countries if useful, or add another aggregator for markets it misses

---

## Open Questions to Settle Before Coding
- Platform: bot (Telegram) first like the other two projects, or does this one make more sense as a simple web app from the start, given resume text and job lists are easier to read on a screen than in a chat?
- Should saved/applied job tracking exist at all, or is this purely search + prep with nothing persisted long-term (more privacy-minimal but less useful over time)?
- Resume text storage: fine to keep temporarily for the session, or should it never be stored server-side at all (processed and discarded immediately)?

Sources: [JobThai API scraper details](https://apify.com/mai_amm/jobthai-com-scraper), [JobsDB Thailand scraper](https://apify.com/mai_amm/jobsdb-thailand-scraper/api), [LinkedIn Jobs API access](https://coldiq.com/blog/best-linkedin-jobs-apis), [Adzuna free API tier & coverage](https://jobspipe.dev/blog/adzuna-api)
