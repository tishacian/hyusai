import '@angular/compiler';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

test('help-guide keeps Work chrome and names the return origin (UX-045 h2)', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/app/features/help/help-guide.component.ts'),
    'utf8',
  );
  assert.match(source, /app-work-bar/);
  assert.match(source, /experience\.help\.back/);
  assert.match(source, /helpOrigin/);
  assert.match(source, /originLabel/);
  assert.doesNotMatch(source, /navLink\]="\{\s*surface:\s*'work'/);
});
