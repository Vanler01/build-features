/**
 * The SQLite connection and its migrations.
 *
 * One migration file per schema change, applied in order and recorded — never
 * `CREATE TABLE IF NOT EXISTS` scattered through the code (AI_PROJECTS.md,
 * Data & storage). `:memory:` is what the test suite opens; a real path is
 * what the bot opens.
 */

import Database from 'better-sqlite3';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export type Store = InstanceType<typeof Database>;

const MIGRATIONS_DIR = join(dirname(fileURLToPath(import.meta.url)), 'migrations');

interface MigrationRow {
  readonly id: string;
}

export function openStore(path: string): Store {
  const db = new Database(path);
  migrate(db);
  // Off by default in SQLite; without it ON DELETE CASCADE is silently a no-op.
  // Set *after* migrating — see migrate() for why they must be off during.
  db.pragma('foreign_keys = ON');
  return db;
}

/**
 * Apply pending migrations in filename order, each in its own transaction.
 *
 * Foreign keys are off for the duration, because a migration that alters a
 * CHECK constraint has to rebuild the table (SQLite cannot alter one in
 * place), and `DROP TABLE terms` with foreign keys on performs an implicit
 * DELETE that cascades into senses, aliases and review_queue. The pragma
 * cannot be changed inside a transaction, so it is set around the whole loop
 * rather than per migration. `foreign_key_check` afterwards is what catches a
 * rebuild that left a dangling reference — the enforcement we gave up during
 * the rebuild, applied once at the end instead.
 */
function migrate(db: Store): void {
  db.exec(
    `CREATE TABLE IF NOT EXISTS schema_migrations (
       id TEXT PRIMARY KEY,
       applied_at TEXT NOT NULL
     )`,
  );

  const appliedRows = db.prepare('SELECT id FROM schema_migrations').all() as MigrationRow[];
  const applied = new Set(appliedRows.map((r) => r.id));

  const files = readdirSync(MIGRATIONS_DIR)
    .filter((f) => f.endsWith('.sql'))
    .sort()
    .filter((f) => !applied.has(f));
  if (files.length === 0) return;

  db.pragma('foreign_keys = OFF');
  // Renaming a table while another table's REFERENCES clause points at a table
  // the same migration just dropped makes the modern ALTER TABLE reparse the
  // whole schema and fail. Legacy mode skips that reparse, which is what a
  // rebuild needs.
  db.pragma('legacy_alter_table = ON');
  try {
    for (const file of files) {
      const sql = readFileSync(join(MIGRATIONS_DIR, file), 'utf8');
      db.transaction(() => {
        db.exec(sql);
        db.prepare('INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)').run(
          file,
          new Date().toISOString(),
        );
      })();

      // Per migration, not once at the end: a later migration could otherwise
      // repair a reference an earlier one broke, and the combined check would
      // report clean while a real defect sat in the middle of the sequence.
      const violations = db.pragma('foreign_key_check') as unknown[];
      if (violations.length > 0) {
        throw new Error(
          `migration ${file} left ${violations.length} dangling foreign key reference(s); ` +
            'the database was not left in a usable state',
        );
      }
    }
  } finally {
    db.pragma('legacy_alter_table = OFF');
  }
}
