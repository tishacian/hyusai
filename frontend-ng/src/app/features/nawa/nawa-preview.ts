/**
 * A service the rollout has not reached yet, played the way it will run.
 *
 * The desk has 39 services and one of them executes here. Describing the other
 * 38 in a paragraph — "handled by the desk today, automation is planned" — is
 * accurate and useless: it reads as a refusal, and it tells a requester to go
 * back to the portal, which is the opposite of what the workspace is for.
 *
 * So the assistant plays them instead. The steps are the customer's own written
 * procedure, untouched; what this module adds is the reading of that procedure:
 * which step the conversation has already satisfied, which one is a human
 * decision, and what the rest are. The screen then walks it, stops at the
 * decision, and closes — the same grammar as the run that is real.
 *
 * Two lines are not negotiable. Nothing here calls the platform, so no run, no
 * ledger entry and no ticket is created by a preview; and the turn carries a
 * standing "Preview" mark, so the one service that acts for real stays
 * distinguishable from the ones that do not.
 */
import { procedureSteps, type NawaIntakeMatch } from './nawa-intake';

/**
 * What a step is, once read.
 *
 * `intake` is the step that asks the requester to raise the request — already
 * satisfied by the conversation. `approval` is the human decision. Everything
 * else the platform would carry out.
 */
export type PreviewActor = 'intake' | 'approval' | 'automated';

export interface PreviewStep {
  /** The customer's sentence, as written in their workbook. */
  text: string;
  actor: PreviewActor;
}

export interface PreviewPlan {
  service: string;
  /** Who the request is about, when the sentence names them. */
  subject: string | null;
  /** Roles the procedure requires a decision from, in the order it names them. */
  approvers: string[];
  steps: PreviewStep[];
  /** Index of the human decision, or -1 when the procedure has none. */
  gateIndex: number;
  intro: string;
  gateAsk: string;
  approved: string;
  declined: string;
  /** The standing mark, shown for as long as the turn is on screen. */
  note: string;
}

/**
 * The step that tells the requester to raise the request. It names the
 * requester — not IT — and a verb of asking. "IT logs the ticket" is IT's own
 * bookkeeping and stays an ordinary step.
 */
const INTAKE =
  /^(?:the\s+)?(?:requester|user|users|employee|staff|hr or manager|hr|manager|line manager|user or manager|department)\b[^.]{0,70}?\b(?:submits|contacts|raises|requests|reports|informs|sends|logs)\b/i;

/**
 * The step where IT checks that someone approved. It needs a verb of checking
 * next to the word: "IT installs the approved software" is the installation
 * step, not a decision, and "sends credentials to the approver for handover" is
 * a handover.
 */
const APPROVAL =
  /\b(?:verif\w+|confirm\w+|review\w+|obtain\w+|seek\w+|check\w+)\b[^.]{0,70}?\b(?:approval|approvals|authoris\w+|authoriz\w+|sign-?off)\b/i;

/** The roles this desk actually names. Kept to what the workbook contains. */
const ROLES = /\b(Line Manager|IT Approver|HR)\b/g;

/**
 * Who the request is about. Titled names are taken as written; a handful of
 * ways people refer to a third party are taken as they stand. Nothing else is
 * guessed: "for the finance distribution group" is a target, not a person, and
 * reading it as one would put a wrong name on screen in front of an audience.
 */
const TITLED = /\b((?:Mr|Mrs|Ms|Dr|Eng)\.?\s+[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)/;
const THIRD_PARTY =
  /\b(?:for|of)\s+((?:a|an|my|our)\s+(?:new\s+)?(?:joiner|starter|employee|colleague|newcomer|team\s+member|contractor|intern))\b/i;

export function readSubject(utterance: string): string | null {
  const titled = TITLED.exec(utterance);
  if (titled) return titled[1].replace(/\s+/g, ' ').trim();
  const third = THIRD_PARTY.exec(utterance);
  return third ? third[1].replace(/\s+/g, ' ').toLowerCase().trim() : null;
}

/** Reads the procedure: what the conversation covered, what needs a decision. */
export function readSteps(useCase: NawaIntakeMatch['useCase']): PreviewStep[] {
  let gateTaken = false;
  return procedureSteps(useCase).map((text, index) => {
    if (index === 0 && INTAKE.test(text)) return { text, actor: 'intake' as const };
    if (!gateTaken && !INTAKE.test(text) && APPROVAL.test(text)) {
      gateTaken = true;
      return { text, actor: 'approval' as const };
    }
    return { text, actor: 'automated' as const };
  });
}

function rolesIn(steps: readonly PreviewStep[], actor: PreviewActor): string[] {
  const source = steps.filter((step) => step.actor === actor).map((step) => step.text).join(' ');
  const seen: string[] = [];
  for (const match of source.matchAll(ROLES)) {
    if (!seen.includes(match[1])) seen.push(match[1]);
  }
  return seen;
}

/**
 * Who decides. The decision step names them, in the order it names them. Some
 * procedures only say "IT verifies the request is authorised", and there the
 * step that raised the request is the one carrying the role — which is still
 * the right name to put in front of the requester.
 */
export function readApprovers(steps: readonly PreviewStep[]): string[] {
  if (!steps.some((step) => step.actor === 'approval')) return [];
  const named = rolesIn(steps, 'approval');
  return named.length ? named : rolesIn(steps, 'intake');
}

/** "Line Manager and HR", "Line Manager, HR and IT Approver", "an approver". */
function spell(approvers: readonly string[]): string {
  if (approvers.length === 0) return 'an approver';
  if (approvers.length === 1) return approvers[0];
  return `${approvers.slice(0, -1).join(', ')} and ${approvers[approvers.length - 1]}`;
}

const COUNTED = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

function counted(total: number): string {
  return total < COUNTED.length ? COUNTED[total] : String(total);
}

/**
 * Everything the screen needs to play one service. Pure: the caller owns the
 * timing, so a test can assert the whole plan without waiting for it.
 */
export function planPreview(match: NawaIntakeMatch, utterance: string): PreviewPlan {
  const steps = readSteps(match.useCase);
  const approvers = readApprovers(steps);
  const gateIndex = steps.findIndex((step) => step.actor === 'approval');
  const subject = readSubject(utterance);
  const service = match.useCase.name;

  const captured = subject ? `Request captured for ${subject}.` : 'Request captured.';
  const shared = match.sameFamily
    ? ` It shares its approval and directory pattern with ${counted(match.sameFamily)} other ${
        match.sameFamily === 1 ? 'service' : 'services'
      }.`
    : '';

  // Three services in the workbook arrive with an empty procedure column. There
  // is nothing to walk, and inventing steps for them would be the one thing a
  // preview must not do.
  const intro = steps.length
    ? `${service}. ${captured} I am running the desk's ${counted(steps.length)}-step procedure` +
      `${gateIndex >= 0 ? `, and I stop for ${spell(approvers)} before anything changes` : ''}.${shared}`
    : `${service}. ${captured} The desk has not written its procedure for this service yet, ` +
      `so there are no steps to walk — that gap is worth closing before it is automated.${shared}`;

  return {
    service,
    subject,
    approvers,
    steps,
    gateIndex,
    intro,
    gateAsk:
      `Step ${gateIndex + 1} is ${spell(approvers)} approval. ` +
      'Nothing has been changed so far — the remaining steps wait on this decision.',
    approved: 'Approved. I completed the remaining steps and closed the ticket.',
    declined: 'Declined. Nothing was changed, and the request stays with the service desk.',
    note:
      'Preview of the automated service. The steps are the desk’s own procedure, played as it will run once ' +
      'this service is connected here; nothing was executed and no ticket was raised. Password Reset is the ' +
      'service that acts for real in this workspace today.',
  };
}
