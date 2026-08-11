/**
 * Reading the store: term or alias in, full `Term` with all its senses out.
 *
 * A miss returns `undefined` rather than throwing — a term genuinely not
 * being in the store yet is the expected, common case that triggers the
 * Claude fallback (REQUIREMENTS §1), not an error.
 */

import type { Store } from './db.js';
import { decayConfidence } from './decay.js';
import type { ContentFlag, Confidence, Register, Sense, Source, Term } from './types.js';
import { normalise } from './types.js';
import { collapse, variantsOf } from './variants.js';

interface TermRow {
  readonly id: number;
  readonly term: string;
  readonly register: Register;
  readonly source: Source;
  readonly verified: number;
  readonly verified_by: string | null;
  readonly verified_at: string | null;
}

interface SenseRow {
  readonly id: number;
  readonly definition: string;
  readonly example: string | null;
  readonly confidence: Sense['confidence'];
  readonly content_flags: string;
  readonly region: string | null;
  readonly last_seen: string;
}

interface AliasRow {
  readonly variant: string;
}

/**
 * A sense as read from the store. `confidence` is what was written down;
 * `effectiveConfidence` is that value aged by how long the entry has sat
 * untouched (CLAUDE.md rule 4). Readers should be shown the effective one —
 * reviewers need to see both.
 */
export interface StoredSense extends Sense {
  readonly id: number;
  readonly lastSeen: string;
  readonly effectiveConfidence: Confidence;
}

/** A `Term` as read from the store, with the row id callers need to write back. */
export interface StoredTerm extends Term {
  readonly id: number;
  readonly senses: readonly StoredSense[];
  /** Who confirmed this entry, if anyone has. Never set by automation. */
  readonly verifiedBy?: string;
  readonly verifiedAt?: string;
}

function sensesFor(db: Store, termId: number, now: Date): StoredSense[] {
  const rows = db
    .prepare(
      `SELECT id, definition, example, confidence, content_flags, region, last_seen
       FROM senses WHERE term_id = ? ORDER BY id`,
    )
    .all(termId) as SenseRow[];
  return rows.map((r) => ({
    id: r.id,
    definition: r.definition,
    confidence: r.confidence,
    effectiveConfidence: decayConfidence(r.confidence, r.last_seen, now),
    lastSeen: r.last_seen,
    contentFlags: JSON.parse(r.content_flags) as ContentFlag[],
    ...(r.example === null ? {} : { example: r.example }),
    ...(r.region === null ? {} : { region: r.region }),
  }));
}

function aliasesFor(db: Store, termId: number): string[] {
  const rows = db
    .prepare('SELECT variant FROM aliases WHERE term_id = ?')
    .all(termId) as AliasRow[];
  return rows.map((r) => r.variant);
}

function toStoredTerm(db: Store, row: TermRow, now: Date): StoredTerm {
  return {
    id: row.id,
    term: row.term,
    aliases: aliasesFor(db, row.id),
    register: row.register,
    senses: sensesFor(db, row.id, now),
    source: row.source,
    verified: row.verified === 1,
    ...(row.verified_by === null ? {} : { verifiedBy: row.verified_by }),
    ...(row.verified_at === null ? {} : { verifiedAt: row.verified_at }),
  };
}

/**
 * Look up by term or alias, normalised. `undefined` on a genuine miss.
 *
 * `now` is injectable so decay is testable without waiting 90 days.
 */
export function findTerm(db: Store, raw: string, now: Date = new Date()): StoredTerm | undefined {
  const key = normalise(raw);
  if (key === '') return undefined;

  const exact = byKey(db, key);
  if (exact !== undefined) return toStoredTerm(db, exact, now);

  // Variants last, and only after both exact and curated-alias lookups have
  // missed. They widen what resolves to an *existing* entry; they never
  // create one, so a wrong guess simply misses and falls through to Claude.
  for (const candidate of variantsOf(raw)) {
    const row = byKey(db, candidate);
    if (row !== undefined) return toStoredTerm(db, row, now);
  }

  // Separator-insensitive match, which has to be done against the stored side
  // as well as the query. Generating "nocap" from "no cap" is easy; the
  // reverse is impossible, because nothing says where the space goes. So both
  // sides are collapsed and compared.
  const viaCollapsed = byCollapsedKey(db, collapse(key));
  return viaCollapsed === undefined ? undefined : toStoredTerm(db, viaCollapsed, now);
}

/** Match ignoring spaces and hyphens on both sides — "nocap" ⇄ "no cap". */
function byCollapsedKey(db: Store, collapsedKey: string): TermRow | undefined {
  // An unindexed scan, which is fine at this size and honest about it: the
  // store holds tens of terms, and this only runs after every indexed lookup
  // has already missed.
  const direct = db
    .prepare(`SELECT * FROM terms WHERE REPLACE(REPLACE(normalised, ' ', ''), '-', '') = ?`)
    .get(collapsedKey) as TermRow | undefined;
  if (direct !== undefined) return direct;

  return db
    .prepare(
      `SELECT terms.* FROM terms
       JOIN aliases ON aliases.term_id = terms.id
       WHERE REPLACE(REPLACE(aliases.normalised, ' ', ''), '-', '') = ?`,
    )
    .get(collapsedKey) as TermRow | undefined;
}

/** Exact match on a normalised key, by term then by curated alias. */
function byKey(db: Store, key: string): TermRow | undefined {
  const direct = db.prepare('SELECT * FROM terms WHERE normalised = ?').get(key) as
    | TermRow
    | undefined;
  if (direct !== undefined) return direct;

  return db
    .prepare(
      `SELECT terms.* FROM terms
       JOIN aliases ON aliases.term_id = terms.id
       WHERE aliases.normalised = ?`,
    )
    .get(key) as TermRow | undefined;
}

/**
 * Record that a term was looked up, and refresh its `last_seen`.
 *
 * Still term + timestamp only — CLAUDE.md rule 19; no user id, message body,
 * page or URL touches this table.
 *
 * The `last_seen` bump is what makes decay mean what REQUIREMENTS §4 says it
 * means: "an entry nobody has looked up in months". Note the limit of that
 * model — being looked up is not the same as being *confirmed*, so a popular
 * term stays fresh-looking however wrong it is. That gap is covered separately
 * by the low-confidence sweep in the review module, which is §4's other signal.
 */
export function recordLookup(db: Store, termId: number, foundLocally: boolean): void {
  const now = new Date().toISOString();
  db.transaction(() => {
    db.prepare(
      'INSERT INTO lookups (term_id, looked_up_at, found_locally) VALUES (?, ?, ?)',
    ).run(termId, now, foundLocally ? 1 : 0);
    db.prepare('UPDATE terms SET last_seen = ? WHERE id = ?').run(now, termId);
    db.prepare('UPDATE senses SET last_seen = ? WHERE term_id = ?').run(now, termId);
  })();
}
