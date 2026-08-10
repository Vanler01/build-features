/**
 * The Anthropic client and the models each Claude call uses.
 *
 * Per AI_PROJECTS.md: Sonnet for parsing/generation, Haiku for high-volume
 * cheap classification passes — slang detection and sense disambiguation are
 * both classification, definition is generation.
 */

import Anthropic from '@anthropic-ai/sdk';

export function createClient(apiKey: string): Anthropic {
  return new Anthropic({ apiKey });
}

export const DETECT_MODEL = 'claude-haiku-4-5';
export const DEFINE_MODEL = 'claude-sonnet-5';
export const DISAMBIGUATE_MODEL = 'claude-haiku-4-5';
