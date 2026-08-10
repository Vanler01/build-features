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

export interface Config {
  readonly telegramBotToken: string;
  readonly anthropicApiKey: string;
  readonly dbPath: string;
}

export function loadConfig(): Config {
  return {
    telegramBotToken: required('TELEGRAM_BOT_TOKEN'),
    anthropicApiKey: required('ANTHROPIC_API_KEY'),
    dbPath: process.env['DB_PATH'] ?? 'data/store.sqlite3',
  };
}
