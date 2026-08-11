/**
 * `npm run serve` — the local backend for the browser extension.
 *
 * Binds to loopback only. This is a personal-use backend holding a Claude key
 * (REQUIREMENTS §6, CLAUDE.md rule 18); binding 0.0.0.0 would put it on every
 * network the machine joins, which is a different product with different
 * obligations. Sharing it is a decision to make deliberately, not a default
 * that arrives via a bind address.
 */

import { createServer, type IncomingMessage } from 'node:http';
import { createClient } from '../ai/client.js';
import { loadConfig } from '../config.js';
import { openStore } from '../store/db.js';
import { corsHeaders, handleRequest, MAX_SELECTION_CHARS } from './api.js';

const HOST = '127.0.0.1';
const DEFAULT_PORT = 8787;

/** Bytes accepted before a request is refused outright. */
const MAX_BODY_BYTES = 4096;

/** Read a request body, refusing anything implausibly large for one term. */
async function readBody(req: IncomingMessage): Promise<string | undefined> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    const buf = chunk as Buffer;
    size += buf.length;
    if (size > MAX_BODY_BYTES) {
      // Drain rather than break. Leaving the `for await` early makes the
      // iterator destroy the socket, so a keep-alive connection cannot be
      // reused and the caller may never read the 413 we are about to send.
      req.resume();
      return undefined;
    }
    chunks.push(buf);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function main(): void {
  const config = loadConfig();
  const db = openStore(config.dbPath);
  const client = createClient(config.anthropicApiKey);
  const deps = { db, client };

  const port = Number(process.env['SLANG_API_PORT'] ?? DEFAULT_PORT);

  const server = createServer((req, res) => {
    void (async (): Promise<void> => {
      const origin = req.headers.origin;
      const path = new URL(req.url ?? '/', `http://${HOST}`).pathname;

      // Everything is inside this try. Without it, a client that hangs up
      // mid-body makes `for await` in readBody throw "aborted" (ECONNRESET),
      // which rejects this `void`-ed promise with nothing to catch it — and
      // Node turns an unhandled rejection into process death. One aborted
      // connection took the whole server down, needing a manual restart.
      try {
        const body = await readBody(req);

        const response =
          body === undefined
            ? {
                status: 413,
                // CORS headers here too, or the extension sees an opaque CORS
                // failure instead of a readable "too long". Unreachable from
                // the extension today (its 300-char cap is far under
                // MAX_BODY_BYTES even in 4-byte UTF-8), but an error the
                // caller cannot read is not worth leaving in place.
                headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
                body: JSON.stringify({ error: 'selection too long' }),
              }
            : await handleRequest(deps, {
                method: req.method ?? 'GET',
                path,
                origin,
                body,
              });

        res.writeHead(response.status, response.headers);
        res.end(response.body);

        // Outcome only. Never the term — what somebody looks up is exactly the
        // sensitive part (CLAUDE.md rule 19, AI_PROJECTS.md rule 5).
        console.log('%s %s -> %d', req.method, path, response.status);
      } catch (error) {
        // A disconnected client cannot be told anything, and trying to write
        // to its socket throws again. Only answer if the socket is still there.
        if (!res.headersSent && res.writable) {
          res.writeHead(500, { 'Content-Type': 'application/json', ...corsHeaders(origin) });
          res.end(JSON.stringify({ error: 'request failed' }));
        } else {
          res.destroy();
        }
        // The error's own text, never the request's — same rule as above.
        console.log(
          '%s %s -> aborted (%s)',
          req.method,
          path,
          error instanceof Error ? error.message : 'unknown',
        );
      }
    })();
  });

  // A body that starts and never finishes would otherwise sit open until
  // Node's 5-minute default. Nothing legitimate here sends slowly: the only
  // client posts a few hundred bytes from the same machine.
  server.requestTimeout = 15_000;

  server.listen(port, HOST, () => {
    console.log('slang api on http://%s:%d (loopback only)', HOST, port);
    console.log('selections over %d chars are refused', MAX_SELECTION_CHARS);
  });

  const shutdown = (): void => {
    server.close(() => {
      db.close();
      process.exit(0);
    });
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

main();
