/**
 * Correcting an entry.
 *
 * The rules worth holding onto are the ones about what an edit must *not* do:
 * it must not promote anything, must not rewrite where an entry came from, and
 * must not leave one person's name standing behind another person's wording.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { addSense, addTerm, editSense, removeSense } from '../../src/review/edit.js';
import { verifyTerm } from '../../src/review/queue.js';
import { openStore, type Store } from '../../src/store/db.js';
import { findTerm } from '../../src/store/lookup.js';
import { insertTerm, writeClaudeTerm } from '../../src/store/write.js';

let db: Store;

beforeEach(() => {
  db = openStore(':memory:');
  writeClaudeTerm(db, {
    term: 'cap',
    register: 'both',
    senses: [
      { definition: 'A lie, or exaggeration.', confidence: 'high', contentFlags: [] },
      { definition: 'A hat.', confidence: 'medium', contentFlags: [] },
    ],
  });
});

describe('editing a sense', () => {
  it('rewrites the definition and shows the new entry back', () => {
    const entry = editSense(db, 'cap', 1, { definition: 'A lie.' });
    expect(entry.senses[0]?.definition).toBe('A lie.');
    expect(entry.senses[1]?.definition).toBe('A hat.');
  });

  it('does not promote the entry it just corrected', () => {
    // The whole point of the separation: fixing the wording is not the same
    // act as vouching for it (CLAUDE.md rule 2).
    const entry = editSense(db, 'cap', 1, { definition: 'A lie.' });
    expect(entry.verified).toBe(false);
    expect(entry.verifiedBy).toBeUndefined();
  });

  it('leaves a claude-sourced entry claude-sourced', () => {
    // Relabelling it manual_seed on edit would forge the provenance rule 3
    // exists to protect — the definition still started as a model's guess.
    const entry = editSense(db, 'cap', 1, { definition: 'A lie.' });
    expect(entry.source).toBe('claude');
  });

  it('sets and clears an example', () => {
    const withExample = editSense(db, 'cap', 1, { example: "That's cap." });
    expect(withExample.senses[0]?.example).toBe("That's cap.");

    const cleared = editSense(db, 'cap', 1, { example: null });
    expect(cleared.senses[0]?.example).toBeUndefined();
  });

  it('leaves the example alone when the change does not mention it', () => {
    editSense(db, 'cap', 1, { example: "That's cap." });
    const entry = editSense(db, 'cap', 1, { definition: 'An untruth.' });
    expect(entry.senses[0]?.example).toBe("That's cap.");
  });

  it('sets and clears a region', () => {
    const marked = editSense(db, 'cap', 1, { region: 'US' });
    expect(marked.senses[0]?.region).toBe('US');
    expect(editSense(db, 'cap', 1, { region: null }).senses[0]?.region).toBeUndefined();
  });

  it('sets content flags and confidence', () => {
    const entry = editSense(db, 'cap', 1, { contentFlags: ['vulgar'], confidence: 'low' });
    expect(entry.senses[0]?.contentFlags).toEqual(['vulgar']);
    expect(entry.senses[0]?.confidence).toBe('low');
  });

  it('refuses an unknown flag or confidence rather than storing it', () => {
    expect(() => editSense(db, 'cap', 1, { contentFlags: ['spicy'] })).toThrow(
      /unknown content flag/,
    );
    expect(() => editSense(db, 'cap', 1, { confidence: 'certain' })).toThrow(
      /confidence must be one of/,
    );
  });

  it('names the range rather than failing obscurely on a bad sense number', () => {
    expect(() => editSense(db, 'cap', 9, { definition: 'x' })).toThrow(/no sense 9/);
    expect(() => editSense(db, 'nothing', 1, { definition: 'x' })).toThrow(/no term matching/);
  });
});

describe('the content policy still applies to an edit', () => {
  it('refuses to flag a sense as a slur while it still carries an example', () => {
    // Neither half is a violation on its own, which is exactly why the merged
    // sense is what gets validated. This is rule 11 arriving by the back door.
    editSense(db, 'cap', 1, { example: "That's cap." });
    expect(() => editSense(db, 'cap', 1, { contentFlags: ['slur'] })).toThrow(
      /must not carry a usage example/,
    );
  });

  it('allows the slur flag once the example has been cleared', () => {
    editSense(db, 'cap', 1, { example: "That's cap." });
    editSense(db, 'cap', 1, { example: null });
    const entry = editSense(db, 'cap', 1, { contentFlags: ['slur'] });
    expect(entry.senses[0]?.contentFlags).toEqual(['slur']);
    expect(entry.senses[0]?.example).toBeUndefined();
  });

  it('refuses an empty definition', () => {
    expect(() => editSense(db, 'cap', 1, { definition: '   ' })).toThrow(/needs a definition/);
  });
});

describe('editing an entry somebody has already verified', () => {
  beforeEach(() => {
    verifyTerm(db, 'cap', 'blanc');
  });

  it('refuses without a name, because the stored one vouched for the old text', () => {
    expect(() => editSense(db, 'cap', 1, { definition: 'A falsehood.' })).toThrow(
      /needs your name/,
    );
  });

  it('re-stamps the name to whoever made the edit', () => {
    const entry = editSense(db, 'cap', 1, { definition: 'A falsehood.' }, 'someone-else');
    expect(entry.verified).toBe(true);
    expect(entry.verifiedBy).toBe('someone-else');
  });

  it('never turns an unverified entry verified along the way', () => {
    writeClaudeTerm(db, {
      term: 'yeet',
      register: 'genz',
      senses: [{ definition: 'To throw.', confidence: 'high', contentFlags: [] }],
    });
    const entry = editSense(db, 'yeet', 1, { definition: 'To throw hard.' }, 'blanc');
    expect(entry.verified).toBe(false);
    expect(entry.verifiedBy).toBeUndefined();
  });
});

describe('adding and removing senses', () => {
  it('adds a sense to an existing term', () => {
    const entry = addSense(db, 'cap', 'An upper limit.');
    expect(entry.senses).toHaveLength(3);
    expect(entry.senses[2]?.definition).toBe('An upper limit.');
  });

  it('removes a sense that is not the last one', () => {
    const entry = removeSense(db, 'cap', 2);
    expect(entry.senses).toHaveLength(1);
    expect(entry.senses[0]?.definition).toBe('A lie, or exaggeration.');
  });

  it('refuses to remove the last sense', () => {
    // A term with no senses is not empty, it is broken: formatTermReply throws
    // on it, so every lookup of the term would crash.
    removeSense(db, 'cap', 2);
    expect(() => removeSense(db, 'cap', 1)).toThrow(/only this sense left/);
  });

  it('renumbers the remaining senses the way show prints them', () => {
    addSense(db, 'cap', 'An upper limit.');
    const entry = removeSense(db, 'cap', 1);
    expect(entry.senses.map((s) => s.definition)).toEqual(['A hat.', 'An upper limit.']);
  });
});

describe('hand-writing a term', () => {
  it('is the one path that produces manual_seed, and it carries a name', () => {
    const entry = addTerm(db, 'skibidi', 'A nonsense word from a video series.', 'blanc');
    expect(entry.source).toBe('manual_seed');
    expect(entry.verified).toBe(true);
    expect(entry.verifiedBy).toBe('blanc');
  });

  it('refuses without a reviewer name', () => {
    expect(() => addTerm(db, 'skibidi', 'A nonsense word.', '  ')).toThrow(/needs your name/);
  });

  it('refuses a term that already resolves to something', () => {
    expect(() => addTerm(db, 'cap', 'A lie.', 'blanc')).toThrow(/already resolves to/);
  });

  it('refuses a spelling that resolves to an existing term by variant', () => {
    // "capping" reaches "cap" mechanically, so adding it as its own term would
    // create a second entry the lookup path can never reach.
    expect(() => addTerm(db, 'capping', 'Lying.', 'blanc')).toThrow(/already resolves to/);
  });

  it('leaves no open queue item behind — it was verified as it was created', () => {
    addTerm(db, 'skibidi', 'A nonsense word.', 'blanc');
    const id = findTerm(db, 'skibidi')?.id;
    const open = db
      .prepare('SELECT COUNT(*) AS n FROM review_queue WHERE term_id = ? AND resolved_at IS NULL')
      .get(id) as { n: number };
    expect(open.n).toBe(0);
  });

  it('is reachable by lookup immediately', () => {
    addTerm(db, 'left no crumbs', 'Did something flawlessly.', 'blanc');
    expect(findTerm(db, 'left no crumbs')?.source).toBe('manual_seed');
  });
});

describe('an edit counts as a person touching the entry', () => {
  it('moves last_seen forward, the way verification does', () => {
    const stale = '2020-01-01T00:00:00.000Z';
    insertTerm(db, {
      term: 'yeet',
      aliases: [],
      register: 'genz',
      source: 'claude',
      verified: false,
      senses: [{ definition: 'To throw.', confidence: 'high', contentFlags: [] }],
    });
    db.prepare(
      'UPDATE senses SET last_seen = ? WHERE term_id = (SELECT id FROM terms WHERE term = ?)',
    ).run(stale, 'yeet');

    const entry = editSense(db, 'yeet', 1, { definition: 'To throw with force.' });
    expect(entry.senses[0]?.lastSeen).not.toBe(stale);
    // Fresh, but still nobody's confirmation.
    expect(entry.verified).toBe(false);
  });
});
