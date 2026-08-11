/**
 * Confidence decay — CLAUDE.md rule 4.
 *
 * Dates are fixed rather than relative to "now" so these cannot start failing
 * in ninety days' time.
 */

import { describe, expect, it } from 'vitest';
import {
  ageInDays,
  decayConfidence,
  decaySteps,
  hasDecayed,
  STALE_DAYS,
  VERY_STALE_DAYS,
} from '../../src/store/decay.js';

const NOW = new Date('2026-08-11T00:00:00.000Z');

/** A timestamp exactly `days` before NOW. */
function daysAgo(days: number): string {
  return new Date(NOW.getTime() - days * 86_400_000).toISOString();
}

describe('ageInDays', () => {
  it('counts whole days', () => {
    expect(ageInDays(daysAgo(10), NOW)).toBe(10);
  });

  it('treats a future timestamp as age zero rather than negative', () => {
    // Clock skew between machines is real; a negative age would decay
    // *upwards* through the ladder if it ever reached decaySteps.
    expect(ageInDays(daysAgo(-30), NOW)).toBe(0);
  });

  it('throws on an unparseable timestamp instead of silently reading NaN', () => {
    expect(() => ageInDays('not a date', NOW)).toThrow();
  });
});

describe('decaySteps', () => {
  it('does not decay a fresh entry', () => {
    expect(decaySteps(0)).toBe(0);
    expect(decaySteps(STALE_DAYS - 1)).toBe(0);
  });

  it('drops one step exactly at the stale threshold', () => {
    expect(decaySteps(STALE_DAYS)).toBe(1);
  });

  it('drops two steps at the very-stale threshold', () => {
    expect(decaySteps(VERY_STALE_DAYS)).toBe(2);
    expect(decaySteps(VERY_STALE_DAYS * 10)).toBe(2);
  });
});

describe('decayConfidence', () => {
  it('leaves a recently-seen entry alone', () => {
    expect(decayConfidence('high', daysAgo(1), NOW)).toBe('high');
  });

  it('ages high to medium once stale', () => {
    expect(decayConfidence('high', daysAgo(STALE_DAYS + 1), NOW)).toBe('medium');
  });

  it('ages high to low once very stale', () => {
    expect(decayConfidence('high', daysAgo(VERY_STALE_DAYS + 1), NOW)).toBe('low');
  });

  it('ages medium to low once stale', () => {
    expect(decayConfidence('medium', daysAgo(STALE_DAYS + 1), NOW)).toBe('low');
  });

  it('never falls below low, however old', () => {
    expect(decayConfidence('low', daysAgo(3650), NOW)).toBe('low');
    expect(decayConfidence('medium', daysAgo(3650), NOW)).toBe('low');
  });

  it('never raises confidence above what was stored', () => {
    for (const stored of ['low', 'medium', 'high'] as const) {
      for (const age of [0, 30, 89, 90, 239, 240, 1000]) {
        const result = decayConfidence(stored, daysAgo(age), NOW);
        const ladder = ['low', 'medium', 'high'];
        expect(ladder.indexOf(result)).toBeLessThanOrEqual(ladder.indexOf(stored));
      }
    }
  });
});

describe('hasDecayed', () => {
  it('is false for a fresh entry', () => {
    expect(hasDecayed(daysAgo(1), NOW)).toBe(false);
  });

  it('is true as soon as anything has been lost', () => {
    expect(hasDecayed(daysAgo(STALE_DAYS), NOW)).toBe(true);
  });

  it('is true for a stale entry that was already low', () => {
    // The case a "is it now low?" test would wrongly pass over: an entry that
    // was a guess when written and has since gone stale is the most suspect
    // thing in the store, not something to skip.
    expect(hasDecayed(daysAgo(VERY_STALE_DAYS), NOW)).toBe(true);
  });
});
