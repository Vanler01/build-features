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
import { handleRequest, MAX_SELECTION_CHARS } from './api.js';

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
    if (size > MAX_BODY_BYTES) return undefined;
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
      const body = await readBody(req);
      const origin = req.headers.origin;
      const path = new URL(req.url ?? '/', `http://${HOST}`).pathname;

      const response =
        body === undefined
          ? {
              status: 413,
              headers: { 'Content-Type': 'application/json' },
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
    })();
  });

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
