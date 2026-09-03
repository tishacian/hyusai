import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  chatExecutionSaveBody,
  clampChatExecutionPercentage,
  isChatExecutionMode,
  parseChatExecution,
} from './chat-execution.types';

test('isChatExecutionMode accepts only the three policy modes', () => {
  assert.equal(isChatExecutionMode('classic'), true);
  assert.equal(isChatExecutionMode('hybrid'), true);
  assert.equal(isChatExecutionMode('agentic_default'), true);
  assert.equal(isChatExecutionMode('agentic'), false);
});

test('clampChatExecutionPercentage stays in 0..100', () => {
  assert.equal(clampChatExecutionPercentage(-4), 0);
  assert.equal(clampChatExecutionPercentage(140), 100);
  assert.equal(clampChatExecutionPercentage('25'), 25);
  assert.equal(clampChatExecutionPercentage('nope'), 0);
});

test('parseChatExecution defaults to hybrid at 0 % and keeps invariants', () => {
  const empty = parseChatExecution(null);
  assert.equal(empty.mode, 'hybrid');
  assert.equal(empty.percentage, 0);
  assert.equal(empty.rollout_ready, true);

  const blocked = parseChatExecution({
    mode: 'hybrid',
    percentage: 40,
    invariants: ['collection is not ready'],
    rollout_ready: false,
    target_system_name: 'Chat agentique',
  });
  assert.equal(blocked.percentage, 40);
  assert.deepEqual(blocked.invariants, ['collection is not ready']);
  assert.equal(blocked.rollout_ready, false);
  assert.equal(blocked.target_system_name, 'Chat agentique');
});

test('chatExecutionSaveBody forces 0 % on classic', () => {
  assert.deepEqual(chatExecutionSaveBody('classic', 80), { mode: 'classic', percentage: 0 });
  assert.deepEqual(chatExecutionSaveBody('hybrid', 25), { mode: 'hybrid', percentage: 25 });
});
