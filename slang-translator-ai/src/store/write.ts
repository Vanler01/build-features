/**
 * Writing to the store: a Claude-defined term on a miss, and a user report.
 *
 * Both paths are deliberately narrow. There is no parameter for `verified`
 * on the Claude path — a model's answer cannot arrive trusted (CLAUDE.md
 * rule 2), so the function signature makes that mistake impossible to make,
 * not just documented against.
 */

import type { Store } from './db.js';
import type { Register, Sense } from './types.js';
import { normalise } from './types.js';

/** What Claude produced for a term the store had never seen. */
export interface DefinedTerm {
  readonly term: string;
  readonly register: Register;
  readonly senses: readonly Sense[];
}

/** Insert a Claude-defined term as unverified, and queue it for human review. */
export function writeClaudeTerm(db: Store, defined: DefinedTerm): number {
  const now = new Date().toISOString();

  const insertTerm = db.prepare(
    `INSERT INTO terms (term, normalised, register, source, verified, first_seen, last_seen)
     VALUES (?, ?, ?, 'claude', 0, ?, ?)`,
  );
  const insertSense = db.prepare(
    `INSERT INTO senses
       (term_id, definition, example, confidence, content_flags, first_seen, last_seen)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  );
  const insertReview = db.prepare(
    `INSERT INTO review_queue (term_id, reason, queued_at) VALUES (?, 'unverified', ?)`,
  );

  const run = db.transaction((): number => {
    const info = insertTerm.run(
      defined.term,
      normalise(defined.term),
      defined.register,
      now,
      now,
    );
    const termId = Number(info.lastInsertRowid);
    for (const sense of defined.senses) {
      insertSense.run(
        termId,
        sense.definition,
        sense.example ?? null,
        sense.confidence,
        JSON.stringify(sense.contentFlags),
        now,
        now,
      );
    }
    insertReview.run(termId, now);
    return termId;
  });

  return run();
}

/** Queue an existing term for review because a user flagged it wrong. */
export function reportTerm(db: Store, termId: number, note: string | undefined): void {
  db.prepare(
    `INSERT INTO review_queue (term_id, reason, note, queued_at) VALUES (?, 'reported', ?, ?)`,
  ).run(termId, note ?? null, new Date().toISOString());
}
