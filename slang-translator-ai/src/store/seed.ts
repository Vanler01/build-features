/**
 * Reading and validating the seed vocabulary.
 *
 * The validator's job is to refuse dishonest data before it reaches the store,
 * because once an entry is in and marked verified nothing downstream can tell
 * it from something a person actually checked.
 *
 * The rule that matters most: **a model-authored entry may not arrive
 * verified**. The seed shipped with this project was written by Claude, not by
 * a person, so it is `source: 'claude'` and `verified: false` — and it stays
 * that way until somebody reads it. Labelling it `manual_seed` would have been
 * the convenient lie.
 */

import { readFileSync } from 'node:fs';
import type { ContentFlag, Register, Sense, Source, Term } from './types.js';

const SOURCES: readonly Source[] = ['manual_seed', 'claude', 'user_report'];
const REGISTERS: readonly Register[] = ['genz', 'genalpha', 'both'];
const FLAGS: readonly ContentFlag[] = ['sexual', 'vulgar', 'slur', 'violent'];
const CONFIDENCES = ['high', 'medium', 'low'] as const;

/** A seed entry that cannot be trusted, with a message naming why. */
export class SeedError extends Error {}

/** What a load found, including what still needs a human. */
export interface SeedReport {
  readonly terms: number;
  readonly senses: number;
  readonly unverified: readonly string[];
}

function fail(term: string, message: string): never {
  throw new SeedError(`${term}: ${message}`);
}

function parseSense(term: string, raw: unknown): Sense {
  if (typeof raw !== 'object' || raw === null) fail(term, 'sense must be an object');
  const r = raw as Record<string, unknown>;

  const definition = r['definition'];
  if (typeof definition !== 'string' || definition.trim() === '') {
    fail(term, 'sense needs a definition');
  }

  const confidence = r['confidence'];
  if (!CONFIDENCES.includes(confidence as (typeof CONFIDENCES)[number])) {
    fail(term, `confidence must be one of ${CONFIDENCES.join(', ')}`);
  }

  const flagsRaw = r['content_flags'];
  if (!Array.isArray(flagsRaw)) fail(term, 'content_flags must be an array');
  const contentFlags = flagsRaw.map((f) => {
    if (!FLAGS.includes(f as ContentFlag)) fail(term, `unknown content flag: ${String(f)}`);
    return f as ContentFlag;
  });

  const example = r['example'];
  if (example !== undefined && typeof example !== 'string') {
    fail(term, 'example must be a string when present');
  }

  // The one hard content rule: an example models using the word, which is
  // exactly what must not happen for a slur. Enforced here rather than left to
  // whoever writes the reply, because this is where it can actually be caught.
  if (contentFlags.includes('slur') && example !== undefined) {
    fail(term, 'a slur must not carry a usage example');
  }

  return {
    definition,
    confidence: confidence as Sense['confidence'],
    contentFlags,
    ...(example === undefined ? {} : { example }),
  };
}

/** Parse and validate one entry, or throw `SeedError`. */
export function parseTerm(raw: unknown): Term {
  if (typeof raw !== 'object' || raw === null) throw new SeedError('entry must be an object');
  const r = raw as Record<string, unknown>;

  const term = r['term'];
  if (typeof term !== 'string' || term.trim() === '') throw new SeedError('entry needs a term');

  const source = r['source'];
  if (!SOURCES.includes(source as Source)) {
    fail(term, `source must be one of ${SOURCES.join(', ')} — never a generic value`);
  }

  const verified = r['verified'];
  if (typeof verified !== 'boolean') fail(term, 'verified must be a boolean');

  // The check this module exists for. A model-authored entry arriving verified
  // means somebody has laundered a guess into a fact.
  if (source === 'claude' && verified) {
    fail(term, 'a claude-sourced entry cannot ship verified — a person must confirm it');
  }

  const register = r['register'];
  if (!REGISTERS.includes(register as Register)) {
    fail(term, `register must be one of ${REGISTERS.join(', ')}`);
  }

  const sensesRaw = r['senses'];
  if (!Array.isArray(sensesRaw) || sensesRaw.length === 0) {
    fail(term, 'a term needs at least one sense');
  }

  const aliasesRaw = r['aliases'] ?? [];
  if (!Array.isArray(aliasesRaw)) fail(term, 'aliases must be an array');

  return {
    term,
    aliases: aliasesRaw.map(String),
    register: register as Register,
    senses: sensesRaw.map((s) => parseSense(term, s)),
    source: source as Source,
    verified,
  };
}

/** Read and validate the whole seed file. */
export function loadSeed(path: string): Term[] {
  const raw: unknown = JSON.parse(readFileSync(path, 'utf8'));
  if (!Array.isArray(raw)) throw new SeedError('seed file must contain an array');

  const terms = raw.map(parseTerm);

  const seen = new Set<string>();
  for (const t of terms) {
    const key = t.term.toLowerCase();
    if (seen.has(key)) throw new SeedError(`duplicate term: ${t.term}`);
    seen.add(key);
  }
  return terms;
}

/** Summarise a loaded seed, including what still needs review. */
export function report(terms: readonly Term[]): SeedReport {
  return {
    terms: terms.length,
    senses: terms.reduce((n, t) => n + t.senses.length, 0),
    unverified: terms.filter((t) => !t.verified).map((t) => t.term),
  };
}
