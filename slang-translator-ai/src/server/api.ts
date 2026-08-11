/**
 * The HTTP surface the browser extension talks to.
 *
 * It exists because of CLAUDE.md rule 17: no API key ships to a client. The
 * extension holds no Claude key and no bot token; it asks this, and this holds
 * the keys. That is the whole reason Phase 3 needs a server at all.
 *
 * Written as a pure request→response function so the routing, the CORS policy
 * and the length cap are all testable without opening a socket. `index.ts` is
 * the only part that touches `node:http`.
 */

import { handleMessage, type Deps } from '../bot/core.js';

/**
 * The longest selection accepted for a lookup.
 *
 * This is rule 16 enforcement, not a nicety. "Only the selected term leaves
 * the browser — never the page" is trivially defeated by selecting an entire
 * article and right-clicking it, which would ship the whole page here. A term
 * or a sentence fits comfortably; a page does not.
 */
export const MAX_SELECTION_CHARS = 300;

export interface ApiRequest {
  readonly method: string;
  readonly path: string;
  /** The `Origin` header, if the caller sent one. */
  readonly origin: string | undefined;
  readonly body: string;
}

export interface ApiResponse {
  readonly status: number;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: string;
}

/**
 * Only a browser extension may call this.
 *
 * Not `*`: the server listens on loopback, but any web page the user visits
 * can also reach loopback. A permissive header would let any site run lookups
 * against this store and learn that it exists. An extension origin is the only
 * caller that should ever appear.
 */
function corsHeaders(origin: string | undefined): Record<string, string> {
  if (origin === undefined || !origin.startsWith('chrome-extension://')) return {};
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function json(
  status: number,
  payload: Record<string, unknown>,
  origin: string | undefined,
): ApiResponse {
  return {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
    body: JSON.stringify(payload),
  };
}

/** Pull a non-empty `term` out of a JSON body, or explain what was wrong. */
function readTerm(body: string): { term: string } | { error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return { error: 'body must be JSON' };
  }
  if (typeof parsed !== 'object' || parsed === null) return { error: 'body must be a JSON object' };

  const term = (parsed as Record<string, unknown>)['term'];
  if (typeof term !== 'string') return { error: 'term must be a string' };
  if (term.trim() === '') return { error: 'term must not be empty' };
  if (term.length > MAX_SELECTION_CHARS) {
    return { error: `selection too long — select a word or a sentence, not a page` };
  }
  return { term };
}

/**
 * Route and answer one request.
 *
 * Deliberately tiny: one real endpoint. Every extra route is another thing
 * that has to be reasoned about for privacy, and the extension needs exactly
 * one thing — the meaning of a selected term.
 */
export async function handleRequest(deps: Deps, req: ApiRequest): Promise<ApiResponse> {
  const { origin } = req;

  if (req.method === 'OPTIONS') {
    return { status: 204, headers: corsHeaders(origin), body: '' };
  }

  if (req.path !== '/lookup') {
    return json(404, { error: 'not found' }, origin);
  }

  if (req.method !== 'POST') {
    return json(405, { error: 'use POST' }, origin);
  }

  const parsed = readTerm(req.body);
  if ('error' in parsed) {
    return json(400, { error: parsed.error }, origin);
  }

  try {
    // The same function the Telegram bot calls. One lookup path and one
    // formatter across both clients, so the content rules (11, 12, 13) are
    // enforced in one place rather than re-implemented in the extension where
    // they could drift.
    const reply = await handleMessage(deps, parsed.term);
    return json(200, { reply }, origin);
  } catch {
    // Never echo the error: it can contain the term, and an upstream failure
    // is not the user's problem to read a stack trace about.
    return json(502, { error: 'lookup failed — try again' }, origin);
  }
}
