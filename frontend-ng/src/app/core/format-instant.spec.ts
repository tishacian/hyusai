import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatInstant, parseInstant } from './format-instant';

test('engine timestamps without offset are UTC, with or without fractions', () => {
  assert.equal(parseInstant('2026-10-22T13:15:22'), Date.UTC(2026, 9, 22, 13, 15, 22));
  assert.equal(parseInstant('2026-10-22T16:13:11.527526'), Date.parse('2026-10-22T16:13:11.527Z'));
  assert.equal(parseInstant('2026-10-22T13:15:22+02:00'), Date.UTC(2026, 9, 22, 11, 15, 22));
  assert.equal(parseInstant('not a date'), null);
  assert.equal(parseInstant(null), null);
});

test('an instant is shown with its zone and never as raw ISO', () => {
  const text = formatInstant('2026-10-22T13:15:22', 'en-GB', { timeZone: 'Europe/Paris', seconds: true });
  assert.equal(text, '22 Oct 2026, 15:15:22 CEST');
  const utc = formatInstant('2026-10-22T13:15:22', 'fr-FR', { timeZone: 'UTC' });
  assert.match(utc ?? '', /22 oct\. 2026.*13:15.*UTC/);
  assert.equal(formatInstant('', 'fr-FR'), null);
});
