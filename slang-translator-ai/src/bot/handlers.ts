/**
 * grammY wiring. Thin on purpose — the actual logic lives in core.ts so it
 * can be tested without a fake Telegram Context.
 */

import type { Bot } from 'grammy';
import { handleMessage, handleReport, HELP_TEXT, type Deps } from './core.js';

/** Telegram rejects anything longer than this, and rejects the whole message. */
const TELEGRAM_MAX_CHARS = 4096;

/**
 * Split a reply into Telegram-sized pieces, preferring the seams between
 * per-term answers.
 *
 * A message naming several multi-sense terms can exceed the limit, and
 * Telegram's response to an over-long message is to reject it outright — the
 * user gets *nothing*, which is a worse failure than being told less. Splitting
 * on the blank line that `formatMultiTermReply` puts between terms keeps each
 * piece a whole answer wherever possible.
 */
export function chunkReply(reply: string, limit = TELEGRAM_MAX_CHARS): string[] {
  if (reply.length <= limit) return [reply];

  const chunks: string[] = [];
  let current = '';
  for (const block of reply.split('\n\n')) {
    const candidate = current === '' ? block : `${current}\n\n${block}`;
    if (candidate.length <= limit) {
      current = candidate;
      continue;
    }
    if (current !== '') chunks.push(current);
    // A single block over the limit has no seam to use; cut it hard rather
    // than drop it. One definition this long is already pathological.
    if (block.length > limit) {
      for (let i = 0; i < block.length; i += limit) chunks.push(block.slice(i, i + limit));
      current = '';
    } else {
      current = block;
    }
  }
  if (current !== '') chunks.push(current);
  return chunks;
}

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
  // trust update.message.text length). That applies to the reply as well as
  // the input: several multi-sense terms in one message can exceed it, and
  // Telegram rejects an over-long message whole, so the user would get
  // nothing at all.
  bot.on('message:text', async (ctx) => {
    const reply = await handleMessage(deps, ctx.message.text);
    for (const chunk of chunkReply(reply)) {
      await ctx.reply(chunk);
    }
  });

  bot.catch((err) => {
    console.error('slang-bot handler error:', err.error);
  });
}
