/**
 * The spoken form is where a voice assistant is judged. These lock the two
 * failures that make one sound broken: trailing off mid-sentence, and reading
 * screen furniture — citation markers, bullets, emphasis — out loud.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spokenAction, spokenAnswer, spokenOutcome, spokenService } from './nawa-speech';

test('a short answer is spoken as written', () => {
  const answer = 'Passwords must be at least 12 characters and are reset every 90 days.';
  assert.equal(spokenAnswer(answer), answer);
});

test('a long answer is cut at a sentence, never mid-word', () => {
  const answer =
    'Passwords must be at least twelve characters long and contain three character classes. ' +
    'They expire every ninety days and the previous five may not be reused. ' +
    'Accounts lock after five failed attempts and stay locked for thirty minutes. ' +
    'A reset requires two independent proofs of identity before the desk may act. ' +
    'Shared accounts are forbidden except where an approved exception is recorded.';

  const spoken = spokenAnswer(answer);
  assert.ok(spoken.length < answer.length, 'nothing was shortened');
  assert.ok(spoken.includes('on screen'), 'the listener is not told where the rest is');
  // Everything before the hand-off ends on a full stop.
  const body = spoken.slice(0, spoken.indexOf(' The '));
  assert.match(body, /[.!?]$/);
});

test('citation markers and markdown never reach the ear', () => {
  const answer = 'A reset needs **two** proofs [1], and the desk records both [2, 3].';
  const spoken = spokenAnswer(answer, 3);
  assert.ok(!spoken.includes('['), 'a citation marker would be read aloud');
  assert.ok(!spoken.includes('*'), 'emphasis would be read aloud');
  assert.equal(spoken, 'A reset needs two proofs, and the desk records both.');
});

test('sources are mentioned only when the answer was shortened', () => {
  const short = 'Multi-factor authentication is mandatory for remote access.';
  assert.equal(spokenAnswer(short, 4), short, 'a whole answer should not advertise the screen');
});

test('a procedure is spoken as a count, not as a list', () => {
  const reply =
    'This is a known service request: New Email Account. It is handled by the service desk today, ' +
    'following the procedure below. Automation for it is in the rollout plan for this workspace.';
  const spoken = spokenService(reply, 7);
  assert.ok(spoken.includes('7 steps'), 'the step count is missing');
  assert.ok(!spoken.includes('1.'), 'the steps themselves are being read out');
});

test('a single step is announced in the singular', () => {
  assert.ok(spokenService('Handled by the desk.', 1).includes('1 step of'));
});

test('a service with no documented procedure says nothing extra', () => {
  const reply = 'This is a known service request: Printer Access.';
  assert.equal(spokenService(reply, 0), reply);
});

test('an offer names the button, and says nothing has started', () => {
  // A listener is not looking at the screen. Said badly, this is the worst line
  // of the demonstration: either it sounds as though the reset is under way, or
  // it sounds as though nothing can be done and the requester leaves.
  const spoken = spokenAction(
    'I can process a password reset here. Before anything is changed I have to verify your '
    + 'identity, which is step 2 of the service desk procedure.',
    'Password Reset',
  );
  assert.match(spoken, /Nothing has started yet/);
  assert.match(spoken, /button to run Password Reset/);
  assert.match(spoken, /it starts when you press it/);
  // And the reason it is being asked for is still spoken first.
  assert.match(spoken, /^I can process a password reset here\./);
});

test('an empty answer is admitted rather than mumbled', () => {
  assert.match(spokenAnswer('   '), /no answer/);
});

test('an outcome keeps more room than a library answer', () => {
  const outcome =
    'Your password has been reset and a one-time code has been sent to your registered mobile number. ' +
    'You will be asked to choose a new password at your next sign-in. ' +
    'The change has been recorded in the service desk audit trail with both proofs of identity. ' +
    'No further action is needed from you.';
  assert.equal(spokenOutcome(outcome), outcome, 'a four-sentence outcome should survive whole');
});
