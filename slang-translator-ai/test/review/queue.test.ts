/**
 * The review queue and verification flow — Phase 2.
 *
 * The load-bearing assertions here are the ones about promotion: that it needs
 * a person's name, that nothing in the bot path can perform it, and that an
 * entry stays servable while it waits (CLAUDE.md rules 2 and 5).
 */

import { describe, expect, it } from 'vitest';
import { openStore, type Store } from '../../src/store/db.js';
import { findTerm, recordLookup } from '../../src/store/lookup.js';
import { insertTerm, reportTerm, writeClaudeTerm } from '../../src/store/write.js';
import {
  enqueue,
  pending,
  queueStats,
  rejectTerm,
  sweepDecayed,
  sweepLowConfidence,
  unverifiedCount,
  unverifyTerm,
  verifyTerm,
} from '../../src/review/queue.js';

const NOW = new Date('2026-08-11T00:00:00.000Z');

function daysAgo(days: number): string {
  return new Date(NOW.getTime() - days * 86_400_000).toISOString();
}

function freshStore(): Store {
  return openStore(':memory:');
}

/** Write a claude-sourced term the way a live miss would. */
function claudeTerm(
  db: Store,
  term: string,
  confidence: 'high' | 'medium' | 'low' = 'high',
): number {
  return writeClaudeTerm(db, {
    term,
    register: 'both',
    senses: [{ definition: `Definition of ${term}.`, confidence, contentFlags: [] }],
  });
}

/** Backdate a term's senses so decay has something to act on. */
function backdate(db: Store, termId: number, days: number): void {
  db.prepare('UPDATE senses SET last_seen = ? WHERE term_id = ?').run(daysAgo(days), termId);
  db.prepare('UPDATE terms SET last_seen = ? WHERE id = ?').run(daysAgo(days), termId);
}

describe('verification', () => {
  it('promotes a claude-sourced term when a person is named', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');

    const outcome = verifyTerm(db, 'rizz', 'blanc');

    const found = findTerm(db, 'rizz');
    expect(found?.verified).toBe(true);
    expect(found?.verifiedBy).toBe('blanc');
    expect(found?.verifiedAt).toBeDefined();
    // The source still names the real origin — promotion is not laundering.
    expect(found?.source).toBe('claude');
    expect(outcome.itemsResolved).toBe(1);
  });

  it('refuses to promote without a reviewer name', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');
    expect(() => verifyTerm(db, 'rizz', '')).toThrow(/reviewer name/i);
    expect(() => verifyTerm(db, 'rizz', '   ')).toThrow(/reviewer name/i);
    expect(findTerm(db, 'rizz')?.verified).toBe(false);
  });

  it('cannot be done by raw SQL without naming a reviewer', () => {
    // The schema is the backstop if application code is ever wrong.
    const db = freshStore();
    claudeTerm(db, 'rizz');
    expect(() => db.prepare("UPDATE terms SET verified = 1 WHERE term = 'rizz'").run()).toThrow();
  });

  it('refuses reviewer metadata on a row that is not verified', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');
    expect(() =>
      db.prepare("UPDATE terms SET verified_by = 'blanc' WHERE term = 'rizz'").run(),
    ).toThrow();
  });

  it('closes every open queue item for the term', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    reportTerm(db, id, 'wrong');
    expect(pending(db)).toHaveLength(2);

    verifyTerm(db, 'rizz', 'blanc');
    expect(pending(db)).toHaveLength(0);
  });

  it('resets the decay clock, because a person has just read it', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    backdate(db, id, 300);
    expect(findTerm(db, 'rizz', NOW)?.senses[0]?.effectiveConfidence).toBe('low');

    verifyTerm(db, 'rizz', 'blanc');
    expect(findTerm(db, 'rizz', NOW)?.senses[0]?.effectiveConfidence).toBe('high');
  });

  it('resolves by alias, not just by primary term', () => {
    const db = freshStore();
    insertTerm(db, {
      term: 'cap',
      aliases: ['no cap'],
      register: 'both',
      source: 'claude',
      verified: false,
      senses: [{ definition: 'A lie.', confidence: 'high', contentFlags: [] }],
    });
    verifyTerm(db, 'no cap', 'blanc');
    expect(findTerm(db, 'cap')?.verified).toBe(true);
  });

  it('throws on a term that does not exist rather than silently doing nothing', () => {
    const db = freshStore();
    expect(() => verifyTerm(db, 'nonexistent', 'blanc')).toThrow(/no term matching/i);
  });
});

describe('an unverified entry is still served', () => {
  it('stays readable while it waits for review — that is the cache doing its job', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');
    const found = findTerm(db, 'rizz');
    expect(found).toBeDefined();
    expect(found?.verified).toBe(false);
    expect(found?.senses[0]?.definition).toBe('Definition of rizz.');
  });
});

describe('reject', () => {
  it('clears the queue item without promoting the entry', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');
    const outcome = rejectTerm(db, 'rizz');

    expect(outcome.itemsResolved).toBe(1);
    expect(pending(db)).toHaveLength(0);
    expect(findTerm(db, 'rizz')?.verified).toBe(false);
  });
});

describe('unverify', () => {
  it('demotes a verified entry and sends it back to the queue', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');
    verifyTerm(db, 'rizz', 'blanc');

    unverifyTerm(db, 'rizz');

    const found = findTerm(db, 'rizz');
    expect(found?.verified).toBe(false);
    expect(found?.verifiedBy).toBeUndefined();
    expect(found?.verifiedAt).toBeUndefined();
    expect(pending(db)).toHaveLength(1);
  });
});

describe('enqueue dedupe', () => {
  it('does not queue the same open reason twice', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    // writeClaudeTerm already queued 'unverified'.
    expect(enqueue(db, id, 'unverified', 'again', NOW.toISOString())).toBe(false);
    expect(pending(db)).toHaveLength(1);
  });

  it('queues again once the previous item has been resolved', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    rejectTerm(db, 'rizz');
    expect(enqueue(db, id, 'unverified', 'second look', NOW.toISOString())).toBe(true);
    expect(pending(db)).toHaveLength(1);
  });
});

describe('sweepDecayed', () => {
  it('queues a stale entry', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'skibidi');
    verifyTerm(db, 'skibidi', 'blanc'); // clears the initial unverified item
    backdate(db, id, 300);

    expect(sweepDecayed(db, NOW)).toBe(1);
    const items = pending(db);
    expect(items).toHaveLength(1);
    expect(items[0]?.reason).toBe('decayed');
  });

  it('leaves a fresh entry alone', () => {
    const db = freshStore();
    claudeTerm(db, 'rizz');
    verifyTerm(db, 'rizz', 'blanc');
    expect(sweepDecayed(db, NOW)).toBe(0);
    expect(pending(db)).toHaveLength(0);
  });

  it('sweeps verified entries too — a confirmation ages like anything else', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'skibidi');
    verifyTerm(db, 'skibidi', 'blanc');
    backdate(db, id, 300);

    sweepDecayed(db, NOW);
    expect(pending(db)[0]?.reason).toBe('decayed');
  });

  it('is safe to run twice', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'skibidi');
    verifyTerm(db, 'skibidi', 'blanc');
    backdate(db, id, 300);

    expect(sweepDecayed(db, NOW)).toBe(1);
    expect(sweepDecayed(db, NOW)).toBe(0);
    expect(pending(db)).toHaveLength(1);
  });
});

describe('sweepLowConfidence', () => {
  it('catches a popular term that never looks stale', () => {
    // The gap sweepDecayed structurally cannot see: every lookup refreshes
    // last_seen, so a frequently-asked term stays "fresh" however unsure it is.
    const db = freshStore();
    const id = claudeTerm(db, 'bussin', 'low');
    rejectTerm(db, 'bussin'); // clear the initial unverified item
    for (let i = 0; i < 6; i += 1) recordLookup(db, id, true);

    expect(sweepDecayed(db, NOW)).toBe(0);
    expect(sweepLowConfidence(db, 5, NOW)).toBe(1);
    expect(pending(db)).toHaveLength(1);
  });

  it('ignores a low-confidence term nobody asks about', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'obscure', 'low');
    rejectTerm(db, 'obscure');
    recordLookup(db, id, true);
    expect(sweepLowConfidence(db, 5, NOW)).toBe(0);
  });

  it('ignores a popular high-confidence term', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz', 'high');
    rejectTerm(db, 'rizz');
    for (let i = 0; i < 10; i += 1) recordLookup(db, id, true);
    expect(sweepLowConfidence(db, 5, NOW)).toBe(0);
  });
});

describe('queue ordering and stats', () => {
  it('puts user reports ahead of everything else', () => {
    const db = freshStore();
    claudeTerm(db, 'first');
    const id = claudeTerm(db, 'second');
    reportTerm(db, id, 'this is wrong');

    expect(pending(db)[0]?.reason).toBe('reported');
  });

  it('counts open items by reason', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    reportTerm(db, id, 'wrong');
    const stats = queueStats(db);
    expect(stats.unverified).toBe(1);
    expect(stats.reported).toBe(1);
    expect(stats.decayed).toBe(0);
  });

  it('counts unverified terms overall', () => {
    const db = freshStore();
    claudeTerm(db, 'a');
    claudeTerm(db, 'b');
    expect(unverifiedCount(db)).toBe(2);
    verifyTerm(db, 'a', 'blanc');
    expect(unverifiedCount(db)).toBe(1);
  });
});

describe('lookups refresh last_seen', () => {
  it('a lookup makes a stale entry fresh again', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    backdate(db, id, 300);
    expect(findTerm(db, 'rizz', NOW)?.senses[0]?.effectiveConfidence).toBe('low');

    recordLookup(db, id, true);
    expect(findTerm(db, 'rizz', NOW)?.senses[0]?.effectiveConfidence).toBe('high');
  });

  it('still records nothing but a term id, timestamp and outcome', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'rizz');
    recordLookup(db, id, true);
    const row = db.prepare('SELECT * FROM lookups').get() as Record<string, unknown>;
    expect(Object.keys(row).sort()).toEqual(['found_locally', 'id', 'looked_up_at', 'term_id']);
  });
});
