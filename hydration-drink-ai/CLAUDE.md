# hydration-drink-ai — project rules

Reminds you to drink water, logs what you actually drink (typed, photographed, or
tapped on a home-screen widget), and points you at nearby cafes/bars. Bots
(Telegram + LINE) → app → widget, one backend. Full spec: `REQUIREMENTS.md`.
Approved plan: `~/.claude/plans/gentle-weaving-candy.md`.

**Status: spec-only.** No code yet.

Shared rules for this project class: `../AI_PROJECTS.md`. This file holds only
what is specific to hydration-drink-ai.

## Stack
- Backend: Python 3.11+, FastAPI, `python-telegram-bot`, LINE Messaging API, SQLite
- Claude: text parsing + **vision** (photo logging)
- Google Places API (New) — Nearby Search, basic field tier
- App: Flutter; **widgets are native** — SwiftUI WidgetKit + Kotlin Glance

## Critical rules

### Data and privacy
1. **Photos are processed, not kept.** Fetch, resize, send to Claude, discard.
   Never write an image to disk or the database — store the parsed entry only.
2. **Body weight is health data.** Opt-in, editable, deletable, never required.
   It must never be sent to a bot platform, never appear in a Claude prompt, and
   never be logged. Deleting it reverts the target to manual or default.
3. **Never store a date of birth.** The alcohol gate stores only
   `alcohol_unlocked` and the country used to resolve the threshold. Once the
   check passes, the age itself has no reason to exist in the database.
4. **The age gate is self-declared and must never be described as verified.**
   No ID, no document upload, no biometrics. Thresholds vary by country
   (Thailand 20, much of Europe 18, US 21) — resolve from the stated country,
   never hardcode one number.
5. **Alcohol is app-only.** The bots have no practical way to gate it, so alcohol
   drinks are not loggable or listable from Telegram or LINE.
6. **Email login is scoped to the alcohol feature.** The rest of the app works
   without an account. Do not expand it into a general login wall.
7. **Location is per-message and opt-in.** `last_known_location` is overwritten,
   never appended. No location history, and no location on a drink log unless the
   user picked a place for that entry.

### Correctness
8. **Sync entry events, never counts.** Every log entry gets a client-generated
   UUID; a removal writes a tombstone on that UUID. Three sources write to the
   same day (widget offline, app, bot) — a counter will corrupt silently.
9. **The widget never touches the network.** It writes to shared storage only
   (App Group / DataStore); the app drains the outbox. This keeps API keys out of
   the widget extension.
10. **"Today" is the user's today.** Every summary, reminder, goal, and widget
    color state resolves against `users.timezone`, never the server's.
11. **A parse is a proposal until it's plausible.** Claude's structured output is
    schema-validated *and* range-checked before it becomes a log row. Implausible
    parses ask the user rather than guess.
12. **Nutrition comes from the seed catalog, not live API calls.** Every value
    carries a `source`. An AI-generated nutrition number entering the catalog as
    fact is a critical bug. Caffeine is hand-maintained — USDA doesn't tag it
    consistently.

### Widget
13. **Tap is the only input.** The OS reserves long-press, swipe, and gives no
    way to debounce a double-tap. Single tap = +1; tap again within the undo
    window = remove that entry. Don't re-attempt gestures.
14. **Never poll for widget updates.** iOS: schedule timeline entries only at
    state-change moments. Android: `updatePeriodMillis = 0`, WorkManager plus one
    exact alarm for the bedtime transition. Periodic refresh is the single
    biggest battery mistake available here.
15. **The undo countdown differs by platform on purpose.** iOS uses
    `ProgressView(timerInterval:)`, which self-animates with zero timeline
    entries. Android shows a static undo state that expires silently — it has no
    self-animating primitive, and a per-second redraw isn't worth the battery.
16. **Haptics are Android-only.** iOS interactive widgets have no haptic API.
    Short/light on +, longer/heavier on −.
17. **Color is never the only signal.** Pair every color state with fill level
    and a glyph. Green always means good — a goal drink greens at target, a
    limiter greens while under cap and reds immediately when exceeded.

### Product
18. **The bot does not choose a place for the user.** Nearby Search returns a
    choice list; Google Maps does the navigating. No ranking or recommendation.
19. **State facts, don't lecture.** A limiter going red reports a number. Whether
    moderation nudges exist at all is an open question in `REQUIREMENTS.md` —
    don't decide it in code.
20. **Explain the undo window.** It's a hidden interaction, so it must appear as
    a first-launch tip *and* permanently in Settings with the window length shown.

## Data retention
- `logs` — kept indefinitely (it's the product); removals are tombstones
- Raw message text and photos — never persisted
- `user_health.weight_kg` — until the user deletes it; deletion is immediate
- `user_age_gate` — boolean + country only, never a DOB
- `last_known_location` — overwritten, never appended; user can clear it

## Scope
The bot is no longer "today only" — goals, limiters, and widget states all need
real history, so history is a first-class feature across all three surfaces. What
*is* still scoped out of the bots: charts, favorites management, alcohol, and
body weight. Those are app-only.

## Agents
See `AGENTS.md` in this directory. Use `hydration-*` agents only — the
daemon-class agents in the root `AGENTS.md` do not apply here.
