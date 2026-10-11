import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  FLOW_DELETE_BLOCK_SELECTOR,
  blocksFlowDeleteShortcut,
  yieldsFlowHistoryShortcut,
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

class FocusNode {
  constructor(readonly parent: FocusNode | null = null) {}

  contains(other: unknown): boolean {
    for (let node = other as FocusNode | null; node; node = node.parent) {
      if (node === this) return true;
    }
    return false;
  }
}

test('undo and redo yield only to a focus outside the builder and its ancestors', () => {
  const body = new FocusNode();
  const main = new FocusNode(body);
  const builder = new FocusNode(main);
  const canvas = new FocusNode(builder);
  const sommaire = new FocusNode(body);
  const host = builder as unknown as EventTarget;

  for (const focused of [canvas, builder, main, body]) {
    assert.equal(yieldsFlowHistoryShortcut(focused as unknown as EventTarget, host), false);
  }
  assert.equal(yieldsFlowHistoryShortcut(sommaire as unknown as EventTarget, host), true);
  assert.equal(yieldsFlowHistoryShortcut(null, host), false);
  assert.equal(yieldsFlowHistoryShortcut(sommaire as unknown as EventTarget, null), false);
});
