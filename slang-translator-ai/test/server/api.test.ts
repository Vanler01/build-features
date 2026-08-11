/**
 * The extension's HTTP surface.
 *
 * The assertions that matter are the boundary ones: that a page-sized
 * selection is refused (rule 16), that only an extension origin is granted
 * CORS (any web page can reach loopback too), and that an internal failure
 * never echoes the term back.
 */

import type Anthropic from '@anthropic-ai/sdk';
import { describe, expect, it, vi } from 'vitest';
import { handleRequest, MAX_SELECTION_CHARS } from '../../src/server/api.js';
import { openStore, type Store } from '../../src/store/db.js';
import { insertTerm } from '../../src/store/write.js';
import type { Deps } from '../../src/bot/core.js';

const EXTENSION_ORIGIN = 'chrome-extension://abcdefghijklmnopabcdefghijklmnop';

function seededStore(): Store {
  const db = openStore(':memory:');
  insertTerm(db, {
    term: 'rizz',
    aliases: [],
    register: 'genz',
    source: 'manual_seed',
    verified: true,
    senses: [
      {
        definition: 'Charisma, especially flirting skill.',
        example: "he's got mad rizz",
        confidence: 'high',
        contentFlags: [],
      },
    ],
  });
  return db;
}

/** A client that fails loudly — the seeded paths must never reach Claude. */
function unusedClient(): Anthropic {
  return {
    messages: {
      create: vi.fn().mockRejectedValue(new Error('Claude must not be called for a store hit')),
    },
  } as unknown as Anthropic;
}

function deps(): Deps {
  return { db: seededStore(), client: unusedClient() };
}

type Request = Parameters<typeof handleRequest>[1];

function post(body: unknown, origin: string | undefined = EXTENSION_ORIGIN): Request {
  return {
    method: 'POST',
    path: '/lookup',
    origin,
    // Spreading over a default would reinstate it, so build the field directly.
    body: typeof body === 'string' ? body : JSON.stringify(body),
  };
}

/** A request with no Origin header at all, which a default parameter cannot express. */
function postWithoutOrigin(body: unknown): Request {
  return { method: 'POST', path: '/lookup', origin: undefined, body: JSON.stringify(body) };
}

describe('lookup', () => {
  it('answers a stored term without calling Claude', async () => {
    const res = await handleRequest(deps(), post({ term: 'rizz' }));
    expect(res.status).toBe(200);
    const payload = JSON.parse(res.body) as { reply: string };
    expect(payload.reply).toContain('Charisma, especially flirting skill.');
  });

  it('formats identically to the bot — one formatter, one content policy', async () => {
    const res = await handleRequest(deps(), post({ term: 'rizz' }));
    const payload = JSON.parse(res.body) as { reply: string };
    // The house format from reply.ts, curly-quoted example and all.
    expect(payload.reply).toBe(
      '"rizz" = Charisma, especially flirting skill. “he\'s got mad rizz”',
    );
  });
});

describe('rule 16 — the page must not leave the browser', () => {
  it('refuses a selection longer than the cap', async () => {
    const res = await handleRequest(deps(), post({ term: 'x'.repeat(MAX_SELECTION_CHARS + 1) }));
    expect(res.status).toBe(400);
    expect(JSON.parse(res.body)).toMatchObject({ error: expect.stringContaining('too long') });
  });

  it('accepts a selection exactly at the cap', async () => {
    const res = await handleRequest(deps(), post({ term: 'x'.repeat(MAX_SELECTION_CHARS) }));
    expect(res.status).not.toBe(400);
  });
});

describe('CORS', () => {
  it('grants an extension origin', async () => {
    const res = await handleRequest(deps(), post({ term: 'rizz' }));
    expect(res.headers['Access-Control-Allow-Origin']).toBe(EXTENSION_ORIGIN);
  });

  it('grants nothing to a web page — any site can reach loopback too', async () => {
    const res = await handleRequest(deps(), post({ term: 'rizz' }, 'https://example.com'));
    expect(res.headers['Access-Control-Allow-Origin']).toBeUndefined();
  });

  it('grants nothing when there is no origin at all', async () => {
    const res = await handleRequest(deps(), postWithoutOrigin({ term: 'rizz' }));
    expect(res.headers['Access-Control-Allow-Origin']).toBeUndefined();
  });

  it('answers a preflight without touching the store', async () => {
    const res = await handleRequest(deps(), {
      method: 'OPTIONS',
      path: '/lookup',
      origin: EXTENSION_ORIGIN,
      body: '',
    });
    expect(res.status).toBe(204);
    expect(res.headers['Access-Control-Allow-Origin']).toBe(EXTENSION_ORIGIN);
  });
});

describe('input validation', () => {
  it('rejects a non-JSON body', async () => {
    const res = await handleRequest(deps(), post('not json'));
    expect(res.status).toBe(400);
  });

  it('rejects a missing or non-string term', async () => {
    expect((await handleRequest(deps(), post({}))).status).toBe(400);
    expect((await handleRequest(deps(), post({ term: 42 }))).status).toBe(400);
  });

  it('rejects an empty or whitespace term', async () => {
    expect((await handleRequest(deps(), post({ term: '' }))).status).toBe(400);
    expect((await handleRequest(deps(), post({ term: '   ' }))).status).toBe(400);
  });
});

describe('routing', () => {
  it('has exactly one endpoint', async () => {
    const res = await handleRequest(deps(), { ...post({ term: 'rizz' }), path: '/anything-else' });
    expect(res.status).toBe(404);
  });

  it('refuses GET, which would put the term in a server log line', async () => {
    const res = await handleRequest(deps(), { ...post({ term: 'rizz' }), method: 'GET' });
    expect(res.status).toBe(405);
  });
});

describe('failure handling', () => {
  function failingDeps(): Deps {
    return {
      db: seededStore(),
      client: {
        messages: {
          create: vi.fn().mockRejectedValue(new Error('upstream exploded for "secretterm"')),
        },
      } as unknown as Anthropic,
    };
  }

  it('never echoes the term or an internal error back to the caller', async () => {
    const res = await handleRequest(failingDeps(), post({ term: 'secretterm' }));
    expect(res.body).not.toContain('secretterm');
    expect(res.body).not.toContain('exploded');
  });

  it('reports an outage on a BARE TERM as "nothing unusual here"', async () => {
    // Documenting existing behaviour rather than asserting a preference:
    // handleMessage catches a failed *definition* and answers NO_SLANG_REPLY,
    // on the reasoning that a term Claude could not define is, to the user,
    // indistinguishable from one that is not slang. The cost is that a real
    // outage reads as a confident "not slang" rather than "try again".
    const res = await handleRequest(failingDeps(), post({ term: 'secretterm' }));
    expect(res.status).toBe(200);
    expect(JSON.parse(res.body)).toMatchObject({
      reply: expect.stringContaining('Nothing unusual here'),
    });
  });

  it('reports an outage on a SENTENCE as a 502, not a false "no slang"', async () => {
    // The other half, and the one the 502 branch actually exists for: a
    // sentence goes to detectSlang first, whose failure is not caught inside
    // handleMessage and so reaches handleRequest. Same outage, different
    // answer depending on input length — worth pinning so the asymmetry is
    // visible rather than surprising.
    const res = await handleRequest(
      failingDeps(),
      post({ term: 'is this whole sentence slang or not' }),
    );
    expect(res.status).toBe(502);
    expect(JSON.parse(res.body)).toMatchObject({ error: 'lookup failed — try again' });
  });

  it('leaks neither the term nor the error text on the 502 path', async () => {
    const res = await handleRequest(
      failingDeps(),
      post({ term: 'secretterm and some more words here' }),
    );
    expect(res.body).not.toContain('secretterm');
    expect(res.body).not.toContain('exploded');
  });
});
