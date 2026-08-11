/**
 * What filling the store costs, and the ceiling on it.
 *
 * Store-first is the whole design (CLAUDE.md rule 5), and until now nothing
 * measured whether it worked. `lookups.found_locally` was written on every
 * lookup from the first migration and never once read, so the cache hit rate —
 * the single number that says whether this product is doing its job — sat in
 * the database unqueried.
 *
 * The other half is the ceiling. Every miss calls Claude, a sentence costs one
 * detect plus one define per candidate, and a right-click in the extension is
 * enough to start. A runaway loop against a local backend spends real money
 * with nobody watching. So calls are counted, and when the day's count reaches
 * the limit the bot degrades to serving what it already knows rather than
 * failing or spending — for a cache, answering from cache is the honest
 * fallback.
 *
 * What is recorded is only ever model, purpose and time. Never the term, the
 * prompt or the reply: rule 19 is about `lookups`, but a cost table is no
 * place to start keeping a second copy of what people asked about.
 */

import type { Store } from './db.js';

/** Somewhere to record that a call happened. Implemented over the store below. */
export interface CallLog {
  record(model: string, purpose: string): void;
}

interface CountRow {
  readonly n: number;
}

/** A `CallLog` that writes to the store. */
export function callLog(db: Store): CallLog {
  return {
    record(model: string, purpose: string): void {
      db.prepare('INSERT INTO claude_calls (model, purpose, called_at) VALUES (?, ?, ?)').run(
        model,
        purpose,
        new Date().toISOString(),
      );
    },
  };
}

/**
 * Start of `now`'s UTC day, as an ISO string.
 *
 * UTC rather than local time because that is what the column holds, and a cap
 * that resets at a predictable instant is easier to reason about than one that
 * moves with the machine's timezone. It means the reset is not at your
 * midnight; for a personal spend limit that costs nothing.
 */
function startOfUtcDay(now: Date): string {
  return `${now.toISOString().slice(0, 10)}T00:00:00.000Z`;
}

/** How many Claude calls have been made since UTC midnight. */
export function callsToday(db: Store, now: Date = new Date()): number {
  const row = db
    .prepare('SELECT COUNT(*) AS n FROM claude_calls WHERE called_at >= ?')
    .get(startOfUtcDay(now)) as CountRow;
  return row.n;
}

/**
 * Whether the day's ceiling has been reached.
 *
 * `undefined` means no limit was configured, which is not the same as a limit
 * of zero and must not quietly become one.
 */
export function overDailyLimit(db: Store, limit: number | undefined, now?: Date): boolean {
  if (limit === undefined) return false;
  return callsToday(db, now) >= limit;
}

/** Cache performance: how many lookups the store answered without Claude. */
export interface HitRate {
  readonly hits: number;
  readonly misses: number;
  readonly total: number;
}

export function hitRate(db: Store): HitRate {
  const rows = db
    .prepare('SELECT found_locally, COUNT(*) AS n FROM lookups GROUP BY found_locally')
    .all() as { found_locally: number; n: number }[];

  let hits = 0;
  let misses = 0;
  for (const row of rows) {
    if (row.found_locally === 1) hits += row.n;
    else misses += row.n;
  }
  return { hits, misses, total: hits + misses };
}

/** Calls made today, broken down by what they were for. */
export function callsByPurpose(db: Store, now: Date = new Date()): Record<string, number> {
  const rows = db
    .prepare(
      `SELECT purpose, COUNT(*) AS n FROM claude_calls
        WHERE called_at >= ? GROUP BY purpose ORDER BY n DESC`,
    )
    .all(startOfUtcDay(now)) as { purpose: string; n: number }[];

  const out: Record<string, number> = {};
  for (const row of rows) out[row.purpose] = row.n;
  return out;
}
