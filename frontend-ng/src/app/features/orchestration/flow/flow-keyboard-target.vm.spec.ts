import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  FLOW_DELETE_BLOCK_SELECTOR,
  blocksFlowDeleteShortcut,
} from './flow-keyboard-target.vm';

function target(matches: boolean): EventTarget {
  return {
    closest: (selector: string) => {
      assert.equal(selector, FLOW_DELETE_BLOCK_SELECTOR);
      return matches ? { matched: true } : null;
    },
  } as unknown as EventTarget;
}

test('global node deletion yields to native and ARIA interaction surfaces', () => {
  for (const selector of [
    'button',
    'a',
    'dialog',
    'menu',
    '[role="dialog"]',
    '[role="menu"]',
    '[role="listbox"]',
    '[role="combobox"]',
  ]) {
    assert.match(
      FLOW_DELETE_BLOCK_SELECTOR,
      new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
    );
  }
  assert.equal(blocksFlowDeleteShortcut(target(true)), true);
  assert.equal(blocksFlowDeleteShortcut(target(false)), false);
  assert.equal(blocksFlowDeleteShortcut(null), false);
  assert.equal(blocksFlowDeleteShortcut({} as EventTarget), false);
});

test('closest-based guard covers a nested icon inside a button or dialog', () => {
  let received = '';
  const nested = {
    closest: (selector: string) => {
      received = selector;
      return { tagName: 'BUTTON' };
    },
  } as unknown as EventTarget;
  assert.equal(blocksFlowDeleteShortcut(nested), true);
  assert.match(received, /button/);
  assert.match(received, /\[role="dialog"\]/);
});
