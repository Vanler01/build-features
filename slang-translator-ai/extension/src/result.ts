/**
 * The popup that shows the answer.
 *
 * It holds no API key (CLAUDE.md rule 17) — it asks the local backend, which
 * holds them. It sends the selected term and nothing else: no page URL, no
 * title, no surrounding text, because the background worker never passed it
 * any of those.
 */

/** Must match SLANG_API_PORT in .env, and the loopback bind in server/index.ts. */
const API = 'http://127.0.0.1:8787/lookup';

function show(id: string, text: string, muted = false): void {
  const el = document.getElementById(id);
  if (el === null) return;
  // textContent, never innerHTML: the reply is a definition that can contain
  // any characters, and it is not markup.
  el.textContent = text;
  el.classList.toggle('muted', muted);
}

async function main(): Promise<void> {
  const params = new URLSearchParams(location.search);

  if (params.get('tooLong') === '1') {
    show('term', '');
    show(
      'reply',
      'That selection is too long. Select a word or a sentence — the whole page ' +
        'is never sent anywhere.',
      true,
    );
    return;
  }

  const term = (params.get('q') ?? '').trim();
  if (term === '') {
    show('reply', 'Nothing was selected.', true);
    return;
  }

  show('term', term);

  try {
    const response = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term }),
      // Backstop, slightly longer than the server's own 30s Claude timeout so
      // a real answer normally wins the race. Without it, anything that stops
      // the server mid-request leaves this popup on "Looking it up…" forever,
      // with no way for the reader to tell waiting from broken.
      signal: AbortSignal.timeout(35_000),
    });

    const data = (await response.json()) as { reply?: string; error?: string };
    if (!response.ok) {
      show('reply', data.error ?? 'Lookup failed.', true);
      return;
    }
    show('reply', data.reply ?? 'No answer came back.');
  } catch (error) {
    // Two different failures, and telling them apart is the difference between
    // "go start the server" and "wait and try again". AbortSignal.timeout
    // rejects with a TimeoutError; a dead server rejects with a TypeError.
    const timedOut = error instanceof DOMException && error.name === 'TimeoutError';
    show(
      'reply',
      timedOut
        ? 'The lookup took too long and was given up on. Try again.'
        : 'Could not reach the local server. Is `npm run serve` running?',
      true,
    );
  }
}

void main();
