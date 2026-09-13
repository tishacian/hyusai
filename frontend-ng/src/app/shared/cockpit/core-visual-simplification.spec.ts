import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

const objectHeader = read('src/app/shared/cockpit/object-header.component.ts');
const sectionHeader = read('src/app/shared/ui/section-header.component.ts');
const askShell = read('src/app/features/chat/chat-workspace.component.ts');
const chatPanel = read('src/app/features/chat/chat-panel.component.ts');
const settings = read('src/app/features/resources/resources-page.component.ts');
const knowledge = read('src/app/features/knowledge/knowledge-base.component.ts');
const build = read('src/app/features/systems/system-builder.component.ts');
const runs = read('src/app/features/runs/runs-list.component.ts');

test('generic headers are flat and use icons as labels rather than tiles', () => {
  assert.doesNotMatch(objectHeader, /backdropFilter/);
  assert.doesNotMatch(objectHeader, /linear-gradient/);
  assert.match(objectHeader, /background\]="'var\(--ck-bg-base/);
  assert.doesNotMatch(sectionHeader, /ck-tone-info[\s\S]{0,100}w-8 h-8/);
});

test('Settings is a focused setup route while the broader Resources page keeps its portfolio', () => {
  assert.match(settings, /focusedSettings\(\) \? i18n\.t\('resources\.providers\.routing\.title'/);
  assert.match(settings, /@if \(!focusedSettings\(\)\) \{[\s\S]*Portfolio summary belongs to Resources/);
  assert.match(settings, /focusedSettings\.set\(this\.router\.url\.split\('\?'\)\[0\] === '\/settings'\)/);
});

test('Knowledge and Build use restrained selection and action treatments', () => {
  assert.match(knowledge, /\.ck-btn-primary \{\s*background: var\(--ck-signal-cool\)/);
  assert.doesNotMatch(knowledge, /backdrop-blur/);
  assert.doesNotMatch(build, /var\(--ck-glow-cool\)/);
  assert.doesNotMatch(build, /tone="violet"/);
  assert.doesNotMatch(build, /var\(--ck-signal-violet\)/);
});

test('Ask and Runs have explicit narrow-screen behavior', () => {
  assert.match(askShell, /t-simple-shell[\s\S]*@media \(max-width: 640px\)/);
  assert.match(chatPanel, /\.chat-history-panel \{[\s\S]{0,300}?background: var\(--ck-bg-panel\)/);
  assert.match(chatPanel, /\.chat-control-bar \{[\s\S]{0,300}?background: var\(--ck-bg-panel\)/);
  assert.match(runs, /\.runs-actions,[\s\S]*flex-wrap: wrap/);
  assert.match(runs, /@media \(max-width: 640px\)/);
});
