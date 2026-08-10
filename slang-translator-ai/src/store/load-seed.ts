/**
 * `npm run seed` — load data/seed.json into the store.
 *
 * Idempotent: a term already present (by normalised form) is left alone
 * rather than duplicated or overwritten, so this is safe to re-run after the
 * seed file grows. It does not need TELEGRAM_BOT_TOKEN or ANTHROPIC_API_KEY,
 * so it deliberately doesn't go through config.ts's full loadConfig().
 */

import { openStore } from './db.js';
import { loadSeed, report } from './seed.js';
import { normalise } from './types.js';
import { insertTerm } from './write.js';

function main(): void {
  const dbPath = process.env['DB_PATH'] ?? 'data/store.sqlite3';
  const terms = loadSeed('data/seed.json');
  const db = openStore(dbPath);

  const alreadyPresent = db.prepare('SELECT 1 FROM terms WHERE normalised = ?');
  let inserted = 0;
  for (const term of terms) {
    if (alreadyPresent.get(normalise(term.term)) !== undefined) continue;
    insertTerm(db, term);
    inserted += 1;
  }

  const r = report(terms);
  console.log(`seed: ${inserted} new term(s) inserted, ${terms.length - inserted} already present`);
  console.log(`seed file: ${r.terms} terms, ${r.senses} senses, ${r.unverified.length} unverified`);

  db.close();
}

main();
