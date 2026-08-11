/**
 * Store round-trip: migrations apply, a term written by the Claude path reads
 * back correctly, and a report lands in the review queue. This is the seam
 * most likely to be wrong in a way types alone can't catch — SQL typos,
 * JSON-encoding of content_flags, the boolean-to-0/1 conversion.
 */

import Database from 'better-sqlite3';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import { openStore } from '../../src/store/db.js';
import { findTerm, recordLookup } from '../../src/store/lookup.js';
import { insertTerm, reportTerm, writeClaudeTerm } from '../../src/store/write.js';

function freshStore(): ReturnType<typeof openStore> {
  return openStore(':memory:');
}

const MIGRATIONS_DIR = fileURLToPath(new URL('../../src/store/migrations/', import.meta.url));

const tempDirs: string[] = [];
afterEach(() => {
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/**
 * Build a database at an earlier point in the migration history, the way a
 * store created before a given phase actually looks on disk.
 *
 * Applying the real migration files rather than a hand-written schema is the
 * point: a snapshot copied into the test would drift from the files that ship
 * and stop testing the upgrade anyone actually performs.
 */
function storeAtSchema(...applied: readonly string[]): string {
  const dir = mkdtempSync(join(tmpdir(), 'slang-migrate-'));
  tempDirs.push(dir);
  const path = join(dir, 'store.sqlite3');

  const db = new Database(path);
  db.exec(`CREATE TABLE schema_migrations (id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)`);
  const record = db.prepare('INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)');
  for (const file of applied) {
    db.exec(readFileSync(join(MIGRATIONS_DIR, file), 'utf8'));
    record.run(file, new Date().toISOString());
  }
  db.close();
  return path;
}

const storeAtSchema001 = (): string => storeAtSchema('001_init.sql');

describe('migrations', () => {
  it('applies cleanly and is idempotent on a second open', () => {
    const db = freshStore();
    db.close();
  });

  it('upgrades a 001-era database without losing a single row', () => {
    // The rebuild in 002 drops and recreates `terms`. With foreign keys on,
    // that DROP performs an implicit cascading DELETE and would silently take
    // every sense, alias and queue row with it. This is the test that fails
    // loudly if the runner ever stops disabling them.
    const path = storeAtSchema001();

    const before = new Database(path);
    before.pragma('foreign_keys = ON');
    const termId = Number(
      before
        .prepare(
          `INSERT INTO terms (term, normalised, register, source, verified, first_seen, last_seen)
           VALUES ('cap', 'cap', 'both', 'claude', 0, '2026-01-01', '2026-01-01')`,
        )
        .run().lastInsertRowid,
    );
    before
      .prepare(
        `INSERT INTO senses (term_id, definition, example, confidence, content_flags,
                             first_seen, last_seen)
         VALUES (?, 'A lie.', NULL, 'high', '[]', '2026-01-01', '2026-01-01')`,
      )
      .run(termId);
    before
      .prepare('INSERT INTO aliases (term_id, variant, normalised) VALUES (?, ?, ?)')
      .run(termId, 'no cap', 'no cap');
    before
      .prepare("INSERT INTO review_queue (term_id, reason, queued_at) VALUES (?, 'unverified', ?)")
      .run(termId, '2026-01-01');
    before.close();

    const db = openStore(path);
    const count = (table: string): number =>
      (db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get() as { n: number }).n;

    expect(count('terms')).toBe(1);
    expect(count('senses')).toBe(1);
    expect(count('aliases')).toBe(1);
    expect(count('review_queue')).toBe(1);
    expect(db.pragma('foreign_key_check')).toEqual([]);

    // The child tables still point at the rebuilt parent, so cascade works.
    db.prepare('DELETE FROM terms WHERE id = ?').run(termId);
    expect(count('senses')).toBe(0);
    expect(count('aliases')).toBe(0);
    db.close();
  });

  it('adds the region column to a 002-era database, keeping existing senses', () => {
    // 003 is a plain ADD COLUMN rather than a rebuild, so the risk is not data
    // loss but the upgrade silently not happening — leaving reads that select
    // `region` broken against a real store created before Phase 4.
    const path = storeAtSchema('001_init.sql', '002_verification.sql');

    const before = new Database(path);
    const termId = Number(
      before
        .prepare(
          `INSERT INTO terms (term, normalised, register, source, verified, first_seen, last_seen)
           VALUES ('bare', 'bare', 'both', 'claude', 0, '2026-01-01', '2026-01-01')`,
        )
        .run().lastInsertRowid,
    );
    before
      .prepare(
        `INSERT INTO senses (term_id, definition, example, confidence, content_flags,
                             first_seen, last_seen)
         VALUES (?, 'Very, or a lot of.', NULL, 'high', '[]', '2026-01-01', '2026-01-01')`,
      )
      .run(termId);
    expect(
      before.prepare("SELECT COUNT(*) AS n FROM pragma_table_info('senses') WHERE name = 'region'")
        .get(),
    ).toEqual({ n: 0 });
    before.close();

    const db = openStore(path);
    const hasRegion = db
      .prepare("SELECT COUNT(*) AS n FROM pragma_table_info('senses') WHERE name = 'region'")
      .get() as { n: number };
    expect(hasRegion.n).toBe(1);

    // The pre-existing sense survives and reads as unmarked, not as a claim.
    const found = findTerm(db, 'bare');
    expect(found?.senses).toHaveLength(1);
    expect(found?.senses[0]?.definition).toBe('Very, or a lot of.');
    expect(found?.senses[0]?.region).toBeUndefined();
    db.close();
  });

  it('leaves foreign keys enforced after migrating', () => {
    const db = freshStore();
    expect(db.pragma('foreign_keys', { simple: true })).toBe(1);
    expect(() =>
      db
        .prepare(
          `INSERT INTO senses (term_id, definition, confidence, content_flags,
                               first_seen, last_seen)
           VALUES (9999, 'orphan', 'high', '[]', 'now', 'now')`,
        )
        .run(),
    ).toThrow();
    db.close();
  });
});

describe('the Claude write path', () => {
  it('writes a term as unverified, claude-sourced, and queues it for review', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'yeet',
      register: 'both',
      senses: [
        { definition: 'To throw with force.', confidence: 'medium', contentFlags: [] },
      ],
    });

    const found = findTerm(db, 'yeet');
    if (found === undefined) throw new Error('just-written term not found');
    expect(found.id).toBe(id);
    expect(found.source).toBe('claude');
    expect(found.verified).toBe(false);
    expect(found.senses).toHaveLength(1);
    expect(found.senses[0]?.definition).toBe('To throw with force.');

    const queued = db.prepare('SELECT reason FROM review_queue WHERE term_id = ?').get(id) as
      | { reason: string }
      | undefined;
    expect(queued?.reason).toBe('unverified');
  });

  it('refuses a claude-sourced row from arriving verified, even via raw SQL', () => {
    // The schema-level CHECK is the last line of defence if application code
    // is ever wrong — belt matching the seed validator's suspenders.
    const db = freshStore();
    expect(() =>
      db
        .prepare(
          `INSERT INTO terms (term, normalised, register, source, verified, first_seen, last_seen)
           VALUES ('x', 'x', 'both', 'claude', 1, 'now', 'now')`,
        )
        .run(),
    ).toThrow();
  });
});

describe('lookup', () => {
  it('resolves an alias to its term', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'no cap',
      register: 'both',
      senses: [{ definition: 'Not a lie; for real.', confidence: 'high', contentFlags: [] }],
    });
    db.prepare('INSERT INTO aliases (term_id, variant, normalised) VALUES (?, ?, ?)').run(
      id,
      'nocap',
      'nocap',
    );

    const found = findTerm(db, 'NoCap');
    expect(found?.id).toBe(id);
  });

  it('returns undefined on a genuine miss, not a throw', () => {
    const db = freshStore();
    expect(findTerm(db, 'not a real term')).toBeUndefined();
  });

  it('records only a term id and timestamp, never message text', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'bet',
      register: 'both',
      senses: [{ definition: 'Agreement.', confidence: 'high', contentFlags: [] }],
    });
    recordLookup(db, id, true);

    const row = db.prepare('SELECT * FROM lookups').get() as Record<string, unknown>;
    expect(Object.keys(row).sort()).toEqual(['found_locally', 'id', 'looked_up_at', 'term_id']);
  });
});

describe('reporting', () => {
  it('queues an existing term with reason reported', () => {
    const db = freshStore();
    const id = writeClaudeTerm(db, {
      term: 'mid',
      register: 'both',
      senses: [{ definition: 'Mediocre.', confidence: 'high', contentFlags: [] }],
    });
    reportTerm(db, id, 'this definition is wrong');

    const rows = db.prepare('SELECT reason, note FROM review_queue WHERE term_id = ?').all(id) as {
      reason: string;
      note: string | null;
    }[];
    expect(rows.some((r) => r.reason === 'reported' && r.note === 'this definition is wrong')).toBe(
      true,
    );
  });
});

describe('insertTerm (seed loader path)', () => {
  it('preserves source, verified, senses, and aliases exactly as given', () => {
    const db = freshStore();
    const id = insertTerm(db, {
      term: 'cap',
      aliases: ['no cap', 'nocap'],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [
        { definition: 'A lie.', confidence: 'high', contentFlags: [] },
        { definition: 'A hat.', confidence: 'medium', contentFlags: [] },
      ],
    });

    const found = findTerm(db, 'cap');
    expect(found?.id).toBe(id);
    expect(found?.source).toBe('manual_seed');
    expect(found?.verified).toBe(true);
    expect(found?.senses).toHaveLength(2);
    expect(found?.aliases.slice().sort()).toEqual(['no cap', 'nocap']);

    // The alias resolves too — not just the primary term.
    expect(findTerm(db, 'nocap')?.id).toBe(id);
  });

  it('queues an unverified term for review, same as a live Claude miss would', () => {
    const db = freshStore();
    const id = insertTerm(db, {
      term: 'yeet',
      aliases: [],
      register: 'genz',
      source: 'claude',
      verified: false,
      senses: [{ definition: 'To throw.', confidence: 'high', contentFlags: [] }],
    });
    const queued = db.prepare('SELECT reason FROM review_queue WHERE term_id = ?').get(id) as
      | { reason: string }
      | undefined;
    expect(queued?.reason).toBe('unverified');
  });

  it('does not queue a review entry for an already-verified term', () => {
    const db = freshStore();
    const id = insertTerm(db, {
      term: 'cap',
      aliases: [],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [{ definition: 'A lie.', confidence: 'high', contentFlags: [] }],
    });
    const queued = db.prepare('SELECT 1 FROM review_queue WHERE term_id = ?').get(id);
    expect(queued).toBeUndefined();
  });

  it('resolves a real emoji alias — 🧢 must not normalise away to nothing', () => {
    const db = freshStore();
    const id = insertTerm(db, {
      term: 'cap',
      aliases: ['no cap', 'nocap', '🧢'],
      register: 'both',
      source: 'manual_seed',
      verified: true,
      senses: [{ definition: 'A lie.', confidence: 'high', contentFlags: [] }],
    });
    expect(findTerm(db, '🧢')?.id).toBe(id);
  });
});
