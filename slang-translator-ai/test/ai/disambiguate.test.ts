/**
 * Sense disambiguation, with the Anthropic client mocked. Covers the sense
 * cases AGENTS.md requires: a term with several senses must return the
 * contextually-correct one, not just any valid index.
 */

import { describe, expect, it, vi } from 'vitest';
import type Anthropic from '@anthropic-ai/sdk';
import { disambiguateSense } from '../../src/ai/disambiguate.js';
import { AiError } from '../../src/ai/errors.js';
import type { Sense } from '../../src/store/types.js';

const CAP_SENSES: Sense[] = [
  { definition: 'A lie, or exaggeration.', confidence: 'high', contentFlags: [] },
  { definition: 'A hat.', confidence: 'medium', contentFlags: [] },
  { definition: 'An upper limit.', confidence: 'medium', contentFlags: [] },
];

function fakeClient(input: unknown): Anthropic {
  const create = vi.fn().mockResolvedValue({
    stop_reason: 'tool_use',
    content: [{ type: 'tool_use', id: 'tu_1', name: 'disambiguate_sense', input }],
  });
  return { messages: { create } } as unknown as Anthropic;
}

describe('disambiguateSense', () => {
  it('returns the index Claude picks', async () => {
    const client = fakeClient({ sense_index: 0 });
    const index = await disambiguateSense(client, 'cap', CAP_SENSES, "that's cap");
    expect(index).toBe(0);
  });

  it('picks the hat sense for hat context', async () => {
    const client = fakeClient({ sense_index: 1 });
    const index = await disambiguateSense(client, 'cap', CAP_SENSES, 'nice cap you got there');
    expect(index).toBe(1);
  });

  it('refuses an out-of-range index', async () => {
    const client = fakeClient({ sense_index: 99 });
    await expect(disambiguateSense(client, 'cap', CAP_SENSES, 'x')).rejects.toThrow(AiError);
  });

  it('refuses to call Claude when there is only one sense', async () => {
    const client = fakeClient({ sense_index: 0 });
    const [onlySense] = CAP_SENSES;
    if (onlySense === undefined) throw new Error('fixture is empty');
    await expect(disambiguateSense(client, 'x', [onlySense], 'x')).rejects.toThrow(AiError);
    expect(client.messages.create).not.toHaveBeenCalled();
  });
});
