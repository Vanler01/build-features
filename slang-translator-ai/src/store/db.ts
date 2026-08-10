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
  // Off by default in SQLite; without it ON DELETE CASCADE is silently a no-op.
  db.pragma('foreign_keys = ON');
  migrate(db);
  return db;
}

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
    .sort();

  for (const file of files) {
    if (applied.has(file)) continue;
    const sql = readFileSync(join(MIGRATIONS_DIR, file), 'utf8');
    db.transaction(() => {
      db.exec(sql);
      db.prepare('INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)').run(
        file,
        new Date().toISOString(),
      );
    })();
  }
}
