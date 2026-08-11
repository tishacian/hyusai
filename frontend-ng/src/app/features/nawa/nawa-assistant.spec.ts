/**
 * A citation must show the sentence the answer rests on, and it must be
 * findable, verbatim, in the document it names. That is the whole job of this
 * module, and everything below is a way of failing it: quoting the document's
 * masthead, quoting the chunk's opening when the rule is four sentences down,
 * rewriting the evidence to fit, or cutting it mid-word.
 *
 * How the citations of one turn are assembled — the numbering, what counts as
 * unsupported, which retrieval a passage came out of — belongs to the engine
 * contract and is exercised in `nawa-engine.spec.ts`, against the payload that
 * contract describes.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  cleanPassage,
  documentTitle,
  elapsedLabel,
  excerptFromDocument,
  SUGGESTED_QUESTIONS,
} from './nawa-assistant';

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

// The published policy, read from the very file the ingestion sent to the index.
// If the corpus moves or is reworded, this test is where it is felt.
//
// Resolved from the working directory, not from `import.meta.url`: the unit
// runner bundles specs into a temp directory, where a path relative to the
// module no longer reaches the assets tree. Both entry points — `npm run
// test:unit` and tsx on this file — run from `frontend-ng`.
const POLICY = readFileSync('src/assets/nawa/knowledge/password-and-account-policy.md', 'utf8');

test('the excerpt comes from the published policy, verbatim', () => {
  const answer =
    'No. A temporary password is issued only to the requester and never to a line manager, ' +
    'colleague, assistant, or any third party.';
  const passage = excerptFromDocument(POLICY, answer);

  assert.ok(passage.length > 40, passage);
  assert.ok(/line manager/i.test(passage), `the supporting rule is missing: ${passage}`);
  // Verbatim: what is shown must be findable in the file, once both are read as
  // prose. The ellipses mark the cuts and are not part of the quotation.
  const prose = POLICY.split('\n').map((l) => l.trim()).filter(Boolean).join(' ').replace(/\s{2,}/g, ' ');
  const shown = passage.replace(/^…/, '').replace(/…$/, '');
  assert.ok(prose.includes(shown), shown);
});

test('the excerpt never quotes the document control block or a heading', () => {
  for (const answer of ['owner version effective policy document', 'temporary password line manager']) {
    const passage = excerptFromDocument(POLICY, answer);
    assert.ok(!/^#/.test(passage), passage);
    assert.ok(!/document owner|^version\b/i.test(passage), passage);
  }
});

test('a policy that says nothing the answer echoes yields no excerpt', () => {
  // Empty, not a guess: the caller falls back to the retrieval's own snippet.
  // "four" alone is a coincidence — the policy has "three of the four following
  // groups" — and one shared word must not be enough to build a window on.
  assert.equal(excerptFromDocument(POLICY, 'The canteen closes at four on Fridays.'), '');
  assert.equal(excerptFromDocument(null, 'anything'), '');
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
