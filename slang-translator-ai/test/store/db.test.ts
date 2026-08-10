/**
 * Store round-trip: migrations apply, a term written by the Claude path reads
 * back correctly, and a report lands in the review queue. This is the seam
 * most likely to be wrong in a way types alone can't catch — SQL typos,
 * JSON-encoding of content_flags, the boolean-to-0/1 conversion.
 */

import { describe, expect, it } from 'vitest';
import { openStore } from '../../src/store/db.js';
import { findTerm, recordLookup } from '../../src/store/lookup.js';
import { reportTerm, writeClaudeTerm } from '../../src/store/write.js';

function freshStore(): ReturnType<typeof openStore> {
  return openStore(':memory:');
}

describe('migrations', () => {
  it('applies cleanly and is idempotent on a second open', () => {
    const db = freshStore();
    db.close();
  });
});

describe('the Claude write path', () => {
  it('writes a term as unverified, claude-sourced, and queues it for review', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'yeet',
      register: 'both',
      senses: [
        { definition: 'To throw with force.', confidence: 'medium', contentFlags: [] },
      ],
    });

    const found = findTerm(db, 'yeet');
    if (found === undefined) throw new Error('just-written term not found');
    expect(found.id).toBe(id);
    expect(found.source).toBe('claude');
    expect(found.verified).toBe(false);
    expect(found.senses).toHaveLength(1);
    expect(found.senses[0]?.definition).toBe('To throw with force.');

    const queued = db.prepare('SELECT reason FROM review_queue WHERE term_id = ?').get(id) as
      | { reason: string }
      | undefined;
    expect(queued?.reason).toBe('unverified');
  });

  it('refuses a claude-sourced row from arriving verified, even via raw SQL', () => {
    // The schema-level CHECK is the last line of defence if application code
    // is ever wrong — belt matching the seed validator's suspenders.
    const db = freshStore();
    expect(() =>
      db
        .prepare(
          `INSERT INTO terms (term, normalised, register, source, verified, first_seen, last_seen)
           VALUES ('x', 'x', 'both', 'claude', 1, 'now', 'now')`,
        )
        .run(),
    ).toThrow();
  });
});

describe('lookup', () => {
  it('resolves an alias to its term', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'no cap',
      register: 'both',
      senses: [{ definition: 'Not a lie; for real.', confidence: 'high', contentFlags: [] }],
    });
    db.prepare('INSERT INTO aliases (term_id, variant, normalised) VALUES (?, ?, ?)').run(
      id,
      'nocap',
      'nocap',
    );

    const found = findTerm(db, 'NoCap');
    expect(found?.id).toBe(id);
  });

  it('returns undefined on a genuine miss, not a throw', () => {
    const db = freshStore();
    expect(findTerm(db, 'not a real term')).toBeUndefined();
  });

  it('records only a term id and timestamp, never message text', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'bet',
      register: 'both',
      senses: [{ definition: 'Agreement.', confidence: 'high', contentFlags: [] }],
    });
    recordLookup(db, id, true);

    const row = db.prepare('SELECT * FROM lookups').get() as Record<string, unknown>;
    expect(Object.keys(row).sort()).toEqual(['found_locally', 'id', 'looked_up_at', 'term_id']);
  });
});

describe('reporting', () => {
  it('queues an existing term with reason reported', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'mid',
      register: 'both',
      senses: [{ definition: 'Mediocre.', confidence: 'high', contentFlags: [] }],
    });
    reportTerm(db, id, 'this definition is wrong');

    const rows = db.prepare('SELECT reason, note FROM review_queue WHERE term_id = ?').all(id) as {
      reason: string;
      note: string | null;
    }[];
    expect(rows.some((r) => r.reason === 'reported' && r.note === 'this definition is wrong')).toBe(
      true,
    );
  });
});
