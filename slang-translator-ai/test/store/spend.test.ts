/**
 * Cost accounting and the daily ceiling.
 *
 * Two things matter here beyond the arithmetic: the ceiling degrades to the
 * store rather than to an error, and the table records no content — a cost
 * log is not a second place to keep what people looked up.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { openStore, type Store } from '../../src/store/db.js';
import {
  callLog,
  callsByPurpose,
  callsToday,
  hitRate,
  overDailyLimit,
} from '../../src/store/spend.js';
import { recordLookup } from '../../src/store/lookup.js';
import { writeClaudeTerm } from '../../src/store/write.js';

let db: Store;

beforeEach(() => {
  db = openStore(':memory:');
});

describe('recording a call', () => {
  it('stores the model, the purpose and the time — and nothing else', () => {
    // The shape assertion is the point. A term or a prompt appearing in this
    // table later would be a privacy regression that nothing else would catch.
    callLog(db).record('claude-haiku-4-5', 'detect');
    const row = db.prepare('SELECT * FROM claude_calls').get() as Record<string, unknown>;
    expect(Object.keys(row).sort()).toEqual(['called_at', 'id', 'model', 'purpose']);
    expect(row['model']).toBe('claude-haiku-4-5');
    expect(row['purpose']).toBe('detect');
  });

  it('counts calls made today', () => {
    const log = callLog(db);
    log.record('claude-sonnet-5', 'define');
    log.record('claude-haiku-4-5', 'detect');
    expect(callsToday(db)).toBe(2);
  });

  it('ignores calls from previous days', () => {
    db.prepare('INSERT INTO claude_calls (model, purpose, called_at) VALUES (?, ?, ?)').run(
      'claude-sonnet-5',
      'define',
      '2020-01-01T12:00:00.000Z',
    );
    expect(callsToday(db)).toBe(0);
  });

  it('breaks today down by purpose', () => {
    const log = callLog(db);
    log.record('claude-sonnet-5', 'define');
    log.record('claude-sonnet-5', 'define');
    log.record('claude-haiku-4-5', 'detect');
    expect(callsByPurpose(db)).toEqual({ define: 2, detect: 1 });
  });
});

describe('the daily ceiling', () => {
  it('is not reached below the limit', () => {
    callLog(db).record('claude-sonnet-5', 'define');
    expect(overDailyLimit(db, 2)).toBe(false);
  });

  it('is reached at the limit, not one past it', () => {
    const log = callLog(db);
    log.record('claude-sonnet-5', 'define');
    log.record('claude-sonnet-5', 'define');
    expect(overDailyLimit(db, 2)).toBe(true);
  });

  it('treats an unset limit as no limit, never as zero', () => {
    // The distinction that matters: a missing config value must not silently
    // become "never call Claude", which looks identical to a broken store.
    for (let i = 0; i < 50; i += 1) callLog(db).record('claude-sonnet-5', 'define');
    expect(overDailyLimit(db, undefined)).toBe(false);
    expect(overDailyLimit(db, 0)).toBe(true);
  });
});

describe('cache hit rate', () => {
  function term(name: string): number {
    return writeClaudeTerm(db, {
      term: name,
      register: 'both',
      senses: [{ definition: 'A thing.', confidence: 'high', contentFlags: [] }],
    });
  }

  it('reports nothing rather than zero when there are no lookups', () => {
    expect(hitRate(db)).toEqual({ hits: 0, misses: 0, total: 0 });
  });

  it('separates lookups the store answered from those that needed Claude', () => {
    const id = term('cap');
    recordLookup(db, id, true);
    recordLookup(db, id, true);
    recordLookup(db, id, false);
    expect(hitRate(db)).toEqual({ hits: 2, misses: 1, total: 3 });
  });
});
