/**
 * Environment loading. `.env` holds real values and is git-ignored;
 * `.env.example` is the committed contract — see AI_PROJECTS.md, Secrets layout.
 */

import { existsSync } from 'node:fs';

if (existsSync('.env')) {
  process.loadEnvFile('.env');
}

function required(name: string): string {
  const value = process.env[name];
  if (value === undefined || value === '') {
    throw new Error(`missing required env var: ${name} (see .env.example)`);
  }
  return value;
}

/**
 * Claude calls allowed per UTC day when `SLANG_DAILY_CALL_LIMIT` is unset.
 *
 * A real ceiling rather than a nominal one: a personal dictionary that misses
 * 200 times in a day is a loop, not a person reading. It exists so that a bug
 * costs an afternoon of lookups instead of a bill.
 */
const DEFAULT_DAILY_CALL_LIMIT = 200;

export interface Config {
  readonly telegramBotToken: string;
  readonly anthropicApiKey: string;
  readonly dbPath: string;
  /** `undefined` means uncapped — only an explicit "none" gets that. */
  readonly dailyCallLimit: number | undefined;
}

/**
 * Read the daily ceiling.
 *
 * "none" is the only way to run without one, and it has to be typed. An unset
 * variable gets the default rather than infinity, because the failure this
 * guards against — a loop against a local backend — is most likely on a
 * machine nobody has configured carefully.
 */
function readDailyCallLimit(): number | undefined {
  const raw = process.env['SLANG_DAILY_CALL_LIMIT'];
  if (raw === undefined || raw.trim() === '') return DEFAULT_DAILY_CALL_LIMIT;
  if (raw.trim().toLowerCase() === 'none') return undefined;

  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(
      `SLANG_DAILY_CALL_LIMIT must be a non-negative whole number or "none", got "${raw}"`,
    );
  }
  return parsed;
}

export function loadConfig(): Config {
  return {
    telegramBotToken: required('TELEGRAM_BOT_TOKEN'),
    anthropicApiKey: required('ANTHROPIC_API_KEY'),
    dbPath: process.env['DB_PATH'] ?? 'data/store.sqlite3',
    dailyCallLimit: readDailyCallLimit(),
  };
}
