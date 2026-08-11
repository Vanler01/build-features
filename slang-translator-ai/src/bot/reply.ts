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

/**
 * Where a meaning holds, when it does not hold everywhere.
 *
 * Unmarked senses say nothing rather than claiming to be universal. A reader
 * met this word somewhere specific, and "this is the UK meaning" is often the
 * whole answer to why it did not make sense to them.
 */
function regionSuffix(sense: StoredSense): string {
  return sense.region === undefined ? '' : ` (${sense.region})`;
}

function confidenceSuffix(sense: StoredSense): string {
  // REQUIREMENTS §2: a low-confidence read says so, rather than presenting a
  // guess with the same certainty as a checked definition. The *effective*
  // confidence, not the stored one — an entry written down as "high" a year
  // ago and untouched since is no longer a high-confidence answer, and the
  // reader is the person who most needs to know that (CLAUDE.md rule 4).
  if (sense.effectiveConfidence !== 'low') return '';

  // Two different things reach "low", and they ask the reader for opposite
  // responses: an entry nobody was ever sure of means distrust the definition
  // as written, while an entry that was confident and has since gone stale
  // means the definition was probably right and the *term* may have moved.
  // Saying "not fully sure" for both is the ambiguity rule 13 exists to
  // prevent, and it reads worst for the second-language reader who cannot
  // infer which one is meant.
  return sense.confidence === 'low'
    ? ' (not fully sure about this one)'
    : ' (this definition may be out of date)';
}

/**
 * Says so when no person has confirmed the entry — AI_PROJECTS.md rule 4,
 * "every Claude answer that could be wrong is labeled".
 *
 * Without this, a definition Claude wrote an hour ago and nobody has read is
 * indistinguishable from one a person checked, for the ninety days it takes
 * decay to say anything. The whole store — `verified`, the review queue, the
 * sweeps — exists to track that difference, and this is the one place the
 * reader who would act on it ever sees it.
 *
 * Keyed on `verified` alone rather than on `source === 'claude'`: an
 * unconfirmed entry is unconfirmed whatever wrote it, and the wording is true
 * either way. Today every entry is claude-sourced, so the two agree.
 */
function reviewSuffix(term: StoredTerm): string {
  return term.verified ? '' : ' (not yet reviewed)';
}

function formatSense(term: string, sense: StoredSense): string {
  // Rule 11, the one hard content rule: an example models using the word, and
  // a slur must never carry one. `parseSense` already refuses to store such an
  // entry, so this is the second lock rather than the first — but it is the
  // one on the door the reader is standing at, and a row that arrives by
  // migration, fixture or a future write path bypasses the validator entirely.
  const showExample = sense.example !== undefined && !sense.contentFlags.includes('slur');
  // Curly quotes around the example, straight quotes around the term. Not
  // decoration: the two are doing different jobs. The term is being *mentioned*
  // ("bet" is the word we are defining), while the example is *quoted speech*.
  // Wrapping both in the same straight quote turned a dialogue example into
  // ""Meet at 7?" "Bet."", where the reader cannot see where the example
  // starts. Nesting straight inside curly is what typography does with a
  // quote inside a quote, and it leaves the 21 seed examples containing
  // apostrophes completely untouched.
  const example = showExample ? ` “${sense.example ?? ''}”` : '';
  // Region sits with the definition it qualifies, before the example, so the
  // example reads as an instance of *that* regional use.
  return (
    `${flagPrefix(sense)}"${term}" = ${sense.definition}${regionSuffix(sense)}` +
    `${example}${confidenceSuffix(sense)}`
  );
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
    return `${formatSense(term.term, only)}${reviewSuffix(term)}`;
  }

  const index = leadIndex ?? 0;
  const lead = senses[index];
  if (lead === undefined) {
    throw new Error(`formatTermReply: lead index ${index} out of range for "${term.term}"`);
  }
  // Flags travel with every sense, not just the lead one. Rule 12 says the
  // flag sits beside the definition; it says nothing about only the first.
  // Dropping them here meant a term whose *secondary* sense is a slur showed
  // that sense unflagged — and a bare-term lookup (which the extension always
  // is) has no lead index, so the flagged sense was never the one that got its
  // flag shown.
  const others = senses
    .filter((_, i) => i !== index)
    .map((s) => `${flagPrefix(s)}${s.definition}${regionSuffix(s)}`);
  // The label sits on the lead line, not after "(also: …)" — it qualifies the
  // whole entry, and trailing it after the alternates would read as though it
  // applied only to those.
  return `${formatSense(term.term, lead)}${reviewSuffix(term)}\n(also: ${others.join(' · ')})`;
}

/** Join per-term replies for a message that contained more than one slang term. */
export function formatMultiTermReply(replies: readonly string[]): string {
  return replies.join('\n\n');
}
