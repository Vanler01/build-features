/**
 * Regional senses — REQUIREMENTS §13, settled in Phase 4.
 *
 * A regional meaning is its own sense row with a `region`, not a note buried
 * in another sense's prose. These check the column survives a round trip and
 * that the reader is told where a meaning holds.
 */

import { describe, expect, it } from 'vitest';
import { formatTermReply } from '../../src/bot/reply.js';
import { openStore, type Store } from '../../src/store/db.js';
import { findTerm } from '../../src/store/lookup.js';
import { parseTerm } from '../../src/store/seed.js';
import { insertTerm, writeClaudeTerm } from '../../src/store/write.js';

function freshStore(): Store {
  return openStore(':memory:');
}

describe('the region column', () => {
  it('round-trips through the seed path', () => {
    const db = freshStore();
    insertTerm(db, {
      term: 'bare',
      aliases: [],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [
        { definition: 'Very, or a lot of.', confidence: 'high', contentFlags: [], region: 'UK' },
      ],
    });
    expect(findTerm(db, 'bare')?.senses[0]?.region).toBe('UK');
  });

  it('round-trips through the Claude path', () => {
    const db = freshStore();
    writeClaudeTerm(db, {
      term: 'peng',
      register: 'both',
      senses: [
        {
          definition: 'Attractive, or excellent.',
          confidence: 'high',
          contentFlags: [],
          region: 'UK',
        },
      ],
    });
    expect(findTerm(db, 'peng')?.senses[0]?.region).toBe('UK');
  });

  it('stays absent when unmarked, rather than defaulting to a claim', () => {
    const db = freshStore();
    writeClaudeTerm(db, {
      term: 'rizz',
      register: 'genz',
      senses: [{ definition: 'Charisma.', confidence: 'high', contentFlags: [] }],
    });
    expect(findTerm(db, 'rizz')?.senses[0]?.region).toBeUndefined();
  });

  it('lets one term hold a regional and an unmarked sense side by side', () => {
    // The reason this is a column and not a note: both are real senses, and
    // disambiguation has to be able to choose between them.
    const db = freshStore();
    insertTerm(db, {
      term: 'dead',
      aliases: [],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [
        { definition: 'Extremely funny.', confidence: 'high', contentFlags: [] },
        {
          definition: 'Very, or completely.',
          confidence: 'medium',
          contentFlags: [],
          region: 'UK',
        },
      ],
    });
    const senses = findTerm(db, 'dead')?.senses ?? [];
    expect(senses).toHaveLength(2);
    expect(senses[0]?.region).toBeUndefined();
    expect(senses[1]?.region).toBe('UK');
  });
});

describe('the seed validator', () => {
  it('accepts a sense with a region', () => {
    const parsed = parseTerm({
      term: 'bare',
      register: 'both',
      source: 'claude',
      verified: false,
      senses: [{ definition: 'Very.', confidence: 'high', content_flags: [], region: 'UK' }],
    });
    expect(parsed.senses[0]?.region).toBe('UK');
  });

  it('rejects an empty region rather than storing a meaningless one', () => {
    expect(() =>
      parseTerm({
        term: 'bare',
        register: 'both',
        source: 'claude',
        verified: false,
        senses: [{ definition: 'Very.', confidence: 'high', content_flags: [], region: '  ' }],
      }),
    ).toThrow(/region/);
  });
});

describe('the reader is told where a meaning holds', () => {
  it('marks a regional sense', () => {
    const db = freshStore();
    insertTerm(db, {
      term: 'bare',
      aliases: [],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [
        { definition: 'Very, or a lot of.', confidence: 'high', contentFlags: [], region: 'UK' },
      ],
    });
    const entry = findTerm(db, 'bare');
    if (entry === undefined) throw new Error('just-inserted term not found');
    const reply = formatTermReply(entry);
    expect(reply).toContain('(UK)');
  });

  it('says nothing for an unmarked sense', () => {
    const db = freshStore();
    insertTerm(db, {
      term: 'rizz',
      aliases: [],
      register: 'genz',
      source: 'manual_seed',
      verified: true,
      senses: [{ definition: 'Charisma.', confidence: 'high', contentFlags: [] }],
    });
    const entry = findTerm(db, 'rizz');
    if (entry === undefined) throw new Error('just-inserted term not found');
    expect(formatTermReply(entry)).toBe('"rizz" = Charisma.');
  });

  it('marks a regional sense in the alternates line too', () => {
    const db = freshStore();
    insertTerm(db, {
      term: 'dead',
      aliases: [],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [
        { definition: 'Extremely funny.', confidence: 'high', contentFlags: [] },
        {
          definition: 'Very, or completely.',
          confidence: 'medium',
          contentFlags: [],
          region: 'UK',
        },
      ],
    });
    const entry = findTerm(db, 'dead');
    if (entry === undefined) throw new Error('just-inserted term not found');
    const reply = formatTermReply(entry);
    expect(reply.split('\n')[1] ?? '').toContain('(UK)');
  });
});
