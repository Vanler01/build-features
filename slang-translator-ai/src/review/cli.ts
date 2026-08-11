/**
 * `npm run review` — work the review queue.
 *
 * Like the seed loader, this needs neither TELEGRAM_BOT_TOKEN nor
 * ANTHROPIC_API_KEY and so deliberately skips config.ts's loadConfig(): review
 * is an offline, local operation over the store, and it must never be the
 * thing that makes a person put an API key somewhere to run it. It also makes
 * no network calls of any kind — re-verification is a person reading an entry,
 * not a model being asked to grade its own homework.
 */

import { openStore, type Store } from '../store/db.js';
import { addSense, addTerm, editSense, removeSense, type SenseChange } from './edit.js';
import { formatEntry } from './format.js';
import {
  addAlias,
  forReview,
  mostLookedUp,
  pending,
  queueStats,
  rejectTerm,
  sweepDecayed,
  sweepLowConfidence,
  unverifiedCount,
  unverifyTerm,
  verifyTerm,
} from './queue.js';

const USAGE = `Usage: npm run review [command]

  list                      open queue items (default)
  show <term>               full entry: senses, flags, stored vs current confidence
  verify <term> --by <you>  confirm an entry — the only way anything becomes verified
  reject <term>             a human looked and did not confirm it; clears the queue item
  unverify <term>           send a previously verified entry back for another look
  alias <term> = <variant>  record a spelling that should resolve to <term>
  top                       most looked-up terms, and whether they are checked
  sweep                     queue stale and low-confidence entries
  stats                     queue counts

Correcting an entry — sense numbers are the ones "show" prints:

  edit <term> <n> = <definition>    rewrite one sense
  example <term> <n> = <text>       set a usage example; empty text clears it
  flags <term> <n> = vulgar,slur    set content flags; empty clears them
  region <term> <n> = UK            mark where a sense holds; empty clears it
  confidence <term> <n> = medium    high | medium | low
  sense add <term> = <definition>   add a sense to an existing term
  sense rm <term> <n>               remove a sense (never the last one)
  add <term> = <definition> --by <you>   hand-write a new term

Editing never promotes anything to verified, and never rewrites where an entry
came from. Editing an entry that is *already* verified needs --by, because the
name on it belongs to whoever confirmed the old wording.

The reviewer name may also come from SLANG_REVIEWER instead of --by.`;

/** Pull `--by <name>` out of the argument list, returning it and the rest. */
function extractReviewer(args: readonly string[]): { reviewer: string; rest: string[] } {
  const rest: string[] = [];
  let reviewer = process.env['SLANG_REVIEWER'] ?? '';

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === '--by') {
      reviewer = args[i + 1] ?? '';
      i += 1;
      continue;
    }
    if (arg !== undefined) rest.push(arg);
  }
  return { reviewer, rest };
}

/**
 * Split `<term> <n> = <value>` — "edit no cap 1 = honestly, no exaggeration".
 *
 * The sense number is taken as the last token before the `=` rather than the
 * second, because terms are routinely multi-word here and "left no crumbs 1"
 * has to parse the same way "cap 1" does. Everything after the first `=` is
 * the value, so a definition may contain one.
 */
function parseSenseTarget(
  command: string,
  target: string,
): { term: string; senseNumber: number; value: string } {
  const eq = target.indexOf('=');
  if (eq === -1) {
    throw new Error(`Usage: npm run review -- ${command} <term> <n> = <value>`);
  }
  const tokens = target.slice(0, eq).trim().split(/\s+/).filter(Boolean);
  const senseNumber = Number(tokens.pop());
  const term = tokens.join(' ');
  if (term === '' || !Number.isInteger(senseNumber) || senseNumber < 1) {
    throw new Error(`Usage: npm run review -- ${command} <term> <n> = <value>`);
  }
  return { term, senseNumber, value: target.slice(eq + 1).trim() };
}

/** Split `<term> <n>` for the commands that take no value, like `sense rm`. */
function parseTermAndNumber(
  command: string,
  target: string,
): { term: string; senseNumber: number } {
  const tokens = target.trim().split(/\s+/).filter(Boolean);
  const senseNumber = Number(tokens.pop());
  const term = tokens.join(' ');
  if (term === '' || !Number.isInteger(senseNumber) || senseNumber < 1) {
    throw new Error(`Usage: npm run review -- ${command} <term> <n>`);
  }
  return { term, senseNumber };
}

/** Apply one field change and show the entry back, so the result is visible. */
function cmdEdit(
  db: Store,
  command: string,
  target: string,
  reviewer: string,
  toChange: (value: string) => SenseChange,
): void {
  const { term, senseNumber, value } = parseSenseTarget(command, target);
  console.log(formatEntry(editSense(db, term, senseNumber, toChange(value), reviewer)));
}

function cmdList(db: Store): void {
  const items = pending(db);
  if (items.length === 0) {
    console.log('Queue is empty.');
    return;
  }
  console.log(`${items.length} open item(s), most-asked-for first:\n`);
  for (const item of items) {
    const note = item.note === undefined ? '' : ` — ${item.note}`;
    const asked = item.lookupCount === 0 ? '' : ` (${item.lookupCount}×)`;
    console.log(`  [${item.reason}] ${item.term}${asked}${note}`);
  }
  console.log(`\n${unverifiedCount(db)} term(s) unverified overall.`);
}

function cmdTop(db: Store): void {
  const rows = mostLookedUp(db);
  if (rows.length === 0) {
    console.log('Nothing has been looked up yet.');
    return;
  }
  console.log('Most looked-up terms:\n');
  for (const row of rows) {
    // An unverified term at the top of this list is the highest-value review
    // in the store — it is the one being served most often unchecked.
    console.log(
      `  ${String(row.lookups).padStart(5)}×  ${row.term}${row.verified ? '' : '  ← unverified'}`,
    );
  }
}

function cmdShow(db: Store, term: string): void {
  const entry = forReview(db, term);
  if (entry === undefined) {
    console.error(`No term matching "${term}".`);
    process.exitCode = 1;
    return;
  }
  console.log(formatEntry(entry));
}

function cmdStats(db: Store): void {
  const stats = queueStats(db);
  console.log(`reported:   ${stats.reported}`);
  console.log(`decayed:    ${stats.decayed}`);
  console.log(`unverified: ${stats.unverified}`);
  console.log(`\n${unverifiedCount(db)} term(s) unverified overall.`);
}

function cmdSweep(db: Store): void {
  const stale = sweepDecayed(db);
  const lowConfidence = sweepLowConfidence(db);
  console.log(`queued ${stale} stale entr(ies) and ${lowConfidence} low-confidence entr(ies).`);
}

function main(): void {
  const argv = process.argv.slice(2);
  const { reviewer, rest } = extractReviewer(argv);
  const [command = 'list', ...operands] = rest;
  const target = operands.join(' ').trim();

  const db = openStore(process.env['DB_PATH'] ?? 'data/store.sqlite3');
  try {
    switch (command) {
      case 'list':
        cmdList(db);
        break;
      case 'show':
        if (target === '') throw new Error('show needs a term');
        cmdShow(db, target);
        break;
      case 'verify': {
        if (target === '') throw new Error('verify needs a term');
        // `npm run review verify x --by you` silently loses the flag to npm
        // itself, which then looks like "you didn't give a name" when you did.
        // Name the actual fix rather than letting people guess at it.
        if (reviewer.trim() === '') {
          throw new Error(
            'verify needs a reviewer name.\n' +
              '  npm run review -- verify <term> --by <you>   (note the --)\n' +
              '  SLANG_REVIEWER=<you> npm run review verify <term>',
          );
        }
        const outcome = verifyTerm(db, target, reviewer);
        console.log(
          `"${outcome.term}" verified by ${reviewer.trim()}; ` +
            `${outcome.itemsResolved} queue item(s) closed.`,
        );
        break;
      }
      case 'reject': {
        if (target === '') throw new Error('reject needs a term');
        const outcome = rejectTerm(db, target);
        console.log(
          `"${outcome.term}" left unverified; ${outcome.itemsResolved} queue item(s) closed.`,
        );
        break;
      }
      case 'unverify': {
        if (target === '') throw new Error('unverify needs a term');
        const outcome = unverifyTerm(db, target);
        console.log(`"${outcome.term}" sent back for review.`);
        break;
      }
      case 'alias': {
        // `alias no cap = nocap` — the `=` is what separates a multi-word term
        // from a multi-word variant, both of which are ordinary here.
        const [termPart, variantPart, ...extra] = target.split('=');
        if (variantPart === undefined || extra.length > 0) {
          throw new Error('Usage: npm run review -- alias <term> = <variant>');
        }
        const outcome = addAlias(db, termPart?.trim() ?? '', variantPart.trim());
        console.log(`"${variantPart.trim()}" now resolves to "${outcome.term}".`);
        break;
      }
      case 'edit':
        cmdEdit(db, 'edit', target, reviewer, (definition) => ({ definition }));
        break;
      case 'example':
        // An empty right-hand side clears it. That is the fix for a slur that
        // arrived carrying a usage example, so it has to be reachable.
        cmdEdit(db, 'example', target, reviewer, (v) => ({ example: v === '' ? null : v }));
        break;
      case 'flags':
        cmdEdit(db, 'flags', target, reviewer, (v) => ({
          contentFlags: v.split(',').map((f) => f.trim()).filter((f) => f !== ''),
        }));
        break;
      case 'region':
        cmdEdit(db, 'region', target, reviewer, (v) => ({ region: v === '' ? null : v }));
        break;
      case 'confidence':
        cmdEdit(db, 'confidence', target, reviewer, (confidence) => ({ confidence }));
        break;
      case 'sense': {
        const [sub = '', ...rest2] = target.split(/\s+/);
        const remainder = rest2.join(' ');
        if (sub === 'add') {
          const eq = remainder.indexOf('=');
          if (eq === -1) {
            throw new Error('Usage: npm run review -- sense add <term> = <definition>');
          }
          const entry = addSense(
            db,
            remainder.slice(0, eq).trim(),
            remainder.slice(eq + 1).trim(),
            reviewer,
          );
          console.log(formatEntry(entry));
          break;
        }
        if (sub === 'rm') {
          const { term, senseNumber } = parseTermAndNumber('sense rm', remainder);
          console.log(formatEntry(removeSense(db, term, senseNumber, reviewer)));
          break;
        }
        throw new Error('Usage: npm run review -- sense add|rm ...');
      }
      case 'add': {
        const eq = target.indexOf('=');
        if (eq === -1) {
          throw new Error('Usage: npm run review -- add <term> = <definition> --by <you>');
        }
        const name = target.slice(0, eq).trim();
        const entry = addTerm(db, name, target.slice(eq + 1).trim(), reviewer);
        console.log(`"${entry.term}" added and verified by ${reviewer.trim()}.\n`);
        console.log(formatEntry(entry));
        break;
      }
      case 'top':
        cmdTop(db);
        break;
      case 'sweep':
        cmdSweep(db);
        break;
      case 'stats':
        cmdStats(db);
        break;
      default:
        console.log(USAGE);
        process.exitCode = 1;
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  } finally {
    db.close();
  }
}

main();
