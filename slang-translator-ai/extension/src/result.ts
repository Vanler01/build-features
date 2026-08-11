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
    });

    const data = (await response.json()) as { reply?: string; error?: string };
    if (!response.ok) {
      show('reply', data.error ?? 'Lookup failed.', true);
      return;
    }
    show('reply', data.reply ?? 'No answer came back.');
  } catch {
    // The overwhelmingly likely cause, and the one worth naming, is that the
    // local backend is not running — this is a personal-use setup where the
    // server is something you start yourself.
    show('reply', 'Could not reach the local server. Is `npm run serve` running?', true);
  }
}

void main();
