/**
 * The Anthropic client and the models each Claude call uses.
 *
 * Per AI_PROJECTS.md: Sonnet for parsing/generation, Haiku for high-volume
 * cheap classification passes — slang detection and sense disambiguation are
 * both classification, definition is generation.
 */

import Anthropic from '@anthropic-ai/sdk';

/**
 * How long to wait on Claude before giving up.
 *
 * The SDK's default is ten minutes, which is sized for long generations and
 * is absurd for this: every call here is a short classification or a
 * one-paragraph definition against a 128–1024 token cap. Ten minutes of
 * silence is not patience, it is a browser popup spinning forever and a
 * Telegram user who never gets a reply.
 */
const REQUEST_TIMEOUT_MS = 30_000;

export function createClient(apiKey: string): Anthropic {
  return new Anthropic({ apiKey, timeout: REQUEST_TIMEOUT_MS });
}

export const DETECT_MODEL = 'claude-haiku-4-5';
export const DEFINE_MODEL = 'claude-sonnet-5';
export const DISAMBIGUATE_MODEL = 'claude-haiku-4-5';
