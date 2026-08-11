/**
 * Morphological variants.
 *
 * The dangerous direction is over-matching: a variant that lands on the wrong
 * entry produces a confidently wrong answer, which is worse than a miss
 * (CLAUDE.md rule 7). Roughly half of these assert what must *not* resolve.
 */

import { describe, expect, it } from 'vitest';
import { variantsOf } from '../../src/store/variants.js';

describe('variantsOf — what should resolve', () => {
  it('collapses a spaced phrase to its run-together spelling', () => {
    expect(variantsOf('no cap')).toContain('nocap');
  });

  it('collapses a hyphenated spelling too', () => {
    // normalise() turns the hyphen into a space, so this is the same path.
    expect(variantsOf('no-cap')).toContain('nocap');
  });

  it('strips a trailing apostrophe', () => {
    expect(variantsOf("bussin'")).toContain('bussin');
  });

  it('strips a possessive', () => {
    expect(variantsOf("rizz's")).toContain('rizz');
  });

  it('strips a simple plural', () => {
    expect(variantsOf('vibes')).toContain('vibe');
  });

  it('handles an -es plural', () => {
    expect(variantsOf('catches')).toContain('catch');
  });

  it('undoubles an -ing form', () => {
    expect(variantsOf('capping')).toContain('cap');
  });

  it('undoubles an -ed form', () => {
    expect(variantsOf('capped')).toContain('cap');
  });

  it('handles an -ing form with no doubling', () => {
    expect(variantsOf('slapping')).toContain('slap');
  });
});

describe('variantsOf — what must not', () => {
  it('never returns the input itself', () => {
    expect(variantsOf('cap')).not.toContain('cap');
  });

  it('leaves a double-s word alone — "mess" is not "mes"', () => {
    expect(variantsOf('mess')).not.toContain('mes');
  });

  it('produces nothing from empty or punctuation-only input', () => {
    expect(variantsOf('')).toEqual([]);
    expect(variantsOf('!!!')).toEqual([]);
  });

  it('never produces a stem shorter than two characters', () => {
    for (const word of ['as', 'is', 'ads', 'ing', 'bed']) {
      for (const v of variantsOf(word)) expect(v.length).toBeGreaterThanOrEqual(2);
    }
  });

  it('does not invent an "e" when stripping -ing', () => {
    // "vibing" → "vib" is offered, but guessing "vibe" would be spelling
    // reconstruction rather than suffix stripping. An alias covers it if needed.
    expect(variantsOf('vibing')).not.toContain('vibe');
  });
});
