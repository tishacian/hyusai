/**
 * The front door used to be a gate. It is now an opinion, and this file is how
 * the opinion is scored.
 *
 * `routeIntake` no longer decides anything: the utterance goes to the
 * conversational engine, and the router's verdict travels beside it as
 * `session_context.route_hint`, one advisory line in the system prompt. The
 * model may follow it, ignore it, or ask a question instead.
 *
 * That changes what these tables are for, not whether they are worth keeping.
 * Every utterance-to-service mapping below was written because a real request
 * had been answered with a policy quotation, or a real question had been turned
 * into a service — and each one still describes the tool the engine ought to
 * reach for:
 *
 * | hint            | what the turn should do      |
 * | --------------- | ---------------------------- |
 * | a live service  | offer the audited launch      |
 * | a planned one   | `preview_service`            |
 * | no opinion      | `search_knowledge`           |
 *
 * So the tables became an evaluation harness. `evaluate` scores the whole set
 * and reports every miss at once, instead of dying on the first row: a hint is
 * allowed to be wrong occasionally in a way a gate was not, and what matters is
 * whether the score moved. The baselines below are the scores as they stand.
 *
 * Two properties are asserted absolutely, because they are what makes a hint a
 * hint: the catalogue always travels, and no hint is sent when the router has
 * no opinion. A router that stays silent must not push the model anywhere —
 * silence used to mean "go to the library", and that is exactly the gate this
 * work removed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  composeIdentity,
  composeTypedCase,
  procedureSteps,
  readIdentity,
  REQUEST_EXAMPLES,
  readsAsRequest,
  routeIntake,
  type NawaFreeTextSettings,
} from './nawa-intake';
import { buildSessionContext, routeHint, SERVICE_CATALOG_LIMIT } from './nawa-engine';
import type { NawaUseCase } from './nawa-itsd.model';

/** The catalogue extracted from the customer's automation workbook, as shipped. */
const CATALOGUE: NawaUseCase[] = JSON.parse(
  readFileSync('src/assets/nawa/itsd-use-cases.json', 'utf8'),
).use_cases;

// ---------------------------------------------------------------------------
// The harness
// ---------------------------------------------------------------------------

/**
 * Two of the three are tools. The third is not, and that is the point: the model
 * is read-only — `start_system_run` is off its allowlist — so a live service is
 * not something it executes, it is a launch the screen offers and a person
 * presses.
 */
type ToolChoice = 'offer_the_launch' | 'preview_service' | 'search_knowledge';

interface EvalCase {
  utterance: string;
  tool: ToolChoice;
  /** The service the tool should be pointed at, or null for a library answer. */
  slug: string | null;
}

interface EvalReport {
  total: number;
  hits: number;
  score: number;
  misses: string[];
}

/**
 * What the hint points the turn at.
 *
 * `route_hint` names a service and says whether it executes here, and those two
 * facts are what separate a launch to offer from a procedure to play from a
 * library to search.
 */
function hintedTool(utterance: string): { tool: ToolChoice; slug: string | null } {
  const hint = routeHint(utterance, CATALOGUE);
  if (!hint) return { tool: 'search_knowledge', slug: null };
  return { tool: hint.live ? 'offer_the_launch' : 'preview_service', slug: hint.slug };
}

function evaluate(cases: readonly EvalCase[]): EvalReport {
  const misses: string[] = [];
  for (const expected of cases) {
    const got = hintedTool(expected.utterance);
    if (got.tool === expected.tool && got.slug === expected.slug) continue;
    misses.push(
      `"${expected.utterance}" → ${got.tool}${got.slug ? `(${got.slug})` : ''}, `
      + `expected ${expected.tool}${expected.slug ? `(${expected.slug})` : ''}`,
    );
  }
  const hits = cases.length - misses.length;
  return { total: cases.length, hits, score: cases.length ? hits / cases.length : 1, misses };
}

/** Assert a set scores at least as well as it did when the set was written. */
function scores(name: string, cases: readonly EvalCase[], baseline: number): void {
  const report = evaluate(cases);
  assert.ok(
    report.score >= baseline,
    `${name}: ${report.hits}/${report.total} (${report.score.toFixed(2)} < ${baseline})\n  `
    + report.misses.join('\n  '),
  );
}

/** A planned service: the engine should read the catalogue entry and play it. */
function preview(utterance: string, slug: string): EvalCase {
  return { utterance, tool: 'preview_service', slug };
}

/** The service that executes here: the screen should offer the run. */
function live(utterance: string, slug: string): EvalCase {
  return { utterance, tool: 'offer_the_launch', slug };
}

/** No opinion. The engine hears the utterance with no service attached to it. */
function library(utterance: string): EvalCase {
  return { utterance, tool: 'search_knowledge', slug: null };
}

test('the catalogue the harness reads is the shipped one', () => {
  assert.ok(CATALOGUE.length >= 39, `${CATALOGUE.length}`);
  assert.equal(CATALOGUE.filter((entry) => entry.status === 'live').length, 2);
  // The engine keeps 40 entries. The workbook must stay inside that, or a
  // service would silently stop being reachable through `list_services`.
  assert.ok(CATALOGUE.length <= SERVICE_CATALOG_LIMIT, `${CATALOGUE.length}`);
});

// ---------------------------------------------------------------------------
// What makes a hint a hint
// ---------------------------------------------------------------------------

test('the catalogue travels on every turn, hint or no hint', () => {
  const asked = buildSessionContext(CATALOGUE, routeHint('I forgot my password', CATALOGUE));
  const unopinionated = buildSessionContext(CATALOGUE, routeHint('Good morning', CATALOGUE));

  for (const context of [asked, unopinionated]) {
    const catalog = context['service_catalog'] as { slug: string }[];
    assert.equal(catalog.length, CATALOGUE.length);
    // The engine drops an entry without a slug, so every one must carry it.
    for (const entry of catalog) assert.ok(entry.slug, JSON.stringify(entry));
  }
});

test('a router with no opinion sends no hint at all', () => {
  // Silence used to mean "answer from the library". Sent as a hint it would be
  // the same gate wearing a different name, so it is simply not sent.
  const context = buildSessionContext(CATALOGUE, routeHint('Good morning', CATALOGUE));
  assert.ok(!('route_hint' in context));
  assert.ok(!('route_hint_service' in context));
  assert.ok(!('route_hint_live' in context));
});

test('a hint names a service and says whether it executes here', () => {
  const context = buildSessionContext(CATALOGUE, routeHint('I forgot my password', CATALOGUE));
  assert.equal(context['route_hint'], 'password-reset');
  assert.equal(context['route_hint_service'], 'Password Reset');
  assert.equal(context['route_hint_live'], true);
  // Scalars only: the engine renders those into the prompt and ignores the rest.
  for (const key of ['route_hint', 'route_hint_service', 'route_hint_live']) {
    assert.ok(['string', 'boolean'].includes(typeof context[key]), key);
  }

  const planned = buildSessionContext(
    CATALOGUE,
    routeHint('I want to create an email for a newcomer', CATALOGUE),
  );
  assert.equal(planned['route_hint'], 'email-creation');
  assert.equal(planned['route_hint_live'], false);
});

test('the hint never names a tool', () => {
  // The mapping from a service to a tool belongs to the model. Naming a tool in
  // the context would be the front deciding again, one indirection further out.
  const context = buildSessionContext(CATALOGUE, routeHint('I forgot my password', CATALOGUE));
  const rendered = JSON.stringify(
    Object.fromEntries(Object.entries(context).filter(([key]) => key !== 'service_catalog')),
  );
  for (const tool of ['start_system_run', 'preview_service', 'search_knowledge', 'list_services']) {
    assert.ok(!rendered.includes(tool), tool);
  }
});

// ---------------------------------------------------------------------------
// The evaluation sets
// ---------------------------------------------------------------------------

test('requests point at the service they belong to', () => {
  scores(
    'typed requests',
    [
      live('I forgot my password', 'password-reset'),
      live('I forgot my password and I cannot sign in this morning', 'password-reset'),
      preview('I want to create an email for a newcomer', 'email-creation'),
      preview('I need an email account for a new joiner starting Sunday', 'email-creation'),
      preview('My account is locked after too many attempts', 'unlock-ad-account'),
      preview('I cannot log in, my account seems locked out', 'unlock-ad-account'),
      preview(
        'Please add three members to the finance distribution group',
        'email-group-members-addition',
      ),
      preview('I want to remove a colleague from an email group', 'email-group-members-deletion'),
      preview(
        'I need access to the shared mailbox for the projects team',
        'shared-mailbox-user-addition',
      ),
      preview('Please create a shared mailbox for the tender team', 'shared-mailbox-creation'),
      preview('I need Power BI installed on my laptop', 'software-installation'),
      preview('We need a mailbox blocked, the person is leaving on Thursday', 'email-block-hr-it'),
      preview('I need my email signature updated', 'user-signature-update'),
      preview(
        'I need VPN access, I am working from home tomorrow',
        'providing-vpn-avd-access-for-users',
      ),
      preview('Please reactivate the mailbox of a colleague who came back', 'email-reactivation'),
    ],
    1,
  );
});

test('what a microphone actually returns still points at the right service', () => {
  // Verbatim transcriptions, not typed sentences: the speech engine contracts
  // "I am" to "I'm", ends on a full stop, and keeps the spoken padding a person
  // drops when typing. The hint scores on stems, so the padding dilutes it —
  // and the voice surface sends the same hint the typed one does.
  scores(
    'spoken requests',
    [
      live("I forgot my password and I'm locked out of my account.", 'password-reset'),
      preview('Hi, I need an email account created for a new joiner please.', 'email-creation'),
      preview(
        "I'd like to get Power BI installed on my laptop if that's possible.",
        'software-installation',
      ),
      preview(
        "Could you give me VPN access? I'm working from home tomorrow.",
        'providing-vpn-avd-access-for-users',
      ),
    ],
    1,
  );
});

test('the phrasings the tables above did not think of also point somewhere', () => {
  // Written after "I lost my password." was answered with a policy quotation in
  // front of a reviewer: every utterance above says "forgot", so the router had
  // never been asked the same thing in another word. Widening the set found
  // four more classes of the same defect, and each line here is one of them:
  // the verb of loss, the bare imperative, the request made for someone else,
  // and the service whose name is a synonym of a sibling's.
  scores(
    'unrehearsed phrasings',
    [
      live('I lost my password.', 'password-reset'),
      live('I have lost my password', 'password-reset'),
      live('My password is lost', 'password-reset'),
      live('I need to change my password.', 'password-reset'),
      live('My password expired and I cannot log in.', 'password-reset'),
      preview('I am locked out of my account.', 'unlock-ad-account'),
      preview('Too many wrong attempts, my account got locked.', 'unlock-ad-account'),
      preview(
        'Remove a colleague from the sales distribution list.',
        'email-group-members-deletion',
      ),
      preview('A colleague is leaving on Friday, block his account.', 'email-block-hr-it'),
      preview('We have a new hire on Monday, he needs an email.', 'email-creation'),
      preview('Please install Adobe Acrobat on my machine.', 'software-installation'),
    ],
    1,
  );
});

test('questions about the rules carry no service hint', () => {
  // A hint here is worse than no hint: it tells the model a question about how
  // resets work is a request to reset something.
  scores(
    'policy questions',
    [
      library('How many failed sign-ins lock an account, and how long does it stay locked?'),
      library('What identity evidence do you need before you reset a password?'),
      library('Can my line manager collect my temporary password for me?'),
      library('What is the response target for a priority 2 ticket?'),
      library('I am travelling to a restricted country next week. What do I need from IT?'),
      library('How long is a leaver mailbox kept?'),
      library('What software am I allowed to install myself?'),
      library('Who approves a shared mailbox request?'),
      // Politeness is not a request. These read exactly like the spoken requests
      // above — "could you", "can you" — and differ only in the verb: they ask
      // to be told something, not to have something done.
      library('Could you tell me what the policy is for password resets?'),
      library('Can you explain how long a leaver mailbox is kept?'),
      library('Would you clarify who signs off on VPN access?'),
      // "lost" earns Password Reset its vocabulary hit, and the desk also holds
      // a policy on a lost authenticator phone. That question shares the verb
      // and nothing else, so the score floor is what keeps it unhinted.
      library('I lost the phone with my authenticator app on it. What happens now?'),
      // Three printer services fit equally well and the catalogue gives nothing
      // to choose between them. No opinion is the honest opinion.
      library('I need a print code for the colour printer'),
    ],
    1,
  );
});

test('every suggested request carries a hint', () => {
  // These are buttons on the screen. One that produces no hint still reaches
  // the engine — that is the point of the change — but a demonstration button
  // whose service the router cannot name is a button worth rewriting.
  for (const example of REQUEST_EXAMPLES) {
    assert.ok(routeHint(example, CATALOGUE), example);
  }
  assert.equal(routeHint(REQUEST_EXAMPLES[0], CATALOGUE)?.live, true);
});

test('nothing is hinted when the utterance states no need', () => {
  assert.equal(readsAsRequest('Good morning'), false);
  assert.equal(readsAsRequest('Thanks, that answers it'), false);
  assert.equal(routeHint('password', CATALOGUE), null);
  assert.equal(routeHint('I forgot my password', []), null);
});

test('the live service is the one that runs here', () => {
  const hint = routeHint('I forgot my password', CATALOGUE);
  assert.equal(hint?.live, true);
  assert.equal(routeIntake('I forgot my password', CATALOGUE)?.useCase.route, '/nawa/itsd/password-reset');
  assert.equal(routeHint('I want to create an email for a newcomer', CATALOGUE)?.live, false);
});

test('a planned service carries their procedure, verbatim', () => {
  const match = routeIntake('I want to create an email for a newcomer', CATALOGUE)!;
  const steps = procedureSteps(match.useCase);

  assert.equal(steps.length, 7);
  assert.match(steps[0], /^HR or the requester's manager submits a new email account request/);
  // Their terminology, verbatim — including the portal and the approver names.
  assert.match(steps.join(' '), /ITSD Portal/);
  assert.match(steps.join(' '), /Line Manager/);
  // The numbering is the screen's, so no step may arrive carrying its own.
  for (const step of steps) assert.ok(!/^\d/.test(step), step);
});

test('a service of the shared pattern reports how many move with it', () => {
  const match = routeIntake('Please add three members to the finance distribution group', CATALOGUE)!;
  assert.ok(match.sameFamily >= 1, `${match.sameFamily}`);
});

// ---------------------------------------------------------------------------
// The live lane: identity before a privileged write
//
// The model asks for the proofs and the model may not act on them: it is
// read-only, so the run is started by the requester pressing the offer. These
// three are what that press runs on — the reply is read, written into an
// evidence record, and composed into the case the run reads. The shape of that
// case is the customer's policy, not an implementation detail of whichever
// surface assembles it, which is why it is pinned here rather than in a
// component test.
// ---------------------------------------------------------------------------

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
  assert.ok(!neither.items.some((item) => /self-service/i.test(item)), neither.items.join(' · '));
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
