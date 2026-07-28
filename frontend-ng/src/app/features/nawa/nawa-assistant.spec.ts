/**
 * The assistant's screen must not flatter the answer.
 *
 * Two properties carry the whole credibility of the surface, and both are
 * exercised against payloads captured off the live workspace on 28/07:
 *
 * - the citation numbering the screen prints has to be the numbering the model
 *   wrote into its own sentence, so a `[2]` under the answer opens the passage
 *   the model actually leaned on;
 * - an answer the library does not support has to be visibly unsupported, not
 *   an answer with a quiet, empty source list.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  cleanPassage,
  documentTitle,
  elapsedLabel,
  projectTurn,
  SUGGESTED_QUESTIONS,
  type AssistantAnswerPayload,
} from './nawa-assistant';

/** Captured verbatim from `POST /chat/completion` on the nawa workspace. */
const GROUNDED: AssistantAnswerPayload = {
  content:
    'Non. Le mot de passe temporaire est communiqué uniquement au titulaire du compte [1]. ' +
    'Un reset avec les preuves au dossier est traité en priorité 3 [2].',
  duration_ms: 4332,
  sources: [
    {
      filename: 'password-and-account-policy.md',
      title: 'password-and-account-policy.md',
      snippet:
        'Parent context:\nWhat the service desk never does\n\nA temporary password is issued to the requester and to nobody else.',
      relevance_score: 0.35,
      collection: 'itsd-knowledge',
    },
    {
      filename: 'service-desk-priorities-and-targets.md',
      snippet: 'A password reset with the identity evidence on file is handled at priority 3.',
      relevance_score: 0.31,
    },
  ],
};

const UNSUPPORTED: AssistantAnswerPayload = {
  content:
    'No relevant policy is available in the provided context to state the mileage reimbursement rate.',
  duration_ms: 4735,
  sources: [],
};

test('citation numbers follow the source order the model was given', () => {
  const turn = projectTurn('Can my line manager collect it?', GROUNDED);

  assert.deepEqual(
    turn.citations.map((citation) => [citation.index, citation.document]),
    [
      [1, 'Password and Account Policy'],
      [2, 'Service Desk Priorities and Targets'],
    ],
  );
  // The markers in the sentence and the list under it agree.
  for (const citation of turn.citations) {
    assert.ok(
      turn.answer.includes(`[${citation.index}]`),
      `answer has no marker [${citation.index}]`,
    );
  }
});

test('a source is never dropped for repeating a document', () => {
  const twice = projectTurn('…', {
    ...GROUNDED,
    sources: [GROUNDED.sources![0], GROUNDED.sources![0]],
  });

  assert.equal(twice.citations.length, 2, 'collapsing them would renumber [2] onto nothing');
  assert.deepEqual(twice.citations.map((c) => c.index), [1, 2]);
});

test('an answer with no source is marked unsupported', () => {
  const turn = projectTurn('What is the mileage rate?', UNSUPPORTED);

  assert.equal(turn.unsupported, true);
  assert.deepEqual(turn.citations, []);
  assert.ok(turn.answer.length > 0, 'the refusal is still shown — it is the answer');
});

test('a source with no readable passage is not offered as a citation', () => {
  const turn = projectTurn('…', {
    ...GROUNDED,
    sources: [{ filename: 'password-and-account-policy.md', snippet: '   ' }],
  });

  assert.deepEqual(turn.citations, [], 'an unopenable citation is worse than none');
  assert.equal(turn.unsupported, true);
});

test('the retrieval prefix is stripped, the section heading is kept', () => {
  assert.equal(
    cleanPassage('Parent context:\nWhat the service desk never does\n\nA temporary password…'),
    'What the service desk never does A temporary password…',
  );
  assert.equal(cleanPassage(null), '');
});

test('a citation quotes the policy, not the document masthead', () => {
  // The first chunk of every document in the library opens on its own front
  // matter. Quoting that as evidence is what made the first citation on screen
  // read as noise.
  const passage = cleanPassage(
    '# Password and Account Policy\n' +
      'Document owner: IT Security Office · Version 3.2 · Effective 1 March 2026\n' +
      'Applies to: all staff and contractors with a corporate account\n' +
      'Sample content prepared for the WE preview workspace.\n\n' +
      'Corporate account passwords must be at least 12 characters long.',
  );

  assert.equal(passage, 'Corporate account passwords must be at least 12 characters long.');
});

test('front matter is never dropped to nothing', () => {
  // A chunk that is only front matter still has to show something, or the
  // citation becomes unopenable and is filtered out as empty.
  assert.equal(cleanPassage('# Password and Account Policy'), '# Password and Account Policy');
});

test('a long passage is cut at a word and marked as cut', () => {
  const long = `${'evidence '.repeat(60)}end`;
  const passage = cleanPassage(long);

  assert.ok(passage.length <= 301, `${passage.length}`);
  assert.ok(passage.endsWith('…'), passage.slice(-20));
  assert.ok(!/\s…$/.test(passage), 'no dangling space before the ellipsis');
  assert.ok(long.startsWith(passage.slice(0, 40)), 'what is shown stays verbatim');
});

// The chunk that actually shipped: a question about who may collect a temporary
// password retrieves the password policy, whose chunk opens four sentences
// earlier on character-length requirements. Showing that opening as the evidence
// is what invites "your citation does not say that".
const PASSWORD_CHUNK =
  '1. Password requirements Corporate account passwords must be at least 12 characters long ' +
  'and contain characters from three of the four following groups: upper case, lower case, ' +
  'digits, symbols. Passwords expire every 180 days and the previous ten passwords cannot ' +
  'be reused. Accounts lock for 30 minutes after five consecutive failed sign-ins. ' +
  'A temporary password is issued to the account holder only. The service desk never hands ' +
  'a temporary password to a line manager or to any other third party. ' +
  'The account holder is required to choose a new password at first sign-in.';

test('the excerpt shows the sentence the answer rests on, not the chunk opening', () => {
  const answer =
    'No. A temporary password is issued only to you, never to a line manager or any other ' +
    'third party. A line manager may confirm your identity, but may not receive the password.';
  const passage = cleanPassage(PASSWORD_CHUNK, answer);

  assert.ok(
    passage.includes('never hands a temporary password to a line manager'),
    `the supporting sentence is missing: ${passage}`,
  );
  assert.ok(
    !passage.includes('at least 12 characters'),
    `the chunk opening is not what the answer rests on: ${passage}`,
  );
  // Verbatim and contiguous: what is shown must be findable as-is in the source.
  const shown = passage.replace(/^…/, '').replace(/…$/, '');
  assert.ok(PASSWORD_CHUNK.includes(shown), shown);
  // Cut at the front, so the reader is told the passage starts earlier.
  assert.ok(passage.startsWith('…'), passage.slice(0, 40));
});

test('an excerpt whose opening does support the answer keeps its opening', () => {
  const answer = 'Corporate passwords must be at least 12 characters long and expire every 180 days.';
  const passage = cleanPassage(PASSWORD_CHUNK, answer);

  assert.ok(passage.startsWith('1. Password requirements'), passage.slice(0, 60));
  assert.ok(!passage.startsWith('…'), 'nothing was elided before the beginning');
});

test('a passage that echoes nothing in the answer falls back to its beginning', () => {
  const answer = 'Priority 2 tickets are responded to within four working hours.';
  const passage = cleanPassage(PASSWORD_CHUNK, answer);

  assert.ok(passage.startsWith('1. Password requirements'), passage.slice(0, 60));
  assert.ok(passage.endsWith('…'), passage.slice(-20));
});

test('the excerpt obeys the same length budget as the prefix it replaces', () => {
  for (const answer of ['line manager third party temporary password', 'expire reused digits symbols']) {
    const passage = cleanPassage(PASSWORD_CHUNK, answer);
    assert.ok(passage.length <= 302, `${answer} → ${passage.length}`);
  }
});

test('the citation under an answer is windowed on that answer', () => {
  const turn = projectTurn('Can my line manager collect my temporary password?', {
    content: 'No. The service desk never hands a temporary password to a line manager [1].',
    sources: [{ filename: 'password-and-account-policy.md', snippet: PASSWORD_CHUNK }],
    duration_ms: 946,
  });

  assert.equal(turn.citations.length, 1);
  assert.ok(turn.citations[0].passage.includes('never hands a temporary password'), turn.citations[0].passage);
});

test('file names are read as document titles', () => {
  assert.equal(documentTitle('joiners-movers-leavers.md'), 'Joiners Movers Leavers');
  assert.equal(documentTitle('remote-access-and-vpn.md'), 'Remote Access and Vpn');
  assert.equal(documentTitle(undefined), 'Service desk library');
});

test('elapsed time reads as a duration, never as a raw float', () => {
  assert.equal(elapsedLabel(4332), '4.3 s');
  assert.equal(elapsedLabel(840.6), '841 ms');
  assert.equal(elapsedLabel(0), '');
  assert.equal(elapsedLabel(null), '');
});

test('the elapsed time falls back to the client clock when the body omits it', () => {
  const turn = projectTurn('…', { ...GROUNDED, duration_ms: null }, 2500);
  assert.equal(turn.elapsed, '2.5 s');
});

test('every suggested question is a question a desk receives', () => {
  assert.equal(SUGGESTED_QUESTIONS.length, 6);
  for (const question of SUGGESTED_QUESTIONS) {
    assert.ok(question.length > 25, question);
    assert.ok(/[?.]$/.test(question), question);
  }
  // The policy the automation enforces must be askable in words, or the two
  // halves of the demonstration never meet.
  assert.ok(
    SUGGESTED_QUESTIONS.some((question) => /identity evidence/i.test(question)),
    'no question reaches the identity rule the password-reset agent applies',
  );
});
