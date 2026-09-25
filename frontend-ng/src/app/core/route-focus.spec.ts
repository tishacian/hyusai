import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { navigationFocusFromState } from './route-focus';

describe('navigationFocusFromState', () => {
  it('reads a non-empty focus selector from navigation state', () => {
    assert.equal(navigationFocusFromState({ focus: '  #open-in-work  ' }), '#open-in-work');
    assert.equal(navigationFocusFromState({ focus: '' }), null);
    assert.equal(navigationFocusFromState({ focus: '   ' }), null);
    assert.equal(navigationFocusFromState({ focus: 12 }), null);
    assert.equal(navigationFocusFromState({ navigationId: 3 }), null);
    assert.equal(navigationFocusFromState(null), null);
    assert.equal(navigationFocusFromState(undefined), null);
  });
});
