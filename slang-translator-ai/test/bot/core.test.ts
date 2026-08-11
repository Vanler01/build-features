/**
 * End-to-end bot logic against a real in-memory store and a routed mock of
 * the Anthropic client. This is where AGENTS.md's mandatory cases live:
 * precision (one term / none / ordinary sense), sense disambiguation, the
 * cache round-trip, content flags surviving the full flow, and privacy.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type Anthropic from '@anthropic-ai/sdk';
import { handleMessage, handleReport, type Deps } from '../../src/bot/core.js';
import { LIMIT_REPLY, NO_SLANG_REPLY } from '../../src/bot/reply.js';
import { openStore, type Store } from '../../src/store/db.js';
import { findTerm } from '../../src/store/lookup.js';
import { callsByPurpose, callsToday } from '../../src/store/spend.js';
import { insertTerm } from '../../src/store/write.js';

function seededStore(): Store {
  const db = openStore(':memory:');
  insertTerm(db, {
    term: 'cap',
    aliases: ['🧢'],
    register: 'both',
    source: 'manual_seed',
    verified: true,
    senses: [
      { definition: 'A lie, or exaggeration.', confidence: 'high', contentFlags: [] },
      { definition: 'A hat.', confidence: 'medium', contentFlags: [] },
    ],
  });
  // A genuine multi-word term with a genuine multi-word alias. Both matter
  // here: the store-first hit has to keep working for phrases, or the fix to
  // the miss path below would have traded one bug for another.
  insertTerm(db, {
    term: 'ate',
    aliases: ['left no crumbs'],
    register: 'both',
    source: 'manual_seed',
    verified: true,
    senses: [{ definition: 'Did something excellently.', confidence: 'high', contentFlags: [] }],
  });
  insertTerm(db, {
    term: 'gooning',
    aliases: [],
    register: 'both',
    source: 'manual_seed',
    verified: true,
    senses: [{ definition: 'A sexual practice.', confidence: 'high', contentFlags: ['sexual'] }],
  });
  return db;
}

/** Routes a forced tool_choice to a canned response, keyed by tool name. */
function routedClient(responses: Record<string, unknown>): Anthropic {
  const create = vi
    .fn()
    .mockImplementation((params: Anthropic.MessageCreateParamsNonStreaming) => {
      const choice = params.tool_choice;
      if (choice === undefined || choice.type !== 'tool') {
        throw new Error('expected a forced tool_choice');
      }
      const input = responses[choice.name];
      if (input === undefined) {
        throw new Error(`no mock response configured for tool "${choice.name}"`);
      }
      return Promise.resolve({
        stop_reason: 'tool_use',
        content: [{ type: 'tool_use', id: 'tu', name: choice.name, input }],
      });
    });
  return { messages: { create } } as unknown as Anthropic;
}

let db: Store;

beforeEach(() => {
  db = seededStore();
});

describe('precision — the mandatory cases (AGENTS.md)', () => {
  it('a bare term already in the store answers without calling Claude', async () => {
    const client = routedClient({});
    const deps: Deps = { db, client };
    const reply = await handleMessage(deps, 'cap');
    expect(reply).toContain('A lie, or exaggeration.');
    expect(client.messages.create).not.toHaveBeenCalled();
  });

  it('a multi-word term in the store still answers from the store', async () => {
    // Store-first runs before any word counting, so a phrase that is a real
    // term never reaches detection at all.
    const client = routedClient({});
    const reply = await handleMessage({ db, client }, 'left no crumbs');
    expect(reply).toContain('Did something excellently.');
    expect(client.messages.create).not.toHaveBeenCalled();
  });

  it('a sentence containing one unstored slang term gets defined and stored', async () => {
    const client = routedClient({
      detected_slang: { terms: ['yeet'] },
      define_term: {
        register: 'genz',
        senses: [{ definition: 'To throw with force.', confidence: 'medium', content_flags: [] }],
      },
    });
    const reply = await handleMessage({ db, client }, 'he really yeeted that across the room');
    expect(reply).toContain('To throw with force.');
    expect(findTerm(db, 'yeet')?.source).toBe('claude');
  });

  it('a short sentence is scanned for slang, not stored as a term itself', async () => {
    // The regression this branch exists for. "he's got rizz" is three words,
    // which the old threshold read as "the user has named a term" — so the
    // phrase was handed to defineTerm, which returns the string it was given
    // verbatim, and a row called `he's got rizz` was written to the store.
    const client = routedClient({
      detected_slang: { terms: ['rizz'] },
      define_term: {
        register: 'genz',
        senses: [
          {
            definition: 'Charisma, especially flirting skill.',
            confidence: 'high',
            content_flags: [],
          },
        ],
      },
    });
    const reply = await handleMessage({ db, client }, "he's got rizz");

    expect(reply).toContain('Charisma, especially flirting skill.');
    expect(findTerm(db, 'rizz')).toBeDefined();
    expect(findTerm(db, "he's got rizz")).toBeUndefined();
    // Nothing phrase-shaped reached the store under any spelling.
    const terms = db.prepare('SELECT term FROM terms').all() as { term: string }[];
    expect(terms.map((t) => t.term)).not.toContain("he's got rizz");
  });

  it('a two-word message with no slang in it stores nothing at all', async () => {
    const client = routedClient({ detected_slang: { terms: [] } });
    const before = (db.prepare('SELECT COUNT(*) AS n FROM terms').get() as { n: number }).n;
    const reply = await handleMessage({ db, client }, 'good morning');

    expect(reply).toBe(NO_SLANG_REPLY);
    expect((db.prepare('SELECT COUNT(*) AS n FROM terms').get() as { n: number }).n).toBe(before);
  });

  it('"nothing unusual here" is a passing answer for an ordinary sentence', async () => {
    const client = routedClient({ detected_slang: { terms: [] } });
    const reply = await handleMessage({ db, client }, "I'll bet you £5 it rains tomorrow");
    expect(reply).toBe(NO_SLANG_REPLY);
  });
});

describe('sense disambiguation', () => {
  it('leads with the sense that fits a longer message with context', async () => {
    const client = routedClient({
      detected_slang: { terms: ['cap'] },
      disambiguate_sense: { sense_index: 1 },
    });
    const reply = await handleMessage({ db, client }, 'nice cap you got there my friend');
    const leadLine = reply.split('\n')[0] ?? '';
    expect(leadLine).toContain('A hat.');
  });

  it('a bare multi-sense term with no context leads with the first stored sense', async () => {
    const client = routedClient({});
    const reply = await handleMessage({ db, client }, 'cap');
    const leadLine = reply.split('\n')[0] ?? '';
    expect(leadLine).toContain('A lie, or exaggeration.');
    expect(client.messages.create).not.toHaveBeenCalled();
  });
});

describe('cache round trip', () => {
  it('a miss writes back as unverified, and a second lookup is served locally', async () => {
    const client = routedClient({
      define_term: {
        register: 'genz',
        senses: [{ definition: 'To throw with force.', confidence: 'medium', content_flags: [] }],
      },
    });
    const deps: Deps = { db, client };

    await handleMessage(deps, 'yeet');
    expect(findTerm(db, 'yeet')?.verified).toBe(false);
    expect(client.messages.create).toHaveBeenCalledTimes(1);

    const second = await handleMessage(deps, 'yeet');
    expect(second).toContain('To throw with force.');
    // No new Claude call — the second lookup hit the store.
    expect(client.messages.create).toHaveBeenCalledTimes(1);
  });

  it('never promotes a term to verified just from being looked up', async () => {
    const client = routedClient({
      define_term: {
        register: 'genz',
        senses: [{ definition: 'x', confidence: 'high', content_flags: [] }],
      },
    });
    const deps: Deps = { db, client };
    for (let i = 0; i < 3; i += 1) {
      await handleMessage(deps, 'skibidi');
    }
    // Only a human review action sets verified — no code path here does.
    expect(findTerm(db, 'skibidi')?.verified).toBe(false);
  });
});

describe('content flags survive the full flow — flag, and show', () => {
  it('a flagged stored term is answered, not suppressed', async () => {
    const client = routedClient({ detected_slang: { terms: ['gooning'] } });
    const reply = await handleMessage({ db, client }, 'what does gooning mean');
    expect(reply).toContain('[sexual]');
    expect(reply).toContain('A sexual practice.');
  });

  it('a vulgar-but-harmless term is flagged rather than dropped from the reply', async () => {
    insertTerm(db, {
      term: 'thicc',
      aliases: [],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [
        { definition: 'Curvy in an attractive way.', confidence: 'high', contentFlags: ['vulgar'] },
      ],
    });
    const client = routedClient({ detected_slang: { terms: ['thicc'] } });
    const reply = await handleMessage({ db, client }, 'she looked thicc in that dress');
    expect(reply).toContain('[vulgar]');
    expect(reply).toContain('Curvy in an attractive way.');
  });
});

describe('the daily Claude ceiling', () => {
  it('counts every call the flow makes, through one chokepoint', async () => {
    const client = routedClient({
      detected_slang: { terms: ['yeet'] },
      define_term: {
        register: 'genz',
        senses: [{ definition: 'To throw.', confidence: 'high', content_flags: [] }],
      },
    });
    await handleMessage({ db, client }, 'he really yeeted that across the room');
    expect(callsByPurpose(db)).toEqual({ detect: 1, define: 1 });
  });

  it('serves the store past the ceiling instead of failing or spending', async () => {
    const client = routedClient({});
    const deps: Deps = { db, client, dailyCallLimit: 0 };

    // Already in the store, so this never needed Claude in the first place.
    expect(await handleMessage(deps, 'cap')).toContain('A lie, or exaggeration.');
    // Not in the store, so this is the one that would have cost money.
    expect(await handleMessage(deps, 'skibidi')).toBe(LIMIT_REPLY);
    expect(client.messages.create).not.toHaveBeenCalled();
  });

  it('says it hit a limit rather than claiming the word is not slang', async () => {
    // "Nothing unusual here" would be a lie about the language rather than a
    // fact about this tool, and the reader cannot tell the two apart.
    const client = routedClient({});
    const reply = await handleMessage({ db, client, dailyCallLimit: 0 }, 'skibidi');
    expect(reply).not.toBe(NO_SLANG_REPLY);
    expect(reply).toContain("today's lookup limit");
  });

  it('stops mid-message rather than defining a dozen unknown terms past the cap', async () => {
    const client = routedClient({
      detected_slang: { terms: ['aaa', 'bbb', 'ccc'] },
      define_term: {
        register: 'genz',
        senses: [{ definition: 'A thing.', confidence: 'low', content_flags: [] }],
      },
    });
    // One detect plus one define fills a ceiling of 2; the other two
    // candidates must not be defined anyway.
    await handleMessage({ db, client, dailyCallLimit: 2 }, 'aaa bbb ccc all at once please');
    expect(callsToday(db)).toBe(2);
  });

  it('leaves an unconfigured limit uncapped rather than silently zero', async () => {
    const client = routedClient({
      define_term: {
        register: 'genz',
        senses: [{ definition: 'To throw.', confidence: 'high', content_flags: [] }],
      },
    });
    const reply = await handleMessage({ db, client }, 'yeet');
    expect(reply).toContain('To throw.');
  });
});

describe('privacy — lookups never carry message text', () => {
  it('records only a term id, timestamp, and hit/miss flag', async () => {
    const client = routedClient({});
    await handleMessage({ db, client }, 'cap');

    const rows = db.prepare('SELECT * FROM lookups').all() as Record<string, unknown>[];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(Object.keys(row).sort()).toEqual(['found_locally', 'id', 'looked_up_at', 'term_id']);
    }
  });
});

describe('/report', () => {
  it('queues a term found by its exact name', () => {
    const client = routedClient({});
    const result = handleReport({ db, client }, 'cap this is wrong');
    expect(result).toContain('"cap"');
    expect(result).toContain('queued for review');
  });

  it('finds a multi-word alias before falling back to the first word', () => {
    // Without the whole-argument attempt this reports "left", which is not a
    // term at all.
    const client = routedClient({});
    const result = handleReport({ db, client }, 'left no crumbs');
    expect(result).toContain('"ate"');
  });

  it('says plainly when the term is not stored', () => {
    const client = routedClient({});
    const result = handleReport({ db, client }, 'notarealterm');
    expect(result).toContain("don't have");
  });

  it('shows usage on empty input', () => {
    const client = routedClient({});
    const result = handleReport({ db, client }, '   ');
    expect(result).toContain('Usage:');
  });
});
