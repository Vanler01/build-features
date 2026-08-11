/**
 * Reply formatting. The content cases here matter most: a flag must appear
 * beside the definition, never suppress it (REQUIREMENTS §8 — flag, and show).
 */

import { describe, expect, it } from 'vitest';
import { formatMultiTermReply, formatTermReply, NO_SLANG_REPLY } from '../../src/bot/reply.js';
import type { StoredSense, StoredTerm } from '../../src/store/lookup.js';

/**
 * Build a stored sense. `effectiveConfidence` defaults to the stored value —
 * i.e. a fresh entry that age has not touched — so a test that cares about
 * decay sets it explicitly and every other test reads as it did before.
 */
function sense(
  partial: Omit<StoredSense, 'id' | 'lastSeen' | 'effectiveConfidence'> &
    Partial<Pick<StoredSense, 'effectiveConfidence'>>,
): StoredSense {
  return {
    id: 1,
    lastSeen: '2026-08-01T00:00:00.000Z',
    effectiveConfidence: partial.effectiveConfidence ?? partial.confidence,
    ...partial,
  };
}

function term(overrides: Partial<StoredTerm> = {}): StoredTerm {
  return {
    id: 1,
    term: 'rizz',
    aliases: [],
    register: 'genz',
    source: 'manual_seed',
    verified: true,
    senses: [
      sense({
        definition: 'Charisma, especially flirting skill.',
        example: "he's got mad rizz.",
        confidence: 'high',
        contentFlags: [],
      }),
    ],
    ...overrides,
  };
}

describe('formatTermReply — single sense', () => {
  it('includes the term, definition, and example', () => {
    const reply = formatTermReply(term());
    expect(reply).toContain('"rizz"');
    expect(reply).toContain('Charisma, especially flirting skill.');
    expect(reply).toContain("he's got mad rizz.");
  });

  it('omits the example clause when there is none', () => {
    const reply = formatTermReply(
      term({ senses: [sense({ definition: 'x', confidence: 'high', contentFlags: [] })] }),
    );
    expect(reply).not.toContain('""');
  });

  it('flags a low-confidence sense rather than presenting it as certain', () => {
    const reply = formatTermReply(
      term({ senses: [sense({ definition: 'x', confidence: 'low', contentFlags: [] })] }),
    );
    expect(reply.toLowerCase()).toContain('not fully sure');
  });
});

describe('formatTermReply — multiple senses', () => {
  const cap = term({
    term: 'cap',
    senses: [
      sense({ definition: 'A lie, or exaggeration.', confidence: 'high', contentFlags: [] }),
      sense({ definition: 'A hat.', confidence: 'medium', contentFlags: [] }),
      sense({ definition: 'An upper limit.', confidence: 'medium', contentFlags: [] }),
    ],
  });

  it('leads with the contextual sense when given a lead index', () => {
    const reply = formatTermReply(cap, 1);
    const leadLine = reply.split('\n')[0] ?? '';
    expect(leadLine).toContain('A hat.');
  });

  it('notes the other senses in one line', () => {
    const reply = formatTermReply(cap, 1);
    expect(reply).toContain('A lie, or exaggeration.');
    expect(reply).toContain('An upper limit.');
  });

  it('defaults to the first sense when no context is available', () => {
    const reply = formatTermReply(cap);
    const leadLine = reply.split('\n')[0] ?? '';
    expect(leadLine).toContain('A lie, or exaggeration.');
  });
});

describe('formatTermReply — content flags: flag, and show', () => {
  it('shows a flagged definition beside its flag rather than hiding it', () => {
    const reply = formatTermReply(
      term({
        term: 'gooning',
        senses: [
          sense({ definition: 'A sexual practice.', confidence: 'high', contentFlags: ['sexual'] }),
        ],
      }),
    );
    expect(reply).toContain('[sexual]');
    expect(reply).toContain('A sexual practice.');
  });

  it('gives a slur a neutral definition and shows it, without an example', () => {
    const reply = formatTermReply(
      term({
        term: 'slur-example',
        senses: [
          sense({
            definition: 'A derogatory term for a group.',
            confidence: 'high',
            contentFlags: ['slur'],
          }),
        ],
      }),
    );
    expect(reply).toContain('[slur]');
    expect(reply).toContain('A derogatory term for a group.');
  });
});

describe('no-slang path', () => {
  it('is a plain, confident statement — not a strained interpretation', () => {
    expect(NO_SLANG_REPLY.toLowerCase()).toContain('nothing unusual');
  });
});

describe('formatMultiTermReply', () => {
  it('joins several term replies with a blank line between them', () => {
    const joined = formatMultiTermReply(['first', 'second']);
    expect(joined).toBe('first\n\nsecond');
  });

  it('returns a single reply unchanged', () => {
    expect(formatMultiTermReply(['only'])).toBe('only');
  });
});
