/**
 * The preview is read from the customer's own workbook, so it is tested against
 * the workbook: every one of the 39 services must produce a plan the screen can
 * play, and the four services the sidebar offers must read the way a desk agent
 * would read them.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import { routeIntake } from './nawa-intake';
import type { NawaUseCase } from './nawa-itsd.model';
import { planPreview, readApprovers, readSteps, readSubject } from './nawa-preview';

const CATALOGUE: NawaUseCase[] = JSON.parse(
  readFileSync(join(process.cwd(), 'src/assets/nawa/itsd-use-cases.json'), 'utf8'),
).use_cases;

function bySlug(slug: string): NawaUseCase {
  const found = CATALOGUE.find((entry) => entry.slug === slug);
  assert.ok(found, `${slug} is missing from the catalogue`);
  return found;
}

function planFor(utterance: string) {
  const match = routeIntake(utterance, CATALOGUE);
  assert.ok(match, `"${utterance}" no longer routes to a service`);
  return planPreview(match, utterance);
}

test('the conversation satisfies the step that asks for the request', () => {
  const steps = readSteps(bySlug('email-reactivation'));
  assert.equal(steps[0].actor, 'intake');
  assert.match(steps[0].text, /submits a reactivation request/);
});

test('the decision is the step where IT checks an approval, and only that one', () => {
  const steps = readSteps(bySlug('email-reactivation'));
  const approvals = steps.filter((step) => step.actor === 'approval');
  assert.equal(approvals.length, 1);
  assert.match(approvals[0].text, /verifies approval from the Line Manager and HR/);
  // "sends credentials to the approver for handover" names an approver without
  // being a decision; "IT installs the approved software" is an installation.
  assert.equal(steps[5].actor, 'automated');
  assert.equal(
    readSteps(bySlug('software-installation')).filter((s) => s.actor === 'approval').length,
    1,
  );
});

test('a procedure with no approval step yields no decision', () => {
  const steps = readSteps(bySlug('unlock-ad-account'));
  assert.equal(
    steps.filter((step) => step.actor === 'approval').length,
    0,
    'nothing in this procedure asks for an approval',
  );
  assert.equal(steps[0].actor, 'intake', 'the user contacting IT is the intake');
});

test('the approvers are the roles the procedure names, in order', () => {
  assert.deepEqual(readApprovers(readSteps(bySlug('email-reactivation'))), ['Line Manager', 'HR']);
  assert.deepEqual(readApprovers(readSteps(bySlug('unlock-ad-account'))), []);
});

test('a named subject is carried into the opening line', () => {
  assert.equal(readSubject('i want to reactivate an email for Mr. Thibaud'), 'Mr. Thibaud');
  assert.equal(readSubject('I need an email account for a new joiner starting Sunday'), 'a new joiner');
  assert.equal(readSubject('Please reactivate the mailbox of a colleague who came back'), 'a colleague');
  // A target is not a person: putting "the finance distribution group" where a
  // name goes would be worse than saying nothing.
  assert.equal(readSubject('Please add two members to the finance distribution group.'), null);
});

test('the opening line takes charge, announces the count and the stop', () => {
  const plan = planFor('i want to reactivate an email for Mr. Thibaud');
  assert.match(plan.intro, /^Email Reactivation\. Request captured for Mr\. Thibaud\./);
  assert.match(plan.intro, /seven-step procedure/);
  assert.match(plan.intro, /I stop for Line Manager and HR before anything changes/);
  // The old copy sent the requester away; that must not come back.
  assert.doesNotMatch(`${plan.intro} ${plan.gateAsk} ${plan.approved}`, /ITSD Portal|rollout plan/i);
});

test('the decision names its step and states that nothing has changed', () => {
  const plan = planFor('i want to reactivate an email for Mr. Thibaud');
  assert.equal(plan.gateIndex, 1);
  assert.match(plan.gateAsk, /^Step 2 is Line Manager and HR approval\./);
  assert.match(plan.gateAsk, /Nothing has been changed so far/);
  assert.match(plan.declined, /Nothing was changed/);
});

test('the standing mark says what a preview is and what it is not', () => {
  const plan = planFor('I need an email account for a new joiner starting Sunday');
  assert.match(plan.note, /Preview of the automated service/);
  assert.match(plan.note, /nothing was executed and no ticket was raised/);
  assert.match(plan.note, /Password Reset is the service that acts for real/);
});

test('the workbook still has three services with no written procedure', () => {
  const bare = CATALOGUE.filter((useCase) => readSteps(useCase).length === 0).map((u) => u.slug);
  assert.deepEqual(bare, [
    'closure-of-non-responsive-tickets',
    'providing-vpn-avd-access-for-users',
    'collecting-user-hardware-information-assistant',
  ]);
});

test('every service in the catalogue produces a playable plan', () => {
  for (const useCase of CATALOGUE) {
    const plan = planPreview(
      { useCase, live: false, sameFamily: 0 } as never,
      `I need help with ${useCase.name}`,
    );
    assert.ok(plan.intro.length > 40, `${useCase.slug} has no opening line`);
    if (plan.steps.length === 0) {
      assert.match(
        plan.intro,
        /has not written its procedure/,
        `${useCase.slug} has no steps and does not say so`,
      );
      assert.equal(plan.gateIndex, -1);
      continue;
    }
    assert.ok(
      plan.gateIndex === -1 || plan.steps[plan.gateIndex].actor === 'approval',
      `${useCase.slug} points its decision at the wrong step`,
    );
    assert.ok(
      plan.steps.filter((step) => step.actor === 'approval').length <= 1,
      `${useCase.slug} would stop twice`,
    );
  }
});

test('the four suggested requests all reach a plan', () => {
  for (const utterance of [
    'I need an email account for a new joiner starting Sunday.',
    'My account is locked after too many attempts.',
    'Please add two members to the finance distribution group.',
    'i want to reactivate an email for Mr. Thibaud',
  ]) {
    const plan = planFor(utterance);
    assert.ok(plan.steps.length > 0, utterance);
  }
});
