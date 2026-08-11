/**
 * The review queue and the verification flow — REQUIREMENTS §11 Phase 2.
 *
 * This module is the *only* place `verified` is ever set to 1, and it cannot
 * do it without a reviewer's name (CLAUDE.md rule 2). Nothing in the bot path
 * imports it. That separation is the point: promotion is a human action, so it
 * lives behind a CLI a human runs, not behind a code path a message can reach.
 */

import type { Store } from '../store/db.js';
import { hasDecayed } from '../store/decay.js';
import { findTerm, type StoredTerm } from '../store/lookup.js';
import { normalise } from '../store/types.js';

/** Why something is sitting in the queue. Mirrors the schema's CHECK. */
export type ReviewReason = 'unverified' | 'decayed' | 'reported';

/** One open item, with enough context to act on it without a second query. */
export interface PendingItem {
  readonly id: number;
  readonly termId: number;
  readonly term: string;
  readonly reason: ReviewReason;
  readonly note: string | undefined;
  readonly queuedAt: string;
  /** How often the term has been asked for — what the queue is ordered by. */
  readonly lookupCount: number;
}

interface PendingRow {
  readonly id: number;
  readonly term_id: number;
  readonly term: string;
  readonly reason: ReviewReason;
  readonly note: string | null;
  readonly queued_at: string;
  readonly lookup_count: number;
}

interface SenseAgeRow {
  readonly term_id: number;
  readonly last_seen: string;
}

interface CountRow {
  readonly n: number;
}

/**
 * Open items, most worth a human's time first.
 *
 * `reported` still sorts ahead of everything — a user saying an answer is
 * wrong is a stronger signal than an entry merely never having been read, and
 * it is the cheapest to act on. Within a reason, the tiebreak is now **how
 * often the term has been looked up** rather than how long it has sat in the
 * queue (REQUIREMENTS §11, "most-looked-up prioritisation").
 *
 * Queue order by age reviews whatever was seeded first, which is alphabetical
 * accident. Order by lookups reviews the words people are actually asking
 * about, so the entries that get served most are the ones a human has checked.
 * Age remains the final tiebreak so an unasked-for term still surfaces
 * eventually rather than never.
 */
export function pending(db: Store, limit = 50): PendingItem[] {
  const rows = db
    .prepare(
      `SELECT rq.id, rq.term_id, t.term, rq.reason, rq.note, rq.queued_at,
              (SELECT COUNT(*) FROM lookups l WHERE l.term_id = rq.term_id) AS lookup_count
         FROM review_queue rq
         JOIN terms t ON t.id = rq.term_id
        WHERE rq.resolved_at IS NULL
        ORDER BY CASE rq.reason WHEN 'reported' THEN 0 WHEN 'decayed' THEN 1 ELSE 2 END,
                 lookup_count DESC,
                 rq.queued_at
        LIMIT ?`,
    )
    .all(limit) as PendingRow[];

  return rows.map((r) => ({
    id: r.id,
    termId: r.term_id,
    term: r.term,
    reason: r.reason,
    note: r.note ?? undefined,
    queuedAt: r.queued_at,
    lookupCount: r.lookup_count,
  }));
}

/** A term and how often it has been asked for, most-asked first. */
export interface TermDemand {
  readonly term: string;
  readonly lookups: number;
  readonly verified: boolean;
}

interface DemandRow {
  readonly term: string;
  readonly lookups: number;
  readonly verified: number;
}

/**
 * What people actually ask about, whether or not it is queued.
 *
 * The queue answers "what needs looking at"; this answers "what is this store
 * for". An unverified term at the top of this list is the single highest-value
 * review in the whole database.
 */
export function mostLookedUp(db: Store, limit = 20): TermDemand[] {
  const rows = db
    .prepare(
      `SELECT t.term, t.verified,
              (SELECT COUNT(*) FROM lookups l WHERE l.term_id = t.id) AS lookups
         FROM terms t
        WHERE lookups > 0
        ORDER BY lookups DESC, t.term
        LIMIT ?`,
    )
    .all(limit) as DemandRow[];

  return rows.map((r) => ({ term: r.term, lookups: r.lookups, verified: r.verified === 1 }));
}

/**
 * Record a spelling that should resolve to an existing term.
 *
 * The counterpart to `variantsOf`: mechanical variants are resolved on the
 * fly and never written down, so anything irregular — "finna" for "fixing
 * to", an emoji, a deliberate misspelling — needs a person to say so once.
 */
export function addAlias(db: Store, term: string, variant: string): ReviewOutcome {
  const trimmed = variant.trim();
  if (trimmed === '') throw new Error('addAlias: the variant cannot be empty');

  const stored = findTerm(db, term);
  if (stored === undefined) throw new Error(`addAlias: no term matching "${term}"`);

  const existing = findTerm(db, trimmed);
  if (existing !== undefined && existing.id !== stored.id) {
    // Silently repointing a word that already means something else is how a
    // store starts giving confidently wrong answers.
    throw new Error(`addAlias: "${trimmed}" already resolves to "${existing.term}"`);
  }

  db.prepare(
    'INSERT OR IGNORE INTO aliases (term_id, variant, normalised) VALUES (?, ?, ?)',
  ).run(stored.id, trimmed, normalise(trimmed));

  return { term: stored.term, itemsResolved: 0 };
}

/** How many open items there are, by reason. */
export function queueStats(db: Store): Record<ReviewReason, number> {
  const rows = db
    .prepare(
      `SELECT reason, COUNT(*) AS n FROM review_queue
        WHERE resolved_at IS NULL GROUP BY reason`,
    )
    .all() as { reason: ReviewReason; n: number }[];

  const stats: Record<ReviewReason, number> = { unverified: 0, decayed: 0, reported: 0 };
  for (const r of rows) stats[r.reason] = r.n;
  return stats;
}

/** Look up a term for review by name or alias. */
export function forReview(db: Store, term: string): StoredTerm | undefined {
  return findTerm(db, term);
}

function resolveOpenItems(db: Store, termId: number, at: string): number {
  const info = db
    .prepare('UPDATE review_queue SET resolved_at = ? WHERE term_id = ? AND resolved_at IS NULL')
    .run(at, termId);
  return info.changes;
}

/** What a verify or reject actually did, so the CLI can report it honestly. */
export interface ReviewOutcome {
  readonly term: string;
  readonly itemsResolved: number;
}

/**
 * Promote a term to verified, naming the person who confirmed it.
 *
 * Refuses an empty reviewer name rather than writing a blank one: the schema
 * permits a verified claude-sourced row only when `verified_by` is non-null,
 * and a whitespace name would satisfy the letter of that while defeating it.
 *
 * Verification also resets the decay clock — a person has just read the entry,
 * which is exactly the "touch" decay measures the absence of.
 */
export function verifyTerm(db: Store, term: string, reviewer: string): ReviewOutcome {
  const reviewerName = reviewer.trim();
  if (reviewerName === '') {
    throw new Error('verifyTerm: a reviewer name is required — promotion is a human action');
  }

  const stored = findTerm(db, term);
  if (stored === undefined) {
    throw new Error(`verifyTerm: no term matching "${term}"`);
  }

  const now = new Date().toISOString();
  const resolved = db.transaction((): number => {
    db.prepare(
      `UPDATE terms SET verified = 1, verified_by = ?, verified_at = ?, last_seen = ?
        WHERE id = ?`,
    ).run(reviewerName, now, now, stored.id);
    db.prepare('UPDATE senses SET last_seen = ? WHERE term_id = ?').run(now, stored.id);
    return resolveOpenItems(db, stored.id, now);
  })();

  return { term: stored.term, itemsResolved: resolved };
}

/**
 * Close a term's open queue items without promoting it.
 *
 * The entry stays unverified and stays servable — an unverified answer is
 * still the cache doing its job (REQUIREMENTS §1). This says "a human looked
 * and did not confirm it", which is different from "nobody has looked yet",
 * and clearing it stops the same item blocking the queue forever.
 */
export function rejectTerm(db: Store, term: string): ReviewOutcome {
  const stored = findTerm(db, term);
  if (stored === undefined) {
    throw new Error(`rejectTerm: no term matching "${term}"`);
  }
  const resolved = resolveOpenItems(db, stored.id, new Date().toISOString());
  return { term: stored.term, itemsResolved: resolved };
}

/**
 * Demote a previously verified term back to unverified and re-queue it.
 *
 * Needed because verification is not permanent: a sense that shifted after
 * being confirmed is exactly the case rule 4 warns about, and without this the
 * only way to correct a wrong promotion would be raw SQL.
 */
export function unverifyTerm(
  db: Store,
  term: string,
  reason: ReviewReason = 'reported',
): ReviewOutcome {
  const stored = findTerm(db, term);
  if (stored === undefined) {
    throw new Error(`unverifyTerm: no term matching "${term}"`);
  }

  const now = new Date().toISOString();
  db.transaction(() => {
    db.prepare(
      'UPDATE terms SET verified = 0, verified_by = NULL, verified_at = NULL WHERE id = ?',
    ).run(stored.id);
    enqueue(db, stored.id, reason, 'previously verified, sent back for another look', now);
  })();

  return { term: stored.term, itemsResolved: 0 };
}

/**
 * Queue a term unless an identical open item already exists.
 *
 * The dedupe is what makes the sweeps safe to run on a cron or by hand twice
 * in a row — without it every run would pile another copy of the same decayed
 * term onto the queue until the queue was useless.
 */
export function enqueue(
  db: Store,
  termId: number,
  reason: ReviewReason,
  note: string | undefined,
  at: string,
): boolean {
  const existing = db
    .prepare(
      'SELECT 1 FROM review_queue WHERE term_id = ? AND reason = ? AND resolved_at IS NULL',
    )
    .get(termId, reason);
  if (existing !== undefined) return false;

  db.prepare(
    'INSERT INTO review_queue (term_id, reason, note, queued_at) VALUES (?, ?, ?, ?)',
  ).run(termId, reason, note ?? null, at);
  return true;
}

/**
 * Queue every term whose senses have gone stale — REQUIREMENTS §4's first
 * signal, "an entry nobody has looked up in months".
 *
 * Verified terms are swept too. A human's confirmation ages exactly like
 * anything else here; slang shifting under a checked definition is the whole
 * reason rule 4 exists.
 */
export function sweepDecayed(db: Store, now: Date = new Date()): number {
  const rows = db
    .prepare('SELECT DISTINCT term_id, last_seen FROM senses')
    .all() as SenseAgeRow[];

  const at = now.toISOString();
  let queued = 0;
  db.transaction(() => {
    for (const row of rows) {
      if (!hasDecayed(row.last_seen, now)) continue;
      if (enqueue(db, row.term_id, 'decayed', 'confidence decayed with age', at)) queued += 1;
    }
  })();
  return queued;
}

/**
 * Queue terms that are looked up often but answered with low confidence —
 * REQUIREMENTS §4's second and, it says, strongest signal.
 *
 * This is the one that catches what `sweepDecayed` structurally cannot: a
 * popular term never looks stale, because every lookup refreshes `last_seen`.
 */
export function sweepLowConfidence(db: Store, minLookups = 5, now: Date = new Date()): number {
  const rows = db
    .prepare(
      `SELECT s.term_id, s.last_seen FROM senses s
        WHERE s.confidence = 'low'
          AND (SELECT COUNT(*) FROM lookups l WHERE l.term_id = s.term_id) >= ?
        GROUP BY s.term_id`,
    )
    .all(minLookups) as SenseAgeRow[];

  const at = now.toISOString();
  let queued = 0;
  db.transaction(() => {
    for (const row of rows) {
      const note = 'looked up often but answered with low confidence';
      if (enqueue(db, row.term_id, 'unverified', note, at)) queued += 1;
    }
  })();
  return queued;
}

/** How many terms are still unverified, for the CLI's summary line. */
export function unverifiedCount(db: Store): number {
  const row = db.prepare('SELECT COUNT(*) AS n FROM terms WHERE verified = 0').get() as CountRow;
  return row.n;
}
