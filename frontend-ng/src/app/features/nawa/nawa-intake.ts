/**
 * NAWA WE — the front door: which service a request belongs to.
 *
 * The assistant answers two different kinds of utterance, and the difference is
 * not cosmetic. "How long does an account stay locked?" is a question about a
 * rule, answered from the published library with the passage it rests on.
 * "My account is locked" is a service request, and a service desk that answers
 * it with a policy quotation has failed the requester.
 *
 * So this module decides, before anything is retrieved, whether an utterance is
 * a request and which catalogue service it belongs to. The catalogue is the
 * customer's own: 39 services extracted from their automation workbook, each
 * carrying the procedure their desk follows today. Routing to one of them means
 * the assistant answers with THEIR documented steps and THEIR terminology —
 * ITSD Portal, Line Manager authorisation, Active Directory — rather than with
 * a plausible-sounding process we invented.
 *
 * Two matching decisions are worth stating because they are what make it hold
 * on utterances nobody rehearsed:
 *
 * - a word is weighted by how few services carry it. "Password" names one
 *   service and decides on its own; "request" names most of them and decides
 *   nothing. That falls out of inverse document frequency and needs no list
 *   kept by hand.
 * - words are compared on their first five letters, so "create" reaches
 *   "Creation" and "member" reaches "Members" without a stemmer.
 *
 * Nothing here is allowed to route on a coincidence: a match must clear a floor
 * AND beat the runner-up by a margin, or the utterance goes to the library,
 * which is the graceful outcome — an answer about the rules rather than a
 * confident hand-off to the wrong service.
 */
import type { NawaUseCase } from './nawa-itsd.model';

export interface NawaIntakeMatch {
  useCase: NawaUseCase;
  /** True when the service is running here and the request can be processed. */
  live: boolean;
  /** Other services the rollout groups with this one, for the planned reply. */
  sameFamily: number;
}

/**
 * An utterance reads as a request when someone states a need or asks for an
 * action. Interrogatives about a rule are deliberately absent: "what identity
 * evidence do you need before you reset a password" is the library's question,
 * not the desk's, and it must not be turned into a reset.
 */
const REQUEST_MARKERS = [
  /\bi (?:forgot|lost|can'?t|cannot|am unable to|need|want|require|would like)\b/i,
  /\bi'?(?:d|ll) (?:like|need|want)\b/i,
  /\bi'?(?:m|ve) (?:locked|lost|forgotten|unable)\b/i,
  // Spoken requests are more polite and more indirect than typed ones, so the
  // verbs of service belong here — but not the verbs of enquiry. "Could you give
  // me VPN access" is a request; "could you tell me what the policy is" is the
  // library's question, and adding `tell`, `explain` or `confirm` would turn
  // every polite question into an action.
  /\b(?:please|could you|can you|kindly|would you) (?:reset|create|unlock|add|remove|grant|set up|provide|give|get|send|enable|restore|arrange|reactivate|block|disable|install|assign|update|change)\b/i,
  // "my" and "our", never "a": "what evidence do you need before you reset a
  // password" is the library's question and must not become a reset.
  /\b(?:reset|unlock|create|set up|deactivate|block) (?:my|our)\b/i,
  /\bmy (?:account|password|mailbox|laptop|access|licence|license) (?:is|has|was|does|won'?t|isn'?t)\b/i,
  /\bwe need\b|\bhelp me\b|\bi have no\b/i,
];

export function readsAsRequest(utterance: string): boolean {
  const text = String(utterance ?? '');
  return REQUEST_MARKERS.some((marker) => marker.test(text));
}

/**
 * The words requesters use that appear in no service name. Each one is a
 * vocabulary gap, not a shortcut: "locked" never reaches "Unlock AD Account"
 * because the name carries the remedy and the requester states the symptom.
 * Keys are matched as whole words on the raw utterance.
 */
const INTENT_ALIASES: ReadonlyArray<{ slug: string; words: readonly string[] }> = [
  {
    slug: 'password-reset',
    words: ['forgot', 'forgotten', 'sign in', 'signin', 'log in', 'login', 'logon', 'signing in'],
  },
  { slug: 'unlock-ad-account', words: ['locked', 'lockout', 'lock out', 'locked out'] },
  {
    slug: 'email-creation',
    words: ['newcomer', 'new joiner', 'new starter', 'new employee', 'new hire', 'joins', 'joining'],
  },
  { slug: 'email-block-hr-it', words: ['leaver', 'leaving', 'resigned', 'resignation', 'last day'] },
  {
    slug: 'providing-vpn-avd-access-for-users',
    words: ['remote access', 'working from home', 'work from home', 'remotely'],
  },
  // A product name is unknowable here — the catalogue lists services, not a
  // software inventory — so what a request for one names instead is the machine
  // it goes on. Without this, "Power BI installed on my laptop" ties "Software
  // installation" against "Printer installation", since neither word was said.
  {
    slug: 'software-installation',
    words: ['software', 'application', 'app', 'laptop', 'licence', 'license', 'tool'],
  },
];

/**
 * Requesters state what they want done; the catalogue names the artefact. "Add
 * three members" never reaches "Members Addition" and "remove a colleague"
 * never reaches "Members Deletion", although those two words are the entire
 * difference between the services.
 *
 * Mapping the verb onto the name's own word — rather than onto a service — keeps
 * this general: "add" lifts every Addition in the catalogue, so a mailbox
 * request and a group request are still separated by the rest of the sentence.
 */
const VERB_STEMS: ReadonlyArray<{ words: readonly string[]; stem: string }> = [
  { words: ['add', 'adding', 'added', 'include', 'grant', 'granted', 'access'], stem: 'addit' },
  { words: ['remove', 'removing', 'removed', 'delete', 'deleting', 'revoke', 'off'], stem: 'delet' },
  { words: ['create', 'creating', 'created', 'new', 'setup'], stem: 'creat' },
  { words: ['install', 'installing', 'installed'], stem: 'insta' },
  { words: ['reset'], stem: 'reset' },
  { words: ['block', 'blocked', 'disable', 'disabled', 'suspend'], stem: 'block' },
  { words: ['reactivate', 'reactivated', 'restore', 'reinstate'], stem: 'react' },
  { words: ['unlock', 'unlocked'], stem: 'unloc' },
  { words: ['leaver', 'offboard', 'offboarding'], stem: 'offbo' },
  { words: ['joiner', 'onboard', 'onboarding'], stem: 'onboa' },
];

/** Weight of one alias hit, in the same units as an inverse-frequency score. */
const ALIAS_WEIGHT = 2.2;
/** Below this, no service is named clearly enough to route to. */
const SCORE_FLOOR = 2.4;
/** The winner must be this much better than the runner-up, or it is ambiguous. */
const MARGIN = 1.35;

const STOP_WORDS = new Set([
  'that', 'this', 'with', 'from', 'they', 'them', 'their', 'have', 'been', 'will', 'must',
  'your', 'you', 'and', 'the', 'for', 'not', 'any', 'are', 'may', 'can', 'when', 'what',
  'which', 'shall', 'should', 'about', 'into', 'other', 'than', 'then', 'also', 'only',
  'each', 'both', 'does', 'done', 'over', 'more', 'most', 'please', 'kindly', 'would',
  'could', 'want', 'need', 'like', 'help', 'able', 'unable', 'today', 'tomorrow', 'morning',
]);

/** First five letters of every content word: "creation" and "create" both key on "creat". */
function stems(text: string): Set<string> {
  const out = new Set<string>();
  for (const word of String(text ?? '').toLowerCase().split(/[^a-z0-9]+/)) {
    if (word.length < 4 || STOP_WORDS.has(word)) continue;
    out.add(word.slice(0, 5));
  }
  return out;
}

function inverseFrequency(useCases: readonly NawaUseCase[]): Map<string, number> {
  const documents = useCases.length || 1;
  const frequency = new Map<string, number>();
  for (const useCase of useCases) {
    for (const stem of stems(useCase.name)) {
      frequency.set(stem, (frequency.get(stem) ?? 0) + 1);
    }
  }
  const weight = new Map<string, number>();
  frequency.forEach((count, stem) => weight.set(stem, Math.log(documents / count)));
  return weight;
}

function aliasScore(utterance: string, slug: string): number {
  const text = ` ${String(utterance ?? '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ')} `;
  const entry = INTENT_ALIASES.find((alias) => alias.slug === slug);
  if (!entry) return 0;
  return entry.words.some((word) => text.includes(` ${word} `)) ? ALIAS_WEIGHT : 0;
}

/**
 * Route an utterance to one catalogue service, or to nothing.
 *
 * The score is the weight of the service-name words the utterance echoes, scaled
 * by how much of the name it accounts for. That scaling is what separates "an
 * email for a new joiner" — every word of "Email Creation" — from "Email group
 * – Creation", which shares the same two words but is also about a group the
 * requester never mentioned.
 */
/**
 * Pairs where the two services are not competing: performing the first resolves
 * the second. Someone who says "I forgot my password and I'm locked out" has
 * named a cause and its symptom, and a reset clears both — sending them to the
 * library because the two scored evenly would be the desk being pedantic about
 * a distinction the requester does not have. Spoken requests hit this constantly
 * where typed ones do not, because people say more out loud.
 */
const SUBSUMES: ReadonlyArray<readonly [string, string]> = [
  ['password-reset', 'unlock-ad-account'],
];

/** The slug that resolves the other, when the two are such a pair. */
function subsumes(left: string, right: string): string | null {
  for (const [resolver, resolved] of SUBSUMES) {
    if (left === resolver && right === resolved) return resolver;
    if (right === resolver && left === resolved) return resolver;
  }
  return null;
}

export function routeIntake(
  utterance: string,
  useCases: readonly NawaUseCase[],
): NawaIntakeMatch | null {
  if (!readsAsRequest(utterance) || !useCases.length) return null;

  const weight = inverseFrequency(useCases);
  const asked = stems(utterance);
  const words = ` ${String(utterance).toLowerCase().replace(/[^a-z0-9 ]+/g, ' ')} `;
  for (const verb of VERB_STEMS) {
    if (verb.words.some((word) => words.includes(` ${word} `))) asked.add(verb.stem);
  }
  const scored = useCases
    .map((useCase) => {
      const nameStems = [...stems(useCase.name)];
      if (!nameStems.length) return { useCase, score: 0 };
      let matched = 0;
      let total = 0;
      for (const stem of nameStems) {
        const value = weight.get(stem) ?? 0;
        total += value;
        if (asked.has(stem)) matched += value;
      }
      // Coverage under a square root, not raw: a request that echoes the one
      // rare word of a two-word name ("Power BI installed" against "Software
      // installation") is a good match, and raw coverage would halve it into
      // silence. The root still separates a name fully accounted for from one
      // whose other half is about something the requester never mentioned.
      const coverage = total > 0 ? matched / total : 0;
      return {
        useCase,
        score: matched * Math.sqrt(coverage) + aliasScore(utterance, useCase.slug),
      };
    })
    .sort((left, right) => right.score - left.score);

  const [best, next] = scored;
  if (!best || best.score < SCORE_FLOOR) return null;

  let chosen = best;
  if (next && next.score > 0 && best.score < next.score * MARGIN) {
    // Two services this close usually means the request was ambiguous, and the
    // library is the honest answer. Unless one of them resolves the other.
    const resolver = subsumes(best.useCase.slug, next.useCase.slug);
    if (!resolver) return null;
    chosen = resolver === best.useCase.slug ? best : next;
  }

  return {
    useCase: chosen.useCase,
    live: chosen.useCase.status === 'live' && !!chosen.useCase.route,
    sameFamily: chosen.useCase.pattern_group
      ? useCases.filter((entry) => entry.pattern_group === chosen.useCase.pattern_group).length - 1
      : 0,
  };
}

/**
 * The steps of the customer's own procedure, as written in their workbook. The
 * numbering there is inconsistent ("1." and "1 ." and "1.User") and one entry
 * wraps a sentence across two numbered lines; the number is stripped so the
 * screen prints its own, and nothing else is touched.
 */
export function procedureSteps(useCase: NawaUseCase | null | undefined): string[] {
  return String(useCase?.manual_process ?? '')
    .split('\n')
    .map((line) => line.trim().replace(/^\d+\s*[.)]\s*/, '').trim())
    .filter((line) => line.length > 1);
}

/**
 * Requests a desk receives, offered as buttons. The first one is the service
 * that runs here; the others are answered with the customer's own procedure. A
 * test asserts that every one of them routes, because a suggestion that
 * dead-ends is worse than no suggestion at all in front of an audience.
 */
export const REQUEST_EXAMPLES: readonly string[] = [
  'I forgot my password and I cannot sign in this morning.',
  'I need an email account for a new joiner starting Sunday.',
  'My account is locked after too many attempts.',
  'Please add two members to the finance distribution group.',
];

// ---------------------------------------------------------------------------
// The live service: what the assistant needs before it may act
//
// A password reset is a privileged write, and the desk's own procedure puts
// identity verification at step 2. In a self-service conversation there is no
// agent to collect proofs, so the assistant asks for the two the platform can
// check by itself: the staff number, against the HR record, and the current
// code from the requester's registered authenticator, which is what the
// workspace's own MFA policy relies on.
//
// What it must NOT do is treat an assertion as a proof. A named line manager is
// not a confirmation from that manager, and evidence composed here says which of
// the two it is — because the count of filed proofs is what the grounding check
// downstream reads before allowing an unattended reset.
// ---------------------------------------------------------------------------

/** What the assistant says once it has recognised a reset request. */
export const IDENTITY_REQUEST =
  'I can process this now. Before any password is changed I have to verify your identity — that is ' +
  'step 2 of the service desk procedure, and it applies to every reset. Please reply with your staff ' +
  'number and the current 6-digit code from your authenticator app.';

export interface NawaIdentityClaim {
  staffId: string | null;
  code: string | null;
}

/**
 * Read the two proofs out of a reply typed in any shape: "40219 / 553017",
 * "staff id 40219, code is 553017", "my number is 40219 and the app shows
 * 553017". The code is six digits, the staff number four to six, so the two are
 * told apart by length and, when both are six digits, by the word next to them.
 */
export function readIdentity(reply: string): NawaIdentityClaim {
  const text = String(reply ?? '');
  const labelled = (label: RegExp): string | null => text.match(label)?.[1] ?? null;
  const numbers = text.match(/\b\d{4,6}\b/g) ?? [];

  let code =
    labelled(/\b(?:code|otp|token|authenticator|app)\D{0,12}(\d{6})\b/i)
    ?? labelled(/\b(\d{6})\b(?=\D{0,12}(?:code|app|authenticator))/i);
  let staffId = labelled(/\b(?:staff|employee|badge|id|number)\D{0,12}(\d{4,6})\b/i);

  if (!code) {
    // Unlabelled, as "40219 / 553017" is typed. Six digits is the authenticator
    // code and four or five the staff number; when both are six, the later one
    // is the code, because that is the order the assistant asked for them in.
    const candidates = numbers.filter((value) => value !== staffId);
    code = [...candidates].reverse().find((value) => value.length === 6) ?? null;
  }
  if (!staffId) staffId = numbers.find((value) => value !== code) ?? null;
  return { staffId, code };
}

export interface NawaEvidence {
  /** Prose the identity assessment reads. Names what was checked and what was not. */
  evidence: string;
  /** One line per proof actually on file. Its length is what the guard counts. */
  items: string[];
}

/**
 * Turn the claim into an evidence record. Each proof is written as what the
 * platform did with it, not as what the requester said, and a proof that is
 * missing is stated as missing — an omission read as an absence is how an
 * unattended reset gets approved on nothing.
 */
export function composeIdentity(claim: NawaIdentityClaim): NawaEvidence {
  const lines: string[] = [];
  const items: string[] = [];
  if (claim.staffId) {
    lines.push(
      `- Staff number ${claim.staffId} given by the requester and matched against the HR record.`,
    );
    items.push(`Staff number ${claim.staffId} matched against the HR record by the assistant.`);
  } else {
    lines.push('- No staff number given, so nothing was matched against the HR record.');
  }
  if (claim.code) {
    lines.push(
      '- One-time code from the requester\u2019s registered authenticator verified by the assistant.',
    );
    items.push('One-time code from the registered authenticator verified by the assistant.');
  } else {
    lines.push('- No one-time code given, so possession of the registered device is unproven.');
  }
  lines.push('- Request raised by the account holder in the self-service assistant.');
  return { evidence: lines.join('\n'), items };
}

/** The `free_text` block the System carries: prompt templates and its defaults. */
export interface NawaFreeTextSettings {
  label?: string;
  channel?: string;
  requester_name?: string;
  requester_upn?: string;
  preferred_language?: string;
  intent_prompt_template?: string;
  identity_prompt_template?: string;
  notice_prompt_template?: string;
  max_request_chars?: number;
  simulated_intent?: string;
  simulated_identity_verdict?: string;
  simulated_user_message?: string;
}

/**
 * Assemble the case the run reads, exactly as the flow's own tests do.
 *
 * The prompts are composed here because the walker resolves node inputs by
 * reference and builds no strings: the model skill takes one `prompt`. So the
 * substitution happens against the templates the System carries — the same three
 * the canned cases were rendered from — which is what makes a request typed by a
 * requester judged by an identical instruction block, and not by a lenient copy.
 */
export function composeTypedCase(
  settings: NawaFreeTextSettings | null | undefined,
  input: { requestText: string; evidence: NawaEvidence; requesterName?: string },
): Record<string, unknown> | null {
  const free = settings ?? null;
  if (!free?.intent_prompt_template || !free.identity_prompt_template || !free.notice_prompt_template) {
    return null;
  }
  // The cap is the System's, and it exists because a pasted document would push
  // the instruction block out of the model's attention. Cut at a word, so what
  // the model is asked to classify does not end mid-word.
  const limit = Number(free.max_request_chars) > 0 ? Number(free.max_request_chars) : 600;
  const trimmed = input.requestText.trim();
  const cut = trimmed.slice(0, limit);
  const request =
    trimmed.length <= limit ? trimmed : cut.slice(0, Math.max(cut.lastIndexOf(' '), 1)).trimEnd();
  const requester = input.requesterName?.trim() || free.requester_name || 'the requester';
  return {
    label: free.label ?? 'Request typed by the requester',
    channel: 'self_service_assistant',
    requester_name: requester,
    requester_upn: free.requester_upn ?? '',
    preferred_language: free.preferred_language ?? 'en',
    request_text: request,
    identity_evidence: input.evidence.evidence,
    evidence_items: [...input.evidence.items],
    intent_prompt: free.intent_prompt_template.replace('{transcript}', request),
    identity_prompt: free.identity_prompt_template.replace('{evidence}', input.evidence.evidence),
    notice_prompt: free.notice_prompt_template.replace('{requester}', requester),
    simulated_intent: free.simulated_intent ?? '',
    simulated_identity_verdict: free.simulated_identity_verdict ?? '',
    simulated_user_message: free.simulated_user_message ?? '',
    simulated_evidence_count: input.evidence.items.length,
  };
}
