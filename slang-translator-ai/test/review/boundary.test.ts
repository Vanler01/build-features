/**
 * The structural half of CLAUDE.md rule 2.
 *
 * The behavioural test (bot lookups never flip `verified`) proves the bot does
 * not promote anything today. It would still pass if someone imported
 * `verifyTerm` into a handler and left it one call away. This asserts the
 * boundary itself: promotion is a human action, so the code that performs it
 * must stay unreachable from the message path.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = fileURLToPath(new URL('../../src/', import.meta.url));

function filesUnder(dir: string): string[] {
  return readdirSync(join(SRC, dir), { withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith('.ts'))
    .map((e) => join(SRC, dir, e.name));
}

describe('the bot path cannot reach the promotion code', () => {
  it('no module under bot/, ai/, store/ or server/ imports from review/', () => {
    const offenders: string[] = [];
    for (const dir of ['bot', 'ai', 'store', 'server']) {
      for (const file of filesUnder(dir)) {
        const source = readFileSync(file, 'utf8');
        if (/from\s+['"][^'"]*review\//.test(source)) offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('review/ is the only place that writes verified = 1', () => {
    const offenders: string[] = [];
    for (const dir of ['bot', 'ai', 'store', 'server']) {
      for (const file of filesUnder(dir)) {
        const source = readFileSync(file, 'utf8');
        // `verified = ?` in the seed loader's INSERT is bound from an
        // already-validated Term, so only a literal 1 is a promotion.
        if (/verified\s*=\s*1/.test(source)) offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });
});
