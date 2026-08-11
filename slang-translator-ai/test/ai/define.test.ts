/**
 * Definition-on-a-miss, with the Anthropic client mocked. The key property
 * under test: defineTerm reuses the seed validator, so a malformed or
 * content-policy-violating Claude answer is refused the same way a bad seed
 * entry would be — one set of rules, two callers.
 */

import { describe, expect, it, vi } from 'vitest';
import type Anthropic from '@anthropic-ai/sdk';
import { defineTerm } from '../../src/ai/define.js';
import { SeedError } from '../../src/store/seed.js';

function fakeClient(input: unknown): Anthropic {
  const create = vi.fn().mockResolvedValue({
    stop_reason: 'tool_use',
    content: [{ type: 'tool_use', id: 'tu_1', name: 'define_term', input }],
  });
  return { messages: { create } } as unknown as Anthropic;
}

describe('defineTerm', () => {
  it('returns a validated DefinedTerm for a well-formed response', async () => {
    const client = fakeClient({
      register: 'genz',
      senses: [
        {
          definition: 'To throw something with force.',
          example: 'he yeeted the ball',
          confidence: 'medium',
          content_flags: [],
        },
      ],
    });
    const result = await defineTerm(client, 'yeet');
    expect(result.term).toBe('yeet');
    expect(result.register).toBe('genz');
    expect(result.senses).toHaveLength(1);
    expect(result.senses[0]?.confidence).toBe('medium');
  });

  it('carries a region through when Claude marks one', async () => {
    const client = fakeClient({
      register: 'both',
      senses: [
        {
          definition: 'Very, or a lot of.',
          example: 'that queue was bare long',
          confidence: 'high',
          content_flags: [],
          region: 'UK',
        },
      ],
    });
    const result = await defineTerm(client, 'bare');
    expect(result.senses[0]?.region).toBe('UK');
  });

  it('leaves region absent when Claude omits it, rather than inventing one', async () => {
    const client = fakeClient({
      register: 'genz',
      senses: [{ definition: 'Charisma.', confidence: 'high', content_flags: [] }],
    });
    const result = await defineTerm(client, 'rizz');
    expect(result.senses[0]?.region).toBeUndefined();
  });

  it('refuses a slur sense that carries a usage example', async () => {
    // Same rule as the seed validator (CLAUDE.md rule 11), enforced on Claude
    // output the same way it's enforced on the hand-written seed.
    const client = fakeClient({
      register: 'both',
      senses: [
        {
          definition: 'A derogatory term for a group.',
          example: 'someone said it',
          confidence: 'high',
          content_flags: ['slur'],
        },
      ],
    });
    await expect(defineTerm(client, 'x')).rejects.toThrow(SeedError);
  });

  it('refuses an unknown register', async () => {
    const client = fakeClient({
      register: 'millennial',
      senses: [{ definition: 'x', confidence: 'high', content_flags: [] }],
    });
    await expect(defineTerm(client, 'x')).rejects.toThrow(/register must be one of/);
  });

  it('includes surrounding context in the prompt when given', async () => {
    const client = fakeClient({
      register: 'both',
      senses: [{ definition: 'x', confidence: 'low', content_flags: [] }],
    });
    await defineTerm(client, 'rizz', 'he has mad rizz');
    const call = vi.mocked(client.messages.create).mock.calls[0]?.[0] as {
      messages: { content: string }[];
    };
    expect(call.messages[0]?.content).toContain('he has mad rizz');
  });
});
