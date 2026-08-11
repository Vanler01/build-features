/**
 * Rendering an entry for a reviewer's terminal.
 *
 * Split out of cli.ts so it can be tested without importing a module whose
 * side effect is to run the whole CLI.
 */

import type { StoredTerm } from '../store/lookup.js';

/**
 * The review view of one entry.
 *
 * Deliberately shows *both* the stored and the aged confidence. That contrast
 * is what the reviewer is judging: `low → low` means whoever wrote it was
 * already unsure, while `high → low (aged)` means it was trusted once and has
 * merely sat untouched. Those belong in different mental queues, and writing
 * the decayed value back to the database would erase the distinction.
 */
export function formatEntry(entry: StoredTerm): string {
  const status = entry.verified
    ? `verified by ${entry.verifiedBy ?? 'unknown'}${
        entry.verifiedAt === undefined ? '' : ` on ${entry.verifiedAt.slice(0, 10)}`
      }`
    : 'UNVERIFIED';

  const lines = [
    `${entry.term}  [${status}]`,
    `  source: ${entry.source}   register: ${entry.register}`,
    entry.aliases.length === 0 ? '  aliases: —' : `  aliases: ${entry.aliases.join(', ')}`,
  ];

  entry.senses.forEach((sense, i) => {
    const flags = sense.contentFlags.length === 0 ? '' : ` [${sense.contentFlags.join(', ')}]`;
    const decayed =
      sense.effectiveConfidence === sense.confidence
        ? sense.confidence
        : `${sense.confidence} → ${sense.effectiveConfidence} (aged)`;

    // Region belongs in the reviewer's view for the same reason it belongs in
    // the reply: an unmarked sense claims nothing, so a marked one has to be
    // visibly marked or the reviewer is judging a different entry from the one
    // stored. It also became possible to *set* this from the CLI, and a field
    // you can change but not see is a field you will change by accident.
    const region = sense.region === undefined ? '' : ` (${sense.region})`;
    lines.push(`  ${i + 1}.${flags} ${sense.definition}${region}`);
    // A slur with a stored example is a rule 11 violation that got past the
    // validator somehow. The reviewer is the last person who can catch it
    // before `verify` freezes it into a confirmed row, so this says so loudly
    // rather than printing the example as though it belonged there.
    if (sense.example !== undefined && sense.contentFlags.includes('slur')) {
      lines.push('     !! POLICY VIOLATION: a slur must carry no usage example.');
      lines.push('        Remove it before verifying this entry.');
    } else if (sense.example !== undefined) {
      // Curly, matching the bot reply — a dialogue example carrying its own
      // straight quotes must not blur into the wrapper.
      lines.push(`     e.g. “${sense.example}”`);
    }
    lines.push(`     confidence: ${decayed}   last seen: ${sense.lastSeen.slice(0, 10)}`);
  });

  return lines.join('\n');
}
