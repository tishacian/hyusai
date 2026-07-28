/**
 * The front door has exactly two ways to fail in front of an audience, and both
 * are tested here against the customer's own catalogue rather than a fixture:
 *
 * - a service request answered with a policy quotation. "My account is locked"
 *   must reach Unlock AD Account, not a paragraph about lockout durations.
 * - a question about the rules turned into a service. "What identity evidence
 *   do you need before you reset a password?" must stay with the library, or the
 *   assistant offers to reset the password of someone who asked how resets work.
 *
 * The routing table below is the calibration, kept as a test so a change to the
 * floor, the margin or the alias list is felt on all of it at once and not just
 * on the utterance that motivated the change.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  composeIdentity,
  composeTypedCase,
  IDENTITY_REQUEST,
  plannedReply,
  procedureSteps,
  readIdentity,
  REQUEST_EXAMPLES,
  readsAsRequest,
  routeIntake,
  type NawaFreeTextSettings,
} from './nawa-intake';
import type { NawaUseCase } from './nawa-itsd.model';

/** The catalogue extracted from the customer's automation workbook, as shipped. */
const CATALOGUE: NawaUseCase[] = JSON.parse(
  readFileSync('src/assets/nawa/itsd-use-cases.json', 'utf8'),
).use_cases;

test('the catalogue the router reads is the shipped one', () => {
  assert.ok(CATALOGUE.length >= 39, `${CATALOGUE.length}`);
  assert.equal(CATALOGUE.filter((entry) => entry.status === 'live').length, 2);
});

test('requests reach the service they belong to', () => {
  const table: ReadonlyArray<readonly [string, string]> = [
    ['I forgot my password', 'password-reset'],
    ['I forgot my password and I cannot sign in this morning', 'password-reset'],
    ['I want to create an email for a newcomer', 'email-creation'],
    ['I need an email account for a new joiner starting Sunday', 'email-creation'],
    ['My account is locked after too many attempts', 'unlock-ad-account'],
    ['I cannot log in, my account seems locked out', 'unlock-ad-account'],
    ['Please add three members to the finance distribution group', 'email-group-members-addition'],
    ['I want to remove a colleague from an email group', 'email-group-members-deletion'],
    ['I need access to the shared mailbox for the projects team', 'shared-mailbox-user-addition'],
    ['Please create a shared mailbox for the tender team', 'shared-mailbox-creation'],
    ['I need Power BI installed on my laptop', 'software-installation'],
    ['We need a mailbox blocked, the person is leaving on Thursday', 'email-block-hr-it'],
    ['I need my email signature updated', 'user-signature-update'],
    ['I need VPN access, I am working from home tomorrow', 'providing-vpn-avd-access-for-users'],
    ['Please reactivate the mailbox of a colleague who came back', 'email-reactivation'],
  ];
  for (const [utterance, slug] of table) {
    const match = routeIntake(utterance, CATALOGUE);
    assert.equal(match?.useCase.slug ?? null, slug, utterance);
  }
});

test('questions about the rules stay with the library', () => {
  const questions = [
    'How many failed sign-ins lock an account, and how long does it stay locked?',
    'What identity evidence do you need before you reset a password?',
    'Can my line manager collect my temporary password for me?',
    'What is the response target for a priority 2 ticket?',
    'I am travelling to a restricted country next week. What do I need from IT?',
    'How long is a leaver mailbox kept?',
    'What software am I allowed to install myself?',
    'Who approves a shared mailbox request?',
  ];
  for (const question of questions) {
    assert.equal(routeIntake(question, CATALOGUE), null, question);
  }
});

test('every suggested request routes somewhere', () => {
  // These are buttons on the screen. One that routes to nothing would open the
  // library on a request, in front of the audience the surface exists for.
  for (const example of REQUEST_EXAMPLES) {
    const match = routeIntake(example, CATALOGUE);
    assert.ok(match, example);
  }
  // The first is the service that actually runs here.
  assert.equal(routeIntake(REQUEST_EXAMPLES[0], CATALOGUE)?.live, true);
});

test('an utterance that fits several services routes to none of them', () => {
  // Print code creation, print code queries and colour printer access all fit,
  // and the catalogue gives nothing to choose between them. Answering from the
  // library is the graceful outcome; a confident hand-off to one in three would
  // be wrong twice as often as it is right.
  assert.equal(routeIntake('I need a print code for the colour printer', CATALOGUE), null);
});

test('nothing routes when the utterance states no need', () => {
  assert.equal(readsAsRequest('Good morning'), false);
  assert.equal(readsAsRequest('Thanks, that answers it'), false);
  assert.equal(routeIntake('password', CATALOGUE), null);
  assert.equal(routeIntake('I forgot my password', []), null);
});

test('the live service is the one that runs here', () => {
  const match = routeIntake('I forgot my password', CATALOGUE);
  assert.equal(match?.live, true);
  assert.equal(match?.useCase.route, '/nawa/itsd/password-reset');
  assert.equal(routeIntake('I want to create an email for a newcomer', CATALOGUE)?.live, false);
});

test('the reply for a planned service quotes their procedure and promises nothing', () => {
  const match = routeIntake('I want to create an email for a newcomer', CATALOGUE)!;
  const steps = procedureSteps(match.useCase);

  assert.equal(steps.length, 7);
  assert.match(steps[0], /^HR or the requester's manager submits a new email account request/);
  // Their terminology, verbatim — including the portal and the approver names.
  assert.match(steps.join(' '), /ITSD Portal/);
  assert.match(steps.join(' '), /Line Manager/);
  // The numbering is the screen's, so no step may arrive carrying its own.
  for (const step of steps) assert.ok(!/^\d/.test(step), step);

  const reply = plannedReply(match);
  assert.match(reply, /Email Creation/);
  assert.match(reply, /rollout plan/);
  // It must not claim to raise, log or track a ticket: this app does none of it.
  assert.ok(!/\b(?:I will|I'll|I have) (?:raise|log|create|open)/i.test(reply), reply);
});

test('a service of the shared pattern says how many move with it', () => {
  const match = routeIntake('Please add three members to the finance distribution group', CATALOGUE)!;
  assert.ok(match.sameFamily >= 1, `${match.sameFamily}`);
  assert.match(plannedReply(match), /same approval and directory pattern/);
});

// ---------------------------------------------------------------------------
// The live lane: identity before a privileged write
// ---------------------------------------------------------------------------

test('the assistant asks for identity before acting, citing the procedure', () => {
  assert.match(IDENTITY_REQUEST, /verify your identity/i);
  assert.match(IDENTITY_REQUEST, /step 2/);
  assert.match(IDENTITY_REQUEST, /staff number/i);
  assert.match(IDENTITY_REQUEST, /6-digit code/i);
});

test('the two proofs are read out of a reply typed any way round', () => {
  assert.deepEqual(readIdentity('Staff ID 40219, code 553017'), {
    staffId: '40219',
    code: '553017',
  });
  assert.deepEqual(readIdentity('my number is 40219 and the app shows 553017'), {
    staffId: '40219',
    code: '553017',
  });
  assert.deepEqual(readIdentity('40219 / 553017'), { staffId: '40219', code: '553017' });
  // Six digits either side: the label decides which is which.
  assert.deepEqual(readIdentity('badge 448071, authenticator code 553017'), {
    staffId: '448071',
    code: '553017',
  });
  assert.deepEqual(readIdentity('I do not have it with me'), { staffId: null, code: null });
});

test('a proof that was not given is written as missing, not omitted', () => {
  const both = composeIdentity({ staffId: '40219', code: '553017' });
  assert.equal(both.items.length, 2);
  assert.match(both.evidence, /matched against the HR record/);
  assert.match(both.evidence, /One-time code .* verified/);

  const partial = composeIdentity({ staffId: '40219', code: null });
  assert.equal(partial.items.length, 1);
  // The assessment downstream must be able to see the hole, or it will approve
  // an unattended reset on a record that only looks complete.
  assert.match(partial.evidence, /No one-time code given/);

  const neither = composeIdentity({ staffId: null, code: null });
  assert.equal(neither.items.length, 0);
  assert.match(neither.evidence, /No staff number given/);
  // Raising the request is never itself a proof.
  assert.ok(!neither.items.some((item) => /self-service/i.test(item)), neither.items);
});

const FREE_TEXT: NawaFreeTextSettings = {
  label: 'Request typed at the service desk',
  requester_name: 'Sara Al-Naimi',
  requester_upn: 'sara.alnaimi@nawa.qa',
  preferred_language: 'en',
  intent_prompt_template: 'Classify: {transcript}',
  identity_prompt_template: 'Assess: {evidence}',
  notice_prompt_template: 'Write to {requester}',
  max_request_chars: 40,
  simulated_intent: 'password_reset',
  simulated_identity_verdict: 'IDENTITY_VERIFIED …',
  simulated_user_message: 'Your password has been reset …',
};

test('the case carries the requester’s own words, judged by the System’s prompts', () => {
  const evidence = composeIdentity({ staffId: '40219', code: '553017' });
  const composed = composeTypedCase(FREE_TEXT, {
    requestText: 'I forgot my password and I cannot sign in',
    evidence,
  })!;

  assert.equal(composed['channel'], 'self_service_assistant');
  // Cut at 40 characters, on a word: the System's cap, not this module's.
  assert.equal(composed['request_text'], 'I forgot my password and I cannot sign');
  assert.equal(composed['intent_prompt'], 'Classify: I forgot my password and I cannot sign');
  assert.equal(composed['identity_prompt'], `Assess: ${evidence.evidence}`);
  assert.equal(composed['notice_prompt'], 'Write to Sara Al-Naimi');
  assert.equal(composed['simulated_evidence_count'], 2);
  for (const field of ['intent_prompt', 'identity_prompt', 'notice_prompt']) {
    assert.ok(!String(composed[field]).includes('{'), field);
  }
});

test('no case is composed when the System carries no templates', () => {
  // Better a refusal the screen can explain than a run whose prompts are ours:
  // the templates are the flow's contract, not this module's.
  const evidence = composeIdentity({ staffId: '40219', code: '553017' });
  assert.equal(composeTypedCase(null, { requestText: 'x', evidence }), null);
  assert.equal(
    composeTypedCase({ intent_prompt_template: 'only one' }, { requestText: 'x', evidence }),
    null,
  );
});
