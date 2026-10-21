import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkBudget, checkRatchet, findFallbacks } from './check-fallbacks.mjs';

test('AST finds multiline and typed empty fallbacks, not strings or error propagation', () => {
  const source = `
    const misleading = 'catchError(() => of([]))';
    a.pipe(catchError(() => of<Array<User>>([])));
    b.pipe(catchError(() => { return of(null); }));
    c.pipe(catchError(() => EMPTY));
    d.pipe(catchError(error => throwError(() => error)));
    e.catch(() => undefined);
    f.pipe(fallbackUnless(options, []));
  `;
  assert.equal(findFallbacks(source).length, 5);
});

test('replacing a legacy fallback with a new unannotated fallback fails even at equal count', () => {
  const previous = findFallbacks('a.pipe(catchError(() => of(null)))');
  const current = findFallbacks('a.pipe(catchError(() => of([])))');
  const budget = { files: { 'a.ts': { count: 1, fingerprints: { [previous[0].fingerprint]: 1 } } } };
  assert.match(checkBudget({ 'a.ts': current }, budget).join(), /requires/);
  const explained = findFallbacks('// fallback-ok: This optional decorative hint may be absent.\na.pipe(catchError(() => of([])))');
  assert.deepEqual(checkBudget({ 'a.ts': explained }, budget), []);
});

test('comments do not increase allowance and budget file increases fail', () => {
  const current = findFallbacks('// fallback-ok: Missing optional hint is a valid absence.\na.pipe(catchError(() => of(null)))');
  assert.match(checkBudget({ 'new.ts': current }, { files: {} }).join(), /exceed/);
  assert.match(checkRatchet({ files: { 'a.ts': { count: 2 } } }, { files: { 'a.ts': { count: 1 } } }).join(), /only decrease/);
  assert.deepEqual(checkRatchet({ files: { 'a.ts': { count: 0 } } }, { files: { 'a.ts': { count: 1 } } }), []);
});
