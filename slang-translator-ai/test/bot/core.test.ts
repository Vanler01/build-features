/**
 * End-to-end bot logic against a real in-memory store and a routed mock of
 * the Anthropic client. This is where AGENTS.md's mandatory cases live:
 * precision (one term / none / ordinary sense), sense disambiguation, the
 * cache round-trip, content flags surviving the full flow, and privacy.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type Anthropic from '@anthropic-ai/sdk';
import { handleMessage, handleReport, type Deps } from '../../src/bot/core.js';
import { NO_SLANG_REPLY } from '../../src/bot/reply.js';
import { openStore, type Store } from '../../src/store/db.js';
import { findTerm } from '../../src/store/lookup.js';
import { insertTerm } from '../../src/store/write.js';

function seededStore(): Store {
  const db = openStore(':memory:');
  insertTerm(db, {
    term: 'cap',
    aliases: ['no cap'],
    register: 'both',
    source: 'manual_seed',
    verified: true,
    senses: [
      { definition: 'A lie, or exaggeration.', confidence: 'high', contentFlags: [] },
      { definition: 'A hat.', confidence: 'medium', contentFlags: [] },
    ],
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
    const reply = await handleMessage(deps, 'no cap');
    expect(reply).toContain('A lie, or exaggeration.');
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

describe('privacy — lookups never carry message text', () => {
  it('records only a term id, timestamp, and hit/miss flag', async () => {
    const client = routedClient({});
    await handleMessage({ db, client }, 'no cap');

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
    const client = routedClient({});
    const result = handleReport({ db, client }, 'no cap');
    expect(result).toContain('"cap"');
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
