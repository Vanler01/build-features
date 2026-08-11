/**
 * Reply formatting — REQUIREMENTS §5 (house format) and §8 (flag, don't hide).
 *
 * Pure string formatting, no I/O, so it's testable without a bot or a store.
 */

import type { StoredSense, StoredTerm } from '../store/lookup.js';

/** "Nothing unusual here" is a correct answer (REQUIREMENTS §2), not a fallback apology. */
export const NO_SLANG_REPLY = 'Nothing unusual here — no slang I recognise.';

function flagPrefix(sense: StoredSense): string {
  return sense.contentFlags.length === 0 ? '' : `[${sense.contentFlags.join(', ')}] `;
}

function confidenceSuffix(sense: StoredSense): string {
  // REQUIREMENTS §2: a low-confidence read says so, rather than presenting a
  // guess with the same certainty as a checked definition.
  //
  // The *effective* confidence, not the stored one — an entry written down as
  // "high" a year ago and untouched since is no longer a high-confidence
  // answer, and the reader is the person who most needs to know that
  // (CLAUDE.md rule 4).
  return sense.effectiveConfidence === 'low' ? ' (not fully sure about this one)' : '';
}

function formatSense(term: string, sense: StoredSense): string {
  const example = sense.example === undefined ? '' : ` "${sense.example}"`;
  return `${flagPrefix(sense)}"${term}" = ${sense.definition}${example}${confidenceSuffix(sense)}`;
}

/**
 * Format the reply for one term. `leadIndex` — from sense disambiguation —
 * picks which sense to lead with when there's message context to judge by;
 * the rest are noted in one line. Omit it for a bare-term lookup, where
 * there's no context to disambiguate against, and every sense is shown.
 */
export function formatTermReply(term: StoredTerm, leadIndex?: number): string {
  const { senses } = term;
  if (senses.length === 0) {
    throw new Error(`formatTermReply: "${term.term}" has no senses to report`);
  }

  if (senses.length === 1) {
    const [only] = senses;
    if (only === undefined) throw new Error('unreachable: length checked above');
    return formatSense(term.term, only);
  }

  const index = leadIndex ?? 0;
  const lead = senses[index];
  if (lead === undefined) {
    throw new Error(`formatTermReply: lead index ${index} out of range for "${term.term}"`);
  }
  const others = senses.filter((_, i) => i !== index).map((s) => s.definition);
  return `${formatSense(term.term, lead)}\n(also: ${others.join(' · ')})`;
}

/** Join per-term replies for a message that contained more than one slang term. */
export function formatMultiTermReply(replies: readonly string[]): string {
  return replies.join('\n\n');
}
