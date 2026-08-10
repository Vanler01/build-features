/**
 * grammY wiring. Thin on purpose — the actual logic lives in core.ts so it
 * can be tested without a fake Telegram Context.
 */

import type { Bot } from 'grammy';
import { handleMessage, handleReport, HELP_TEXT, type Deps } from './core.js';

export function registerHandlers(bot: Bot, deps: Deps): void {
  bot.command('help', async (ctx) => {
    await ctx.reply(HELP_TEXT);
  });
  bot.command('start', async (ctx) => {
    await ctx.reply(HELP_TEXT);
  });

  bot.command('report', async (ctx) => {
    await ctx.reply(handleReport(deps, ctx.match));
  });

  // Telegram allows up to 4096 chars per message (AI_PROJECTS.md — never
  // trust update.message.text length); handleMessage doesn't assume short
  // input, so nothing is truncated here.
  bot.on('message:text', async (ctx) => {
    const reply = await handleMessage(deps, ctx.message.text);
    await ctx.reply(reply);
  });

  bot.catch((err) => {
    console.error('slang-bot handler error:', err.error);
  });
}
