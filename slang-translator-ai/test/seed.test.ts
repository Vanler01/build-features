/**
 * The seed vocabulary and its validator.
 *
 * Most of these assert the *rules*, not the data — the validator is what stops
 * a guess entering the store wearing a verified badge, and it is worth more
 * than the entries it currently guards.
 */

import { describe, expect, it } from 'vitest';
import { SeedError, loadSeed, parseTerm, report } from '../src/store/seed.js';
import { normalise } from '../src/store/types.js';
import { variantsOf } from '../src/store/variants.js';

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

describe('an alias means the same thing, not merely something related', () => {
  const terms = loadSeed(SEED_PATH);

  it('does not point a negation at the word it negates', () => {
    // "no cap" shipped as an alias of "cap", so someone asking what "no cap"
    // meant was told `"cap" = A lie, or exaggeration` — the inverse, under a
    // headword they never typed. Nothing mechanical can catch this; the seed
    // is where it has to be caught.
    const cap = terms.find((t) => t.term === 'cap');
    if (cap === undefined) throw new Error('cap missing from seed');
    const aliases = cap.aliases.map(normalise);
    expect(aliases).not.toContain('no cap');
    expect(aliases).not.toContain('nocap');
  });

  it('carries "no cap" as its own term, meaning affirmation rather than a lie', () => {
    const noCap = terms.find((t) => t.term === 'no cap');
    if (noCap === undefined) throw new Error('"no cap" missing from seed');
    expect(noCap.senses.every((s) => !/\blie\b/i.test(s.definition))).toBe(true);
  });

  it('curates no alias that variantsOf already generates', () => {
    // Redundant curation is harmless in itself but misleading: it implies the
    // mechanical path does not cover the shape, and the next person adds more.
    const redundant = terms.flatMap((t) =>
      t.aliases
        .filter((alias) => variantsOf(alias).includes(normalise(t.term)))
        .map((alias) => `${t.term}: ${alias}`),
    );
    expect(redundant).toEqual([]);
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
    const ate = terms.find((t) => t.term === 'ate');
    if (ate === undefined) throw new Error('ate missing from seed');
    expect(ate.aliases.map(normalise)).toContain('left no crumbs');
  });
});

describe('a malformed file', () => {
  it('is rejected rather than partially loaded', () => {
    expect(() => JSON.parse('not json')).toThrow();
    expect(() => parseTerm(null)).toThrow(SeedError);
    expect(() => parseTerm('a string')).toThrow(SeedError);
  });
});
