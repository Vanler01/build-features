/**
 * Confidence decay — CLAUDE.md rule 4, REQUIREMENTS §4.
 *
 * Slang shifts meaning while keeping its spelling, so a definition is not a
 * fact that stays true; it is an observation with a date on it. An entry
 * nobody has touched in months is a re-verification candidate.
 *
 * Decay is computed at read time and never written back. Persisting a decayed
 * confidence would destroy the original assessment, and the stored value is
 * what a reviewer needs to see in order to judge the entry — the reader sees
 * the decayed one. `senseConfidence` returns both for that reason.
 */

import type { Confidence } from './types.js';

/** One step down after this long without a lookup. */
export const STALE_DAYS = 90;
/** Two steps down after this long — a year-old untouched entry is a guess. */
export const VERY_STALE_DAYS = 240;

const MS_PER_DAY = 86_400_000;

// Ordered worst-to-best so a step down is an index shift.
const LADDER: readonly Confidence[] = ['low', 'medium', 'high'];

/** Whole days between `lastSeen` and `now`. Negative clock skew reads as 0. */
export function ageInDays(lastSeen: string, now: Date): number {
  const then = new Date(lastSeen).getTime();
  if (Number.isNaN(then)) {
    throw new Error(`ageInDays: unparseable timestamp "${lastSeen}"`);
  }
  return Math.max(0, Math.floor((now.getTime() - then) / MS_PER_DAY));
}

/** How many confidence steps an entry of this age has lost. */
export function decaySteps(age: number): number {
  if (age >= VERY_STALE_DAYS) return 2;
  if (age >= STALE_DAYS) return 1;
  return 0;
}

/**
 * The confidence to *show a reader*, given what was stored and how long it has
 * been since anyone touched the entry. Never rises above the stored value.
 */
export function decayConfidence(stored: Confidence, lastSeen: string, now: Date): Confidence {
  const steps = decaySteps(ageInDays(lastSeen, now));
  if (steps === 0) return stored;

  const index = LADDER.indexOf(stored);
  if (index === -1) throw new Error(`decayConfidence: unknown confidence "${stored}"`);
  return LADDER[Math.max(0, index - steps)] as Confidence;
}

/**
 * Whether an entry has decayed far enough to want a human's eyes.
 *
 * Deliberately "has it lost anything at all" rather than "is it now low":
 * a term stored at `low` starts at the bottom and could never become a decay
 * candidate under the stricter reading, which is backwards — an entry that was
 * a guess when written and has since gone stale is the *most* suspect thing in
 * the store, not the least.
 */
export function hasDecayed(lastSeen: string, now: Date): boolean {
  return decaySteps(ageInDays(lastSeen, now)) > 0;
}
