/**
 * Most-looked-up prioritisation and alias management — Phase 4.
 */

import { describe, expect, it } from 'vitest';
import { openStore, type Store } from '../../src/store/db.js';
import { findTerm, recordLookup } from '../../src/store/lookup.js';
import { reportTerm, writeClaudeTerm } from '../../src/store/write.js';
import { addAlias, mostLookedUp, pending } from '../../src/review/queue.js';

function freshStore(): Store {
  return openStore(':memory:');
}

function claudeTerm(db: Store, term: string): number {
  return writeClaudeTerm(db, {
    term,
    register: 'both',
    senses: [{ definition: `Definition of ${term}.`, confidence: 'high', contentFlags: [] }],
  });
}

function lookUp(db: Store, id: number, times: number): void {
  for (let i = 0; i < times; i += 1) recordLookup(db, id, true);
}

describe('queue prioritisation', () => {
  it('puts the most-asked-for term first', () => {
    const db = freshStore();
    const quiet = claudeTerm(db, 'quiet');
    const popular = claudeTerm(db, 'popular');
    lookUp(db, quiet, 1);
    lookUp(db, popular, 9);

    expect(pending(db)[0]?.term).toBe('popular');
  });

  it('still puts a report ahead of a more popular unverified term', () => {
    // Demand orders within a reason, it does not outrank one. Someone saying
    // an answer is wrong stays the strongest signal.
    const db = freshStore();
    const popular = claudeTerm(db, 'popular');
    const reported = claudeTerm(db, 'reported');
    lookUp(db, popular, 50);
    reportTerm(db, reported, 'this is wrong');

    const first = pending(db)[0];
    expect(first?.reason).toBe('reported');
    expect(first?.term).toBe('reported');
  });

  it('falls back to queue age when nothing has been looked up', () => {
    const db = freshStore();
    claudeTerm(db, 'first');
    claudeTerm(db, 'second');
    expect(pending(db).map((i) => i.term)).toEqual(['first', 'second']);
  });

  it('reports the count so the reviewer can see why the order is what it is', () => {
    const db = freshStore();
    const id = claudeTerm(db, 'popular');
    lookUp(db, id, 4);
    expect(pending(db)[0]?.lookupCount).toBe(4);
  });
});

describe('mostLookedUp', () => {
  it('ranks by demand and flags what is still unchecked', () => {
    const db = freshStore();
    const a = claudeTerm(db, 'alpha');
    const b = claudeTerm(db, 'beta');
    lookUp(db, a, 2);
    lookUp(db, b, 7);

    const top = mostLookedUp(db);
    expect(top.map((t) => t.term)).toEqual(['beta', 'alpha']);
    expect(top[0]?.lookups).toBe(7);
    expect(top[0]?.verified).toBe(false);
  });

  it('omits terms nobody has asked for', () => {
    const db = freshStore();
    claudeTerm(db, 'ignored');
    expect(mostLookedUp(db)).toEqual([]);
  });
});

describe('addAlias', () => {
  it('makes a new spelling resolve to the term', () => {
    const db = freshStore();
    claudeTerm(db, 'fixing to');
    addAlias(db, 'fixing to', 'finna');
    expect(findTerm(db, 'finna')?.term).toBe('fixing to');
  });

  it('is idempotent', () => {
    const db = freshStore();
    claudeTerm(db, 'cap');
    addAlias(db, 'cap', '🧢');
    addAlias(db, 'cap', '🧢');
    expect(findTerm(db, '🧢')?.term).toBe('cap');
  });

  it('refuses to steal a spelling that already means something else', () => {
    // Repointing a live word silently is how a store starts giving
    // confidently wrong answers.
    const db = freshStore();
    claudeTerm(db, 'cap');
    claudeTerm(db, 'bet');
    expect(() => addAlias(db, 'cap', 'bet')).toThrow(/already resolves/);
    expect(findTerm(db, 'bet')?.term).toBe('bet');
  });

  it('refuses an empty variant or an unknown term', () => {
    const db = freshStore();
    claudeTerm(db, 'cap');
    expect(() => addAlias(db, 'cap', '   ')).toThrow(/cannot be empty/);
    expect(() => addAlias(db, 'nonexistent', 'x')).toThrow(/no term matching/);
  });
});

describe('variant resolution through the store', () => {
  it('resolves an inflected form to a stored term', () => {
    const db = freshStore();
    claudeTerm(db, 'cap');
    expect(findTerm(db, 'capping')?.term).toBe('cap');
    expect(findTerm(db, 'capped')?.term).toBe('cap');
  });

  it('resolves a run-together spelling of a phrase', () => {
    const db = freshStore();
    claudeTerm(db, 'no cap');
    expect(findTerm(db, 'nocap')?.term).toBe('no cap');
  });

  it('still misses a genuinely unknown word rather than forcing a match', () => {
    const db = freshStore();
    claudeTerm(db, 'cap');
    expect(findTerm(db, 'zorbling')).toBeUndefined();
  });

  it('prefers an exact match over a variant of another term', () => {
    // "caps" exists in its own right; it must not be answered as "cap".
    const db = freshStore();
    claudeTerm(db, 'cap');
    claudeTerm(db, 'caps');
    expect(findTerm(db, 'caps')?.term).toBe('caps');
  });
});
