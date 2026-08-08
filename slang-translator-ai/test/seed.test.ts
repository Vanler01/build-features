/**
 * The seed vocabulary and its validator.
 *
 * Most of these assert the *rules*, not the data — the validator is what stops
 * a guess entering the store wearing a verified badge, and it is worth more
 * than the 56 entries it currently guards.
 */

import { describe, expect, it } from 'vitest';
import { SeedError, loadSeed, parseTerm, report } from '../src/store/seed.js';
import { normalise } from '../src/store/types.js';

const SEED_PATH = new URL('../data/seed.json', import.meta.url).pathname;

function entry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    term: 'example',
    aliases: [],
    register: 'both',
    senses: [{ definition: 'A thing.', confidence: 'high', content_flags: [] }],
    source: 'claude',
    verified: false,
    ...overrides,
  };
}

describe('provenance', () => {
  it('refuses a claude-sourced entry that arrives verified', () => {
    // The check this module exists for: otherwise a guess becomes a fact that
    // everything downstream then trusts.
    expect(() => parseTerm(entry({ verified: true }))).toThrow(/cannot ship verified/);
  });

  it('allows a hand-written entry to be verified', () => {
    expect(() =>
      parseTerm(entry({ source: 'manual_seed', verified: true })),
    ).not.toThrow();
  });

  it('refuses a generic or unknown source', () => {
    for (const source of ['db', 'unknown', '', 'ai']) {
      expect(() => parseTerm(entry({ source }))).toThrow(/source must be one of/);
    }
  });

  it('refuses a missing verified flag rather than defaulting it', () => {
    const e = entry();
    delete e['verified'];
    expect(() => parseTerm(e)).toThrow(/verified must be a boolean/);
  });
});

describe('content policy', () => {
  it('refuses a slur that carries a usage example', () => {
    // An example models using the word. The one hard rule.
    expect(() =>
      parseTerm(
        entry({
          senses: [
            {
              definition: 'A derogatory term for a group.',
              example: 'someone said it',
              confidence: 'high',
              content_flags: ['slur'],
            },
          ],
        }),
      ),
    ).toThrow(/must not carry a usage example/);
  });

  it('allows a slur defined without an example', () => {
    expect(() =>
      parseTerm(
        entry({
          senses: [
            {
              definition: 'A derogatory term for a group.',
              confidence: 'high',
              content_flags: ['slur'],
            },
          ],
        }),
      ),
    ).not.toThrow();
  });

  it('refuses an unknown content flag', () => {
    expect(() =>
      parseTerm(
        entry({
          senses: [{ definition: 'x', confidence: 'high', content_flags: ['spicy'] }],
        }),
      ),
    ).toThrow(/unknown content flag/);
  });

  it('requires content_flags to exist, so nothing is unflagged by omission', () => {
    expect(() =>
      parseTerm(entry({ senses: [{ definition: 'x', confidence: 'high' }] })),
    ).toThrow(/content_flags must be an array/);
  });
});

describe('shape', () => {
  it('refuses a term with no senses', () => {
    expect(() => parseTerm(entry({ senses: [] }))).toThrow(/at least one sense/);
  });

  it('refuses a sense with no definition', () => {
    expect(() =>
      parseTerm(entry({ senses: [{ definition: '  ', confidence: 'high', content_flags: [] }] })),
    ).toThrow(/needs a definition/);
  });

  it('refuses an unknown confidence', () => {
    expect(() =>
      parseTerm(entry({ senses: [{ definition: 'x', confidence: 'sure', content_flags: [] }] })),
    ).toThrow(/confidence must be one of/);
  });
});

describe('the shipped seed', () => {
  const terms = loadSeed(SEED_PATH);

  it('loads and is a useful size', () => {
    expect(terms.length).toBeGreaterThanOrEqual(50);
  });

  it('is entirely unverified, because a model wrote it', () => {
    // If this ever fails, somebody promoted the seed without reading it.
    expect(terms.every((t) => !t.verified)).toBe(true);
    expect(new Set(terms.map((t) => t.source))).toEqual(new Set(['claude']));
  });

  it('has no duplicate terms', () => {
    expect(() => loadSeed(SEED_PATH)).not.toThrow();
  });

  it('carries the multi-sense cases the design exists for', () => {
    for (const word of ['cap', 'bet', 'mid', 'sick', 'fire', 'slaps', 'cooked']) {
      const found = terms.find((t) => t.term === word);
      if (found === undefined) throw new Error(`${word} missing from seed`);
      expect(found.senses.length, `${word} should have several senses`).toBeGreaterThan(1);
    }
  });

  it('includes the ordinary-English sense for words that have one', () => {
    // Without it the bot answers "mid = mediocre" for "mid-July".
    const mid = terms.find((t) => t.term === 'mid');
    if (mid === undefined) throw new Error('mid missing from seed');
    expect(mid.senses.some((s) => /ordinary English/i.test(s.definition))).toBe(true);
  });

  it('flags the entries that need it', () => {
    const flagged = terms.filter((t) => t.senses.some((s) => s.contentFlags.length > 0));
    expect(flagged.length).toBeGreaterThan(0);
    expect(flagged.map((t) => t.term)).toContain('gooning');
  });

  it('keeps definitions free of the slang they explain', () => {
    // The audience is everybody (REQUIREMENTS §12), so a definition that
    // performs the register is useless to most of the people asking.
    const jargon = /\b(iykyk|lowkey|fr fr|no cap|deadass|bussin|situationship)\b/i;
    const offenders = terms.flatMap((t) =>
      t.senses
        .filter((s) => jargon.test(s.definition) && !jargon.test(t.term))
        .map((s) => `${t.term}: ${s.definition}`),
    );
    expect(offenders).toEqual([]);
  });

  it('every sense has a definition and a confidence', () => {
    for (const t of terms) {
      for (const s of t.senses) {
        expect(s.definition.length, `${t.term} has an empty definition`).toBeGreaterThan(0);
        expect(['high', 'medium', 'low']).toContain(s.confidence);
      }
    }
  });

  it('reports what still needs review', () => {
    const r = report(terms);
    expect(r.unverified.length).toBe(r.terms);
    expect(r.senses).toBeGreaterThan(r.terms);
  });
});

describe('normalisation', () => {
  it('folds case and whitespace', () => {
    expect(normalise('  No   CAP ')).toBe('no cap');
  });

  it('strips surrounding punctuation but keeps apostrophes', () => {
    expect(normalise('"rizz!"')).toBe('rizz');
    expect(normalise("it's giving")).toBe("it's giving");
  });

  it('is stable across the seed aliases', () => {
    const terms = loadSeed(SEED_PATH);
    const cap = terms.find((t) => t.term === 'cap');
    if (cap === undefined) throw new Error('cap missing from seed');
    expect(cap.aliases.map(normalise)).toContain('no cap');
  });
});

describe('a malformed file', () => {
  it('is rejected rather than partially loaded', () => {
    expect(() => JSON.parse('not json')).toThrow();
    expect(() => parseTerm(null)).toThrow(SeedError);
    expect(() => parseTerm('a string')).toThrow(SeedError);
  });
});
