import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  RAIL_LABELS_AUTO_DAYS,
  isRailLabelsPreference,
  railLabelsVisible,
} from './rail-labels';

const DAY = 24 * 60 * 60 * 1000;
const firstSeen = '2026-09-01T09:00:00Z';
const seenMs = Date.parse(firstSeen);

test('auto shows the labels during the first 14 days, then hides them', () => {
  assert.equal(RAIL_LABELS_AUTO_DAYS, 14);
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs), true, 'first sighting');
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs + 13 * DAY), true, 'day 13');
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs + 14 * DAY - 1), true, 'one ms before the boundary');
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs + 14 * DAY), false, 'exactly 14 days');
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs + 14 * DAY + 1), false, 'past the boundary');
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs + 90 * DAY), false, 'an expert');
});

test('an explicit choice wins over the date in both directions', () => {
  assert.equal(railLabelsVisible('shown', firstSeen, seenMs + 400 * DAY), true);
  assert.equal(railLabelsVisible('hidden', firstSeen, seenMs), false);
  assert.equal(railLabelsVisible('shown', null, seenMs), true);
  assert.equal(railLabelsVisible('hidden', null, seenMs), false);
});

test('auto without a readable first sighting keeps the icon rail', () => {
  assert.equal(railLabelsVisible('auto', null, seenMs), false);
  assert.equal(railLabelsVisible('auto', undefined, seenMs), false);
  assert.equal(railLabelsVisible('auto', 'not-a-date', seenMs), false);
  assert.equal(railLabelsVisible(undefined, firstSeen, seenMs + DAY), true, 'missing preference means auto');
  // Clock skew: a first sighting in the future is still a newcomer.
  assert.equal(railLabelsVisible('auto', firstSeen, seenMs - DAY), true);
});

test('only the three server values are preferences', () => {
  for (const value of ['auto', 'shown', 'hidden']) assert.equal(isRailLabelsPreference(value), true);
  for (const value of ['', 'visible', null, undefined, true, 1]) assert.equal(isRailLabelsPreference(value), false);
});
