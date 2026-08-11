/**
 * The reviewer's view of an entry.
 *
 * The load-bearing case is the slur one: this view is the last place a rule 11
 * violation can be caught before `verify` freezes it into a confirmed row.
 */

import { describe, expect, it } from 'vitest';
import { formatEntry } from '../../src/review/format.js';
import type { StoredSense, StoredTerm } from '../../src/store/lookup.js';

function sense(
  partial: Omit<StoredSense, 'id' | 'lastSeen' | 'effectiveConfidence'> &
    Partial<Pick<StoredSense, 'lastSeen' | 'effectiveConfidence'>>,
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
    source: 'claude',
    verified: false,
    senses: [sense({ definition: 'Charisma.', confidence: 'high', contentFlags: [] })],
    ...overrides,
  };
}

describe('formatEntry — verification status', () => {
  it('marks an unverified entry plainly', () => {
    expect(formatEntry(term())).toContain('UNVERIFIED');
  });

  it('names the person who verified it, and when', () => {
    const out = formatEntry(
      term({ verified: true, verifiedBy: 'blanc', verifiedAt: '2026-08-11T09:00:00.000Z' }),
    );
    expect(out).toContain('verified by blanc');
    expect(out).toContain('2026-08-11');
  });

  it('shows the real source, not a laundered one', () => {
    expect(formatEntry(term({ verified: true, verifiedBy: 'blanc' }))).toContain('source: claude');
  });
});

describe('formatEntry — confidence', () => {
  it('shows one value when age has changed nothing', () => {
    const out = formatEntry(term());
    expect(out).toContain('confidence: high');
    expect(out).not.toContain('aged');
  });

  it('shows stored and aged together, so the reviewer can tell them apart', () => {
    const out = formatEntry(
      term({
        senses: [
          sense({
            definition: 'x',
            confidence: 'high',
            effectiveConfidence: 'low',
            contentFlags: [],
          }),
        ],
      }),
    );
    expect(out).toContain('high → low (aged)');
  });
});

describe('formatEntry — rule 11', () => {
  it('flags a slur carrying an example instead of printing it', () => {
    const out = formatEntry(
      term({
        senses: [
          sense({
            definition: 'A derogatory term for a group.',
            example: 'an example that models using it',
            confidence: 'high',
            contentFlags: ['slur'],
          }),
        ],
      }),
    );
    expect(out).not.toContain('an example that models using it');
    expect(out).toContain('POLICY VIOLATION');
    // The definition itself is still shown — flag and show, never hide.
    expect(out).toContain('A derogatory term for a group.');
  });

  it('prints a normal example for a non-slur entry', () => {
    const out = formatEntry(
      term({
        senses: [
          sense({
            definition: 'Charisma.',
            example: "he's got mad rizz",
            confidence: 'high',
            contentFlags: [],
          }),
        ],
      }),
    );
    // Straight apostrophe inside, curly wrapper outside: the example text
    // itself must pass through byte-for-byte.
    expect(out).toContain('e.g. “he\'s got mad rizz”');
    expect(out).not.toContain('POLICY VIOLATION');
  });
});

describe('formatEntry — region', () => {
  it('shows where a marked sense holds', () => {
    // Settable from the CLI, so it has to be visible here: a field you can
    // change but cannot see is one you will change by accident.
    const out = formatEntry(
      term({
        senses: [
          sense({ definition: 'Very.', confidence: 'high', contentFlags: [], region: 'UK' }),
        ],
      }),
    );
    expect(out).toContain('Very. (UK)');
  });

  it('says nothing at all for an unmarked sense', () => {
    // An absent region means "not known to be regional", which is a different
    // claim from "holds everywhere" and must not be rendered as either.
    const out = formatEntry(term());
    expect(out).toContain('Charisma.');
    expect(out).not.toMatch(/Charisma\. \(/);
  });
});
