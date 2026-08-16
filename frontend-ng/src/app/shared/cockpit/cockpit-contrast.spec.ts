import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const source = readFileSync(join(process.cwd(), 'src/styles/cockpit-tokens.scss'), 'utf8');
const dark = source.slice(source.indexOf(':root {'), source.indexOf('html:not(.dark)'));
const light = source.slice(source.indexOf('html:not(.dark)'));

function token(block: string, name: string): string {
  const match = block.match(new RegExp(`${name}:\\s*([^;]+);`));
  assert.ok(match, `missing ${name}`);
  const value = match[1].trim();
  const alias = value.match(/^var\((--[^)]+)\)$/)?.[1];
  return alias ? token(block, alias) : value;
}

function luminance(hex: string): number {
  assert.match(hex, /^#[0-9a-f]{6}$/i);
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  return channels
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
}

function contrast(foreground: string, background: string): number {
  const [high, low] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

test('primary CTA text meets WCAG AA in dark and light themes', () => {
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-cta-fg'), token(block, '--ck-cta-bg')) >= 4.5);
  }
});

test('secondary text meets WCAG AA on cockpit panels', () => {
  for (const block of [dark, light]) {
    assert.ok(contrast(token(block, '--ck-fg-4'), token(block, '--ck-bg-panel')) >= 4.5);
  }
});
