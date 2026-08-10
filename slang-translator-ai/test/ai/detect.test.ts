/**
 * Slang detection, with the Anthropic client mocked — no network call is
 * permitted in any test (AGENTS.md testing rules). The precision cases here
 * are mandatory: over-flagging is the failure mode that kills this product.
 */

import { describe, expect, it, vi } from 'vitest';
import type Anthropic from '@anthropic-ai/sdk';
import { detectSlang } from '../../src/ai/detect.js';
import { AiError } from '../../src/ai/errors.js';

function fakeClient(input: unknown, stopReason = 'tool_use'): Anthropic {
  const create = vi.fn().mockResolvedValue({
    stop_reason: stopReason,
    content: [{ type: 'tool_use', id: 'tu_1', name: 'detected_slang', input }],
  });
  return { messages: { create } } as unknown as Anthropic;
}

describe('detectSlang', () => {
  it('returns the terms Claude reports', async () => {
    const client = fakeClient({ terms: ['bet', 'cap'] });
    await expect(detectSlang(client, 'no cap, bet')).resolves.toEqual(['bet', 'cap']);
  });

  it('returns an empty array when the message has no slang — a valid answer', async () => {
    const client = fakeClient({ terms: [] });
    await expect(detectSlang(client, "I'll bet you £5 it rains")).resolves.toEqual([]);
  });

  it('normalises and deduplicates returned terms', async () => {
    const client = fakeClient({ terms: ['  No Cap ', 'no cap', 'Bet'] });
    await expect(detectSlang(client, 'x')).resolves.toEqual(['no cap', 'bet']);
  });

  it('rejects a non-array terms field', async () => {
    const client = fakeClient({ terms: 'bet' });
    await expect(detectSlang(client, 'x')).rejects.toThrow(AiError);
  });

  it('rejects a response that never called the tool', async () => {
    const client = fakeClient({ terms: [] }, 'end_turn');
    await expect(detectSlang(client, 'x')).rejects.toThrow(/stop_reason/);
  });
});
