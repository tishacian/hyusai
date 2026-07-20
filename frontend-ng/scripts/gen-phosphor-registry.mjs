#!/usr/bin/env node
/**
 * Regenerate src/app/shared/ui/phosphor-registry.ts from @iconify-json/ph.
 * Usage: node scripts/gen-phosphor-registry.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ph = require('@iconify-json/ph/icons.json');

const MAP = {
  "message-square": "chat",
  "target": "target",
  "mic": "microphone",
  "atom": "atom",
  "workflow": "tree-structure",
  "layers": "stack",
  "database": "database",
  "cpu": "cpu",
  "list-checks": "list-checks",
  "tag": "tag",
  "shield-check": "shield-check",
  "boxes": "package",
  "sparkles": "sparkle",
  "zap": "lightning",
  "brain": "brain",
  "bot": "robot",
  "users": "users",
  "search": "magnifying-glass",
  "folder": "folder",
  "file-text": "file-text",
  "settings": "gear",
  "sliders-horizontal": "sliders",
  "bar-chart-3": "chart-line",
  "plugs": "plugs",
  "cube": "cube",
  "layout-dashboard": "squares-four",
  "hard-drive": "hard-drives",
  "circuitry": "circuitry"
};

function prepareBody(body) {
  return body
    .replace(/opacity="\.2"/g, 'class="ph-duotone-secondary"')
    .replace(/opacity="0\.2"/g, 'class="ph-duotone-secondary"');
}

const entries = [];
for (const [lucideName, phName] of Object.entries(MAP)) {
  const key = `${phName}-duotone`;
  const icon = ph.icons[key];
  if (!icon?.body) throw new Error(`Missing Phosphor icon: ${key}`);
  entries.push({ lucideName, body: prepareBody(icon.body) });
}

const lines = [
  '/**',
  ' * Curated Phosphor duotone bodies for identity icons.',
  ' * Generated from @iconify-json/ph — do not import the full pack in app code.',
  ' * Regenerate: node scripts/gen-phosphor-registry.mjs',
  ' *',
  ' * Keys use Lucide-facing kebab names so templates can stay name-compatible.',
  ' */',
  '',
  'export type PhosphorIconName = keyof typeof PHOSPHOR_DUOTONE;',
  '',
  'export const PHOSPHOR_DUOTONE = {',
];
for (const e of entries) {
  const escaped = e.body.replace(/\\/g, '\\\\').replace(/`/g, '\\`');
  lines.push(`  '${e.lucideName}': \`${escaped}\`,`);
}
lines.push('} as const;');
lines.push('');
lines.push('export function phosphorDuotoneBody(name: string): string | null {');
lines.push('  const body = (PHOSPHOR_DUOTONE as Record<string, string>)[name];');
lines.push('  return body ?? null;');
lines.push('}');
lines.push('');

const out = path.resolve('src/app/shared/ui/phosphor-registry.ts');
fs.writeFileSync(out, lines.join('\n'));
console.log(`Wrote ${out} (${entries.length} icons)`);
