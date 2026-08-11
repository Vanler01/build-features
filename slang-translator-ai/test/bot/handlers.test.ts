/**
 * Reply chunking.
 *
 * Telegram rejects an over-long message outright rather than truncating it,
 * so the failure this guards against is the user receiving *nothing*.
 */

import { describe, expect, it } from 'vitest';
import { chunkReply } from '../../src/bot/handlers.js';

describe('chunkReply', () => {
  it('leaves a short reply as a single message', () => {
    expect(chunkReply('"rizz" = charisma.')).toEqual(['"rizz" = charisma.']);
  });

  it('splits on the seam between per-term answers', () => {
    const a = `a${'.'.repeat(60)}`;
    const b = `b${'.'.repeat(60)}`;
    const c = `c${'.'.repeat(60)}`;
    const chunks = chunkReply([a, b, c].join('\n\n'), 130);

    expect(chunks.length).toBeGreaterThan(1);
    // No chunk starts or ends mid-answer: each begins with a term's first char.
    for (const chunk of chunks) expect(['a', 'b', 'c']).toContain(chunk[0]);
  });

  it('never emits a chunk over the limit', () => {
    const reply = Array.from({ length: 40 }, (_, i) => `term${i} ${'x'.repeat(200)}`).join('\n\n');
    for (const chunk of chunkReply(reply, 4096)) {
      expect(chunk.length).toBeLessThanOrEqual(4096);
    }
  });

  it('loses nothing — the pieces rejoin to the original', () => {
    const reply = Array.from({ length: 12 }, (_, i) => `term${i} ${'y'.repeat(90)}`).join('\n\n');
    expect(chunkReply(reply, 200).join('\n\n')).toBe(reply);
  });

  it('hard-cuts a single answer that is itself too long, rather than dropping it', () => {
    const monster = 'z'.repeat(500);
    const chunks = chunkReply(monster, 100);
    expect(chunks).toHaveLength(5);
    expect(chunks.join('')).toBe(monster);
  });
});
