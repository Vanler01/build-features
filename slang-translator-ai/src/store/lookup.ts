/**
 * Reading the store: term or alias in, full `Term` with all its senses out.
 *
 * A miss returns `undefined` rather than throwing — a term genuinely not
 * being in the store yet is the expected, common case that triggers the
 * Claude fallback (REQUIREMENTS §1), not an error.
 */

import type { Store } from './db.js';
import type { ContentFlag, Register, Sense, Source, Term } from './types.js';
import { normalise } from './types.js';

interface TermRow {
  readonly id: number;
  readonly term: string;
  readonly register: Register;
  readonly source: Source;
  readonly verified: number;
}

interface SenseRow {
  readonly definition: string;
  readonly example: string | null;
  readonly confidence: Sense['confidence'];
  readonly content_flags: string;
}

interface AliasRow {
  readonly variant: string;
}

/** A `Term` as read from the store, with the row id callers need to write back. */
export interface StoredTerm extends Term {
  readonly id: number;
}

function sensesFor(db: Store, termId: number): Sense[] {
  const rows = db
    .prepare(
      `SELECT definition, example, confidence, content_flags
       FROM senses WHERE term_id = ? ORDER BY id`,
    )
    .all(termId) as SenseRow[];
  return rows.map((r) => ({
    definition: r.definition,
    confidence: r.confidence,
    contentFlags: JSON.parse(r.content_flags) as ContentFlag[],
    ...(r.example === null ? {} : { example: r.example }),
  }));
}

function aliasesFor(db: Store, termId: number): string[] {
  const rows = db
    .prepare('SELECT variant FROM aliases WHERE term_id = ?')
    .all(termId) as AliasRow[];
  return rows.map((r) => r.variant);
}

function toStoredTerm(db: Store, row: TermRow): StoredTerm {
  return {
    id: row.id,
    term: row.term,
    aliases: aliasesFor(db, row.id),
    register: row.register,
    senses: sensesFor(db, row.id),
    source: row.source,
    verified: row.verified === 1,
  };
}

/** Look up by term or alias, normalised. `undefined` on a genuine miss. */
export function findTerm(db: Store, raw: string): StoredTerm | undefined {
  const key = normalise(raw);
  if (key === '') return undefined;

  const direct = db.prepare('SELECT * FROM terms WHERE normalised = ?').get(key) as
    | TermRow
    | undefined;
  if (direct !== undefined) return toStoredTerm(db, direct);

  const viaAlias = db
    .prepare(
      `SELECT terms.* FROM terms
       JOIN aliases ON aliases.term_id = terms.id
       WHERE aliases.normalised = ?`,
    )
    .get(key) as TermRow | undefined;
  return viaAlias === undefined ? undefined : toStoredTerm(db, viaAlias);
}

/** Record that a term was looked up. Term + timestamp only — CLAUDE.md rule 19. */
export function recordLookup(db: Store, termId: number, foundLocally: boolean): void {
  db.prepare(
    'INSERT INTO lookups (term_id, looked_up_at, found_locally) VALUES (?, ?, ?)',
  ).run(termId, new Date().toISOString(), foundLocally ? 1 : 0);
}
