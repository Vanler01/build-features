/**
 * The bot's actual logic, kept free of grammY so it's testable without a
 * fake Telegram context — REQUIREMENTS §5 (bot flow) end to end.
 */

import type Anthropic from '@anthropic-ai/sdk';
import { defineTerm } from '../ai/define.js';
import { disambiguateSense } from '../ai/disambiguate.js';
import { detectSlang } from '../ai/detect.js';
import type { Store } from '../store/db.js';
import type { StoredTerm } from '../store/lookup.js';
import { findTerm, recordLookup } from '../store/lookup.js';
import { reportTerm, writeClaudeTerm } from '../store/write.js';
import { formatMultiTermReply, formatTermReply, NO_SLANG_REPLY } from './reply.js';

export interface Deps {
  readonly db: Store;
  readonly client: Anthropic;
}

export const HELP_TEXT = `Send me a word, or a whole message, and I'll tell you what any \
slang in it means.

/report <term> [why it's wrong] — flag a definition that's wrong. The cheapest way to help \
fix the store.`;

/**
 * One word, so there is nothing to detect — the user has named the term.
 *
 * This used to be "three words or fewer", which was wrong in a way that filled
 * the store with junk. `defineTerm` returns the string it was handed, verbatim
 * (`ai/define.ts` — Claude never renames it), so "he's got rizz" missed the
 * store, took this branch, and was written into `terms` as a row literally
 * called `he's got rizz`: unverified, queued for review, a Sonnet call spent,
 * and a headword nobody will ever look up again.
 *
 * Lowering the threshold was not enough on its own, because real multi-word
 * terms exist — "left no crumbs", "hits different", "green flag". Those still
 * answer instantly on the store-first hit above. What changed is only the
 * *miss* path: it now asks detection what the slang in the message actually
 * is, instead of assuming the whole message was the term.
 */
function isSingleWord(text: string): boolean {
  return text.trim().split(/\s+/).filter(Boolean).length === 1;
}

/** Define an unknown term via Claude, write it as unverified, and read it back. */
async function defineAndStore(deps: Deps, term: string, context?: string): Promise<StoredTerm> {
  const defined = await defineTerm(deps.client, term, context);
  writeClaudeTerm(deps.db, defined);
  const stored = findTerm(deps.db, defined.term);
  if (stored === undefined) {
    throw new Error(`defineAndStore: "${defined.term}" not found immediately after writing it`);
  }
  return stored;
}

/** Handle one incoming message and produce the reply text. */
export async function handleMessage(deps: Deps, text: string): Promise<string> {
  const direct = findTerm(deps.db, text);
  if (direct !== undefined) {
    recordLookup(deps.db, direct.id, true);
    return formatTermReply(direct);
  }

  if (isSingleWord(text)) {
    let stored;
    try {
      stored = await defineAndStore(deps, text.trim());
    } catch {
      // A term Claude couldn't cleanly define is, from the user's side,
      // indistinguishable from "nothing unusual here" — say so plainly
      // rather than surfacing an internal failure.
      return NO_SLANG_REPLY;
    }
    recordLookup(deps.db, stored.id, false);
    return formatTermReply(stored);
  }

  const candidates = await detectSlang(deps.client, text);
  if (candidates.length === 0) return NO_SLANG_REPLY;

  const replies: string[] = [];
  for (const candidate of candidates) {
    const stored = findTerm(deps.db, candidate);

    if (stored !== undefined) {
      recordLookup(deps.db, stored.id, true);
      if (stored.senses.length > 1) {
        const leadIndex = await disambiguateSense(deps.client, stored.term, stored.senses, text);
        replies.push(formatTermReply(stored, leadIndex));
      } else {
        replies.push(formatTermReply(stored));
      }
      continue;
    }

    try {
      const defined = await defineAndStore(deps, candidate, text);
      recordLookup(deps.db, defined.id, false);
      replies.push(formatTermReply(defined));
    } catch {
      // Skip a candidate Claude couldn't cleanly define rather than failing
      // the whole reply over one term out of several.
    }
  }

  return replies.length === 0 ? NO_SLANG_REPLY : formatMultiTermReply(replies);
}

/** Handle `/report <term> [note]`. Synchronous — no Claude call needed. */
export function handleReport(deps: Deps, argsText: string): string {
  const trimmed = argsText.trim();
  if (trimmed === '') {
    return "Usage: /report <term> [why it's wrong]";
  }

  // Terms and aliases can be multi-word ("left no crumbs"), so try the whole
  // argument as the term before falling back to just its first word.
  const wholeMatch = findTerm(deps.db, trimmed);
  if (wholeMatch !== undefined) {
    reportTerm(deps.db, wholeMatch.id, undefined);
    return `Thanks — "${wholeMatch.term}" has been queued for review.`;
  }

  const [firstWord, ...rest] = trimmed.split(/\s+/);
  if (firstWord === undefined) {
    return "Usage: /report <term> [why it's wrong]";
  }
  const stored = findTerm(deps.db, firstWord);
  if (stored === undefined) {
    return `I don't have "${firstWord}" stored, so there's nothing to report.`;
  }
  const note = rest.length > 0 ? rest.join(' ') : undefined;
  reportTerm(deps.db, stored.id, note);
  return `Thanks — "${stored.term}" has been queued for review.`;
}
