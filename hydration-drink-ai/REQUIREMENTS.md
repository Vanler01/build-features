# hydration-drink-ai — Requirements

## Vision
An AI that reminds you to drink water and logs whatever you actually drink —
typed in ("2 hot coffees this morning, an iced latte tonight"), sent as a photo,
or tapped on a home-screen widget. Three surfaces, one backend:

- **Bot** — Telegram and LINE. Casual, no install. Conversational logging + reminders.
- **App** — cross-platform mobile. Full history, goals, limiters, nutrition.
- **Widget** — home-screen tap logging. In practice the surface used most.

Users can start on a bot and carry their data into the app.

> Status: spec. No code yet. Approved implementation plan:
> `~/.claude/plans/gentle-weaving-candy.md`

---

## 0. Platform reality (verified 2026-08-08 — do not re-litigate)

Several original assumptions did not survive contact with platform rules.

| Finding | Consequence |
|---|---|
| Meta deprecated recurring/marketing messages in most countries (2026); outside the 24h window only One-Time Notification, which is one message | **Messenger cannot send reminders — excluded** |
| WeChat's overseas path needs a registered business entity + $99 verification, yielding a Service Account whose template messages are transactional-only | **WeChat excluded** |
| LINE Thailand free plan = 300 push messages/month (Basic ฿1,280/mo = 15,000) | Reminders on LINE must be budgeted and opt-in |
| LINE *reply* messages (within the reply token window) are free | Conversational logging is free; only unsolicited pushes meter |
| WidgetKit supports only `Button`/`Toggle` + App Intents — no gesture recognizers | No swipe, long-press, or true double-tap on iOS widgets |
| Android `RemoteViews` binds click `PendingIntent`s only | Same on Android |
| Long-press belongs to the OS (iOS edit menu / Android launcher move-resize) | Cannot be reclaimed |
| Haptics do not work in iOS interactive widgets | Widget haptics are **Android-only** |
| iOS widget families are fixed (small/medium/large; XL is iPad-only) | User-resizable widgets are **Android-only** |
| Android `updatePeriodMillis` minimum is 30 min and wakes the device | Set it to 0; use WorkManager + one exact alarm instead |

**Net: tap is the only widget input on both platforms, and only Telegram and
LINE can push a recurring reminder.**

---

## 1. Bot

**Platforms:** Telegram (free, unlimited, instant setup) and LINE (where Thai
users are). Both sit behind one `MessagingPort` adapter, so Messenger/WeChat can
drop in later if their rules change.

**Features:**
- Scheduled reminders — user-configurable interval and active window (e.g. 08:00–22:00), **toggleable on/off**
- Log by text or photo; Claude parses into structured entries
- Daily summary: "Today: 3 coffees, 1 soda, 4 waters"
- Nearby cafes/bars on location share — a choice list with Google Maps deep links
- `/link` — hand off to the app (§4)

**LINE push budget:** reminders are opt-in and default conservative. A
`push_budget` counter tracks monthly sends per user with a hard stop, so the
300/month ceiling is visible before it's hit rather than after.

---

## 2. App

**Platform:** Flutter for app screens; widgets are native modules (SwiftUI
WidgetKit + Kotlin Glance) because no cross-platform framework builds widgets.

**Features:**
- Everything the bots do, plus:
- Full history — daily, weekly, yearly, with charts
- Favorite drinks — one-tap logging of usual drinks
- **Day list with full entry editing** — the place to correct a drink logged hours ago
- Nutrition per drink (caffeine, sugar, calories) from the seed catalog
- Push notifications for reminders (more reliable than a bot on mobile)
- Goals and limiters (§5)
- Optional body weight → hydration suggestion (§6)
- Alcohol logging, age-gated (§7)
- Nearby places as a full screen: map + list, filterable, "Directions" hands off to Google Maps

**Onboarding:** first launch shows a tip explaining the widget's **tap-again-
within-4-seconds** undo. The same explanation lives permanently in Settings with
an indicator showing the window length, so a user who skipped onboarding can
still find it.

---

## 3. Widget

The primary logging surface. Tap a glass, a drink is logged.

**Interaction — tap only** (the OS reserves everything else):
- **Single tap = +1.** Glass fills. Short light haptic (Android only).
- **Tap the same glass again within ~4s = remove that entry.** The glass is
  pushed off the edge of the widget. Longer, heavier haptic (Android only).
- Older corrections happen in the app's day list, not on the widget.

A true double-tap cannot be detected — a widget `Button` fires its intent on
every tap with variable latency, so fast logging of two drinks would randomly
register as a removal. The 4-second window is the reliable form of the same idea,
and it is semantically *undo*, which is what a mis-tap needs.

**The undo countdown differs by platform, deliberately:**
- **iOS** — `ProgressView(timerInterval:countsDown:)` self-animates inside the
  widget process with **no timeline entries**, so the ring costs nothing. The
  naive alternative (one timeline entry per second) would exhaust the daily
  refresh budget after ~15 taps and freeze the widget.
- **Android** — `RemoteViews` has no self-animating progress primitive. The
  widget shows a **static highlighted undo state** that expires silently. A
  per-second redraw would be a real battery cost for a cosmetic gain.

**Configuration** — one widget holds N drinks the user picks
(`AppIntentConfiguration` on iOS via Edit Widget; a configuration Activity on
Android). "3 water + 1 coffee + 1 tea" can be three single-drink widgets or one
combined widget, user's choice.

| Size | Drinks | Notes |
|---|---|---|
| small / 2x2 | 1 | count on the left |
| medium / 4x2 | 3–4 | |
| large / 4x4 | up to 6 + day progress | |
| Android, any | computed from cell count | true resizing; **iOS cannot resize** |

**Color states** (per drink, per day) — green always means good:

| State | Goal drink (water) | Limiter drink (beer, coffee) |
|---|---|---|
| monotone | nothing logged yet | nothing logged yet |
| green | goal met | under cap |
| yellow | behind pace near bedtime | near cap |
| red | unmet at bedtime−10min / day end | **over cap, immediately** |

Color is always paired with fill level and a state glyph — never color alone,
which fails colorblind users.

**Refresh:** timeline entries only at state-change moments (midnight rollover,
bedtime−10min, a few pace checkpoints) — roughly 5–10/day against an iOS budget
of ~40–70. Never poll.

---

## 4. Bot → app handoff

A bot user must be able to continue in the app without losing their data.

1. **Deep link (primary)** — `/link` returns a tappable Universal Link / App
   Link. Opens the app if installed, the store if not. Zero typing, and it works
   when the bot and app are on the **same device** — the common case.
2. **6-character code (fallback)** — 10-minute TTL, single-use, rate-limited, for
   when the link fails or the app is on a different device.
3. **QR (last)** — only for the genuine two-device case. QR is useless on a
   single device, since you cannot scan your own screen.

Tokens are 32 random bytes, **stored hashed**, single-use, bound to the issuing
platform identity. Redeeming attaches that identity to the app account.

**Identity model.** One person, many identities:

```sql
users(id, timezone, bedtime, created_at)
platform_identities(user_id, platform, platform_user_id, linked_at)
  UNIQUE(platform, platform_user_id)
```

A single `users.platform` column cannot represent someone on both Telegram and
the app, so this is a Phase 1 prerequisite, not a later refactor.

---

## 5. Goals and limiters

- **Goal** — a target to reach (water, or any drink the user considers healthy)
- **Limiter** — a cap not to exceed (beer, coffee)

Both are per drink category, per day, user-set, and optional. They drive the
widget color states in §3. A limiter turning red is informational — the app
states the fact, it does not lecture.

```sql
user_goals(user_id, drink_category, kind ENUM('goal','limit'), target, period, active)
```

---

## 6. Body weight and hydration suggestion (opt-in)

The app can suggest a daily water target derived from body weight. **Entirely the
user's choice** — the feature is off until they opt in, and the app is fully
usable without it.

- Weight is **health data**: opt-in, editable, deletable, and never required
- Never sent to a bot platform, never included in a Claude prompt, never logged
- Deleting weight reverts the target to the user's manual value or the default
- The suggestion is a starting point, not a medical recommendation, and is
  labeled as such — no health claims

---

## 7. Alcohol (app only, age-gated)

Alcohol logging exists **in the app only** — never in the bots, which have no
practical way to gate it.

- Unlocking alcohol requires **email login** and a self-declared age
- The legal threshold varies by country — Thailand 20, much of Europe 18,
  the US 21, and some countries permit beer/wine earlier. The gate resolves the
  threshold from the user's stated country rather than assuming 18 or 20
- **Self-declared, not verified.** No ID, no document upload, no biometric check.
  The app must never claim verification it does not perform
- Store only `alcohol_unlocked` (boolean) and the country used — **not the date
  of birth**. Once the check passes, the underlying age is not worth keeping
- Users below the threshold keep the entire rest of the app; only alcohol is hidden
- Logging only. Whether moderation nudges appear at all is still open (§10)

---

## 8. Standard drink library

Two tiers:

- **Standard items** — a committed seed catalog of ~50–80 drinks with nutrition:
  coffee variants, tea, matcha, soda, beer, wine, other common alcohol, water
- **Custom items** — user-added specialty drinks ("espresso tonic"), saved to
  their personal list with rough nutrition

**Sourcing.** A static committed dataset, not live API calls per message —
faster, offline-capable, and immune to rate limits. Built by
`hydration-drink-sourcer` from:
- **Open Food Facts** — free, no key, packaged/branded drinks (soda, bottled tea, beer, wine)
- **USDA FoodData Central** — free with a data.gov key, authoritative for generic drinks
- **A manual caffeine reference** — USDA does not consistently tag caffeine, so
  coffee/tea/soda caffeine values are hand-maintained against published sources

Every value carries a `source` field. AI-generated nutrition numbers must never
enter the catalog as fact. Live API calls are reserved for future barcode lookups.

---

## 9. Data model

```sql
users(id, timezone, bedtime, created_at)
platform_identities(user_id, platform, platform_user_id, linked_at)
link_tokens(token_hash, user_id, platform, expires_at, used_at)
drinks_catalog(id, name, category, subtype, serving_size_ml, calories, sugar_g,
               caffeine_mg, source, is_alcohol)
user_favorites(user_id, drink_id, custom_name, custom_nutrition)
logs(id UUID, user_id, drink_id|custom, quantity, logged_at, source,
     place_id, deleted_at)
user_goals(user_id, drink_category, kind, target, period, active)
user_settings(user_id, reminders_enabled, interval_min, window_start, window_end,
              nearby_enabled, nutrition_replies_enabled, undo_window_sec)
user_health(user_id, weight_kg, weight_updated_at)      -- opt-in, deletable
user_age_gate(user_id, alcohol_unlocked, country, checked_at)  -- no DOB stored
push_budget(user_id, platform, year_month, sent_count)
```

**Sync model — entry events, never counts.** Three sources write to the same day
(widget offline, app, bot server-side), so counters would conflict. Every entry
gets a client-generated UUID; a removal writes a **tombstone** (`deleted_at`) on
that UUID rather than decrementing. The backend upserts idempotently on UUID, so
operations are commutative and order-independent. The widget writes only to
shared storage (iOS App Group, Android DataStore) as an append-only outbox and
**never touches the network**; the app drains it on foreground.

---

## 10. Open questions

- Should alcohol get moderation nudges, or stay purely logging?
- Nearby places: cafes/bars only, or broader (boba, juice bars)? And should
  picking a place auto-log a drink, or stay navigational?
- Hydration suggestion formula — which published basis to cite for the
  weight-derived target?

Sources: [FoodData Central API](https://fdc.nal.usda.gov/api-guide.html),
[Open Food Facts API](https://openfoodfacts.github.io/openfoodfacts-server/api/),
[LINE Messaging API pricing](https://developers.line.biz/en/docs/messaging-api/pricing/),
[Messenger Platform policy](https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy),
[WeChat overseas Official Account registration](https://wechatwiki.com/wechat-resources/wechat-overseas-official-account-registration-fees/),
[WidgetKit interactive widgets](https://developer.apple.com/videos/play/wwdc2023/10028/),
[Android widget update strategies](https://developer.android.com/develop/ui/views/appwidgets/advanced),
[Google Places API (New) pricing](https://www.woosmap.com/blog/google-places-api-pricing)
