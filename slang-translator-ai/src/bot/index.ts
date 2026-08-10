/** Entrypoint — `npm run dev`. Long polling for local dev per AI_PROJECTS.md. */

import { Bot } from 'grammy';
import { createClient } from '../ai/client.js';
import { loadConfig } from '../config.js';
import { openStore } from '../store/db.js';
import { registerHandlers } from './handlers.js';

function main(): void {
  const config = loadConfig();
  const db = openStore(config.dbPath);
  const client = createClient(config.anthropicApiKey);
  const bot = new Bot(config.telegramBotToken);

  registerHandlers(bot, { db, client });

  process.once('SIGINT', () => void bot.stop());
  process.once('SIGTERM', () => void bot.stop());

  void bot.start();
}

main();
