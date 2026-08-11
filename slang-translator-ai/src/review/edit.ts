/**
 * Correcting an entry — the half of review that `verify` and `reject` could not do.
 *
 * Until this existed a reviewer could bless an entry or bounce it, and nothing
 * else. A definition Claude got slightly wrong had exactly two fates: promoted
 * with the error in it, or left unverified forever. Fixing the wording meant
 * opening the database by hand. That is a bad enough deal that the honest
 * outcome, faced with 57 unverified entries, is to reject everything imperfect
 * — which throws away the good sense sitting next to the bad one.
 *
 * Three rules hold everywhere in this module:
 *
 * 1. **Editing is not promoting.** Nothing here turns `verified` from 0 to 1.
 *    That is still `verifyTerm`'s job alone, behind a reviewer's name
 *    (CLAUDE.md rule 2). `addTerm` is the one exception and it goes *through*
 *    `verifyTerm` rather than around it.
 * 2. **`source` is never rewritten.** Correcting a claude-sourced definition
 *    leaves it claude-sourced. The field records where the entry came from,
 *    not who touched it last, and relabelling it `manual_seed` on edit would
 *    forge exactly the provenance rule 3 protects.
 * 3. **A name stays attached to verified text.** Editing a verified entry
 *    re-stamps `verified_by` to whoever made the edit, because the previous
 *    reviewer never saw the new wording and their name should not vouch for
 *    it. That is why editing a verified entry needs `--by` and editing an
 *    unverified one does not.
 */

import type { Store } from '../store/db.js';
import { findTerm, type StoredSense, type StoredTerm } from '../store/lookup.js';
import { parseSense } from '../store/seed.js';
import type { Confidence, Register, Sense } from '../store/types.js';
import { insertTerm } from '../store/write.js';
import { verifyTerm } from './queue.js';

/**
 * One field-level change to a sense.
 *
 * `undefined` means "leave this alone" and `null` means "clear it", which are
 * genuinely different instructions — `example: null` removes a usage example,
 * which is the fix for a rule 11 violation, while omitting `example` keeps it.
 */
export interface SenseChange {
  readonly definition?: string;
  readonly example?: string | null;
  /** Unvalidated on the way in: `parseSense` is the gate, in `merge` below. */
  readonly confidence?: string;
  readonly contentFlags?: readonly string[];
  readonly region?: string | null;
}

/** A hand-written sense is the reviewer's own words, so it starts trusted. */
const HAND_WRITTEN_CONFIDENCE: Confidence = 'high';

function locate(db: Store, term: string): StoredTerm {
  const entry = findTerm(db, term);
  if (entry === undefined) throw new Error(`no term matching "${term}"`);
  return entry;
}

/**
 * Senses are numbered as `formatEntry` prints them — 1-based, in stored order.
 * The reviewer is reading that output while typing this command, so the number
 * on screen has to be the number that works.
 */
function senseAt(entry: StoredTerm, senseNumber: number): StoredSense {
  const sense = entry.senses[senseNumber - 1];
  if (sense === undefined) {
    throw new Error(
      `"${entry.term}" has ${entry.senses.length} sense(s); there is no sense ${senseNumber}`,
    );
  }
  return sense;
}

/**
 * Apply a change on top of a stored sense and validate the result as a whole.
 *
 * Validating the *merged* sense rather than the incoming field is what catches
 * the interesting case: flagging an existing sense as a slur while it still
 * carries a usage example is a rule 11 violation that neither half looks like
 * on its own. `parseSense` already refuses that combination, so this reuses it
 * instead of restating the content policy in a second place.
 */
function merge(termName: string, sense: StoredSense, change: SenseChange): Sense {
  const example = change.example === undefined ? sense.example ?? null : change.example;
  const region = change.region === undefined ? sense.region ?? null : change.region;

  return parseSense(termName, {
    definition: change.definition ?? sense.definition,
    confidence: change.confidence ?? sense.confidence,
    content_flags: change.contentFlags ?? sense.contentFlags,
    ...(example === null ? {} : { example }),
    ...(region === null ? {} : { region }),
  });
}

/**
 * Keep the reviewer's name honest on an entry whose text just changed.
 *
 * Only ever runs on a row that is *already* verified: it updates whose name is
 * against the wording, and never promotes anything. An unverified entry stays
 * unverified through every edit, which is why this is a no-op for the 57
 * entries that need the most work.
 */
function restampIfVerified(db: Store, entry: StoredTerm, reviewer: string, at: string): void {
  if (!entry.verified) return;

  const name = reviewer.trim();
  if (name === '') {
    throw new Error(
      `"${entry.term}" is verified — editing it needs your name, because the current one ` +
        `belongs to whoever confirmed the old wording.\n` +
        `  npm run review -- edit ... --by <you>   (note the --)`,
    );
  }
  db.prepare('UPDATE terms SET verified_by = ?, verified_at = ? WHERE id = ?').run(
    name,
    at,
    entry.id,
  );
}

/**
 * Rewrite one field of one sense.
 *
 * `last_seen` moves to now for the same reason `verifyTerm` moves it: a person
 * has just read and rewritten this text, which is precisely the "touch" that
 * decay measures the absence of (CLAUDE.md rule 4). It stays unverified all
 * the same — a fresh timestamp is not a confirmation.
 */
export function editSense(
  db: Store,
  term: string,
  senseNumber: number,
  change: SenseChange,
  reviewer = '',
): StoredTerm {
  const entry = locate(db, term);
  const sense = senseAt(entry, senseNumber);
  const next = merge(entry.term, sense, change);
  const now = new Date().toISOString();

  db.transaction(() => {
    restampIfVerified(db, entry, reviewer, now);
    db.prepare(
      `UPDATE senses
          SET definition = ?, example = ?, confidence = ?, content_flags = ?,
              region = ?, last_seen = ?
        WHERE id = ?`,
    ).run(
      next.definition,
      next.example ?? null,
      next.confidence,
      JSON.stringify(next.contentFlags),
      next.region ?? null,
      now,
      sense.id,
    );
  })();

  return locate(db, entry.term);
}

/**
 * Add a sense to an existing term.
 *
 * The case this exists for is a term whose stored meaning is right as far as
 * it goes but is missing the ordinary-English one — "mid = mediocre" with no
 * "mid-July" sense is how the bot ends up confidently wrong about a plain
 * sentence (REQUIREMENTS §2). A regional meaning is the other one: it belongs
 * in its own row with a `region`, never as a note inside another sense (§13).
 */
export function addSense(
  db: Store,
  term: string,
  definition: string,
  reviewer = '',
): StoredTerm {
  const entry = locate(db, term);
  const sense = parseSense(entry.term, {
    definition,
    confidence: HAND_WRITTEN_CONFIDENCE,
    content_flags: [],
  });
  const now = new Date().toISOString();

  db.transaction(() => {
    restampIfVerified(db, entry, reviewer, now);
    db.prepare(
      `INSERT INTO senses
         (term_id, definition, example, confidence, content_flags, region, first_seen, last_seen)
       VALUES (?, ?, NULL, ?, ?, NULL, ?, ?)`,
    ).run(entry.id, sense.definition, sense.confidence, JSON.stringify([]), now, now);
  })();

  return locate(db, entry.term);
}

/**
 * Remove a sense.
 *
 * Refuses to remove the last one. A term with no senses is not an empty entry,
 * it is a broken one: `formatTermReply` throws on it, so the term would stay
 * in the store answering every lookup with a crash. Deleting the term is a
 * different decision from correcting it, and this command does not pretend to
 * make it.
 */
export function removeSense(
  db: Store,
  term: string,
  senseNumber: number,
  reviewer = '',
): StoredTerm {
  const entry = locate(db, term);
  const sense = senseAt(entry, senseNumber);
  if (entry.senses.length === 1) {
    throw new Error(
      `"${entry.term}" has only this sense left; a term with none would break every ` +
        `lookup of it. Correct the definition instead, or remove the term deliberately.`,
    );
  }

  const now = new Date().toISOString();
  db.transaction(() => {
    restampIfVerified(db, entry, reviewer, now);
    db.prepare('DELETE FROM senses WHERE id = ?').run(sense.id);
  })();

  return locate(db, entry.term);
}

/**
 * Hand-write a new term — the only path that produces `source: 'manual_seed'`.
 *
 * Everything else in the store is `claude`, including all 57 seed entries,
 * because a model wrote them and saying otherwise would be the convenient lie
 * `store/seed.ts` refuses to tell. This is the other case: a person typed the
 * definition, so the provenance is theirs and the reviewer's name goes on it.
 *
 * It creates the term unverified and then calls `verifyTerm`, rather than
 * writing `verified = 1` itself. That keeps promotion in exactly one function
 * — the one that will not run without a name — and leaves the usual audit
 * trail behind, queue item and all.
 */
export function addTerm(
  db: Store,
  term: string,
  definition: string,
  reviewer: string,
  register: Register = 'both',
): StoredTerm {
  const name = reviewer.trim();
  if (name === '') {
    throw new Error(
      'adding a term needs your name — a hand-written definition is somebody\'s word.\n' +
        '  npm run review -- add <term> = <definition> --by <you>   (note the --)',
    );
  }

  const existing = findTerm(db, term);
  if (existing !== undefined) {
    throw new Error(
      `"${term}" already resolves to "${existing.term}" — edit that entry rather than ` +
        `adding a second one that means the same thing.`,
    );
  }

  const sense = parseSense(term, {
    definition,
    confidence: HAND_WRITTEN_CONFIDENCE,
    content_flags: [],
  });

  db.transaction(() => {
    insertTerm(db, {
      term,
      aliases: [],
      register,
      source: 'manual_seed',
      verified: false,
      senses: [sense],
    });
    verifyTerm(db, term, name);
  })();

  return locate(db, term);
}
