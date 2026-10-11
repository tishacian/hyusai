/**
 * Static server for the production bundle, with SPA fallback.
 *
 * The Playwright contract spec is fully mocked, so it only needs the built
 * app to be reachable; `ng serve` costs a ten-minute rebuild we cannot
 * afford on this machine. `reuseExistingServer` in playwright.config.ts
 * makes this a drop-in replacement.
 */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';

const ROOT = new URL('../dist/agentium/browser/', import.meta.url).pathname;
const PORT = Number(process.env['PORT'] ?? 4200);

const TYPES = {
  '.js': 'text/javascript',
  '.mjs': 'text/javascript',
  '.css': 'text/css',
  '.html': 'text/html',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
};

const send = (res, body, type) => {
  res.writeHead(200, { 'content-type': type, 'cache-control': 'no-store' });
  res.end(body);
};

createServer(async (req, res) => {
  const path = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname));
  try {
    const body = await readFile(join(ROOT, path));
    send(res, body, TYPES[extname(path)] ?? 'application/octet-stream');
  } catch {
    try {
      send(res, await readFile(join(ROOT, 'index.html')), 'text/html');
    } catch {
      res.writeHead(404).end('not found');
    }
  }
}).listen(PORT, () => console.log(`serving ${ROOT} on ${PORT}`));
