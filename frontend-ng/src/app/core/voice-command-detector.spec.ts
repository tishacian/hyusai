import assert from 'node:assert/strict';
import test from 'node:test';

import { detectVoiceCommand } from './voice-command-detector';

test('canonical global voice pack enables the standard command vocabulary', () => {
  const settings = { command_packs: ['global_voice_v1'] };
  assert.equal(detectVoiceCommand('pause', settings), 'pause');
  assert.equal(detectVoiceCommand('on peut arrêter là', settings), 'stop');
});
