/**
 * NAWA WE — ITSD surface contracts.
 *
 * Everything the two Nawa pages need that is not an API response: the shape of
 * the extracted catalogue, the six business steps of the Password Reset
 * process, and the injectable scenarios. Kept in one file so the coupling
 * points with the backend flow are reviewable in a single place.
 */

/**
 * The app is named WE, for Workspace Engine. The customer wordmark sits to its
 * left and already reads NAWA, so the lockup is "NAWA" + "WE" and the text does
 * not repeat the brand. `NAWA WE` stays the full name in running prose, where
 * "WE" alone would read as the pronoun.
 *
 * Never a competitor name.
 */
export const NAWA_APP_NAME = 'WE';
export const NAWA_APP_SUBTITLE = 'Workspace Engine';
export const NAWA_APP_FULL_NAME = 'NAWA WE';

/**
 * The customer delivered the wordmark as a JPEG on opaque black, unusable on a
 * light surface. The second file is the same artwork with that field keyed out,
 * so the light theme shows a wordmark rather than a black box.
 */
export const NAWA_LOGO = {
  dark: '/assets/nawa/nawa-logo.png',
  light: '/assets/nawa/nawa-logo-transparent.png',
} as const;

/** One row of `assets/nawa/itsd-use-cases.json`, produced by the extractor. */
export interface NawaUseCase {
  sr: number;
  name: string;
  slug: string;
  manual_process: string;
  automated_process: string;
  agents: number | null;
  monthly_volume: number | null;
  automated_minutes: number | null;
  legacy_minutes: number | null;
  status: 'live' | 'planned';
  route: string | null;
  /** Non-null on the six variants of a single directory-change pattern. */
  pattern_group: string | null;
}

export interface NawaCatalog {
  meta: {
    assistant: string;
    source_workbook: string;
    source_sheet: string;
    generated_by: string;
    use_case_count: number;
    planned_agent_total: number;
    source_headers: string[];
    same_pattern_label: string;
  };
  use_cases: NawaUseCase[];
}

/**
 * System lookup. The Password Reset System is created in the `nawa` workspace
 * by the demo migration, so the front resolves it by name over
 * `GET /api/v1/systems` rather than carrying a hardcoded id that would change
 * between environments. `?systemId=<id>` on the detail route overrides it.
 */
export const NAWA_SYSTEM_NAME_MATCH = 'password reset';

/**
 * Flow node ids behind each business step, as authored in
 * `backend/app/resources/flows/nawa_password_reset_v1.json`.
 *
 * The run's `checkpoints` identify nodes by id; a step lights up when a
 * checkpoint's `node_id` contains one of these fragments. Substring matching
 * (not equality) so the kind prefix — `task.` / `decision.` / `hitl.` — is
 * irrelevant and one fragment can cover the decision and the gate that share a
 * name. A node matching nothing still lands in the activity log, so a naming
 * drift degrades the step animation instead of hiding the run.
 *
 * Substring matching makes near-identical ids dangerous: the quality guard is
 * `task.quality_gate` and a bench node is `task.case_quality_guard`. No
 * fragment below may capture a bench node (`task.case_*`) or a sink, or the
 * simulation harness would animate the business steps.
 *
 * The `decision` nodes of each step are deliberately absent: the walker omits
 * their `status` whether the branch won or was never taken, so the projection
 * ignores them outright (see `nawa-run-projection.ts`) and listing them here
 * would suggest they light a step up.
 */
export interface NawaStep {
  index: number;
  title: string;
  detail: string;
  /** How the step is implemented in the flow — shown as a chip. */
  kind: 'llm' | 'gate' | 'simulated' | 'audit';
  nodeIds: string[];
}

export const NAWA_STEPS: readonly NawaStep[] = [
  {
    index: 1,
    title: 'Request intake',
    detail:
      "Call, e-mail or walk-in: the requester's own words are classified into an intent — reset, unlock, expiry, something else — with a confidence score.",
    kind: 'llm',
    nodeIds: ['classify_intent'],
  },
  {
    index: 2,
    title: 'Identity verification',
    detail:
      'The proofs on file (staff ID, line-manager confirmation, security questions) are assessed against policy. On insufficient proof the assistant abstains explicitly and the request goes to a human gate. A grounding check then confirms the assessment is backed by evidence actually on file.',
    kind: 'gate',
    nodeIds: ['verify_identity', 'identity_gate', 'quality_gate'],
  },
  {
    index: 3,
    title: 'Active Directory reset',
    detail:
      'Privileged write, simulated with dry-run semantics — no real AD integration. The directory-outage lane first attempts the automated route to the directory, the only step of the flow that reaches outside the platform.',
    kind: 'simulated',
    nodeIds: ['directory_bridge', 'ad_reset'],
  },
  {
    index: 4,
    title: 'Temporary password',
    detail: 'A dummy temporary password is issued, with a forced change at the next sign-in.',
    kind: 'simulated',
    nodeIds: ['temporary_credential'],
  },
  {
    index: 5,
    title: 'Requester notification',
    detail:
      'The guidance message is drafted in EN/AR from a constrained template, security warning included.',
    kind: 'llm',
    nodeIds: ['draft_user_notice'],
  },
  {
    index: 6,
    title: 'Ticket closure',
    detail: 'Simulated closure, then a write to the audit ledger.',
    kind: 'audit',
    nodeIds: ['close_ticket', 'audit_ledger'],
  },
];

/**
 * One entry of the selector. `scenario` travels to the run as
 * `input_ref.scenario`, which is exactly what the flow's bench decision reads,
 * and `input` carries any extra run input the entry needs.
 *
 * `key` exists because two entries share one scenario: the directory outage and
 * its remediation are the same injected case, told apart only by the extra
 * input, so the scenario id cannot identify the entry on its own.
 *
 * The caller's words and the identity evidence are NOT duplicated here: the
 * flow loads them from the System settings (`scenario_presets`), so the page
 * displays that same source rather than a copy that could drift. Only the
 * short UI label and the positioning line live in the front.
 */
export interface NawaScenario {
  key: string;
  scenario: string;
  label: string;
  proves: string;
  /** Extra `input_ref` fields beyond the scenario, merged as authored. */
  input?: Readonly<Record<string, string | number | boolean>>;
}

/**
 * Only the entries whose `scenario` is also declared in
 * `System.settings.scenarios` are offered, so an entry added here before the
 * flow carries it stays hidden instead of failing in front of the client.
 */
export const NAWA_SCENARIOS: readonly NawaScenario[] = [
  {
    key: 'nominal',
    scenario: 'nominal',
    label: 'Nominal — clear request, complete identity',
    proves: 'The business outcome: the six steps run through and the ticket is closed.',
  },
  {
    key: 'ambiguous',
    scenario: 'ambiguous',
    label: 'Ambiguous — locked account, not a reset',
    proves:
      'The assistant discriminates instead of guessing: the request is routed to another use case and no password is changed.',
  },
  {
    key: 'weak_identity',
    scenario: 'weak_identity',
    label: 'Weak identity — insufficient proof',
    proves:
      "Governance: no privileged write on weak proof. A human gate opens, approval happens in the platform's own screen and the run resumes from there.",
  },
  {
    key: 'ad_unreachable',
    scenario: 'ad_unreachable',
    label: 'Directory outage — the automated route does not answer',
    proves:
      'Failure is a first-class state: nothing is written, nothing is half-applied, the operator is shown the business incident and the exact technical cause stays in the trace.',
  },
  {
    key: 'ad_unreachable_fallback',
    scenario: 'ad_unreachable',
    label: 'Remediation — switch to the manual directory procedure',
    proves:
      'The operator decides, once the incident is visible: the same request runs again through the manual procedure and reaches closure.',
    input: { bridge_fallback: true },
  },
  {
    key: 'quality_guard',
    scenario: 'quality_guard',
    label: 'Quality guard — assessment not grounded',
    proves:
      'The model is confident and the grounding check disagrees: no unattended privileged write on an assessment that no filed evidence supports.',
  },
];

/** Caller case the flow will actually use, read from `System.settings`. */
export interface NawaScenarioPreset {
  label?: string;
  channel?: string;
  requester_name?: string;
  preferred_language?: string;
  request_text?: string;
  identity_evidence?: string;
}

/** Live status of one business step, derived from the run's checkpoints. */
export type NawaStepState = 'pending' | 'running' | 'done' | 'skipped' | 'failed' | 'awaiting';

/** The final states §7.1 requires the page to render. */
export type NawaOutcome =
  | 'closed'
  | 'routed'
  | 'refused'
  | 'awaiting_approval'
  | 'incident'
  | 'quality_hold';

/**
 * The business code the flow puts on `output_ref.outcome` — the authority for
 * the final state. It is what the operator is accountable for, and it separates
 * a governed refusal from a plain technical failure, which the run status alone
 * cannot do.
 */
export const NAWA_OUTCOME_BY_CODE: Readonly<Record<string, NawaOutcome>> = {
  ticket_closed: 'closed',
  routed_to_other_use_case: 'routed',
  approval_refused: 'refused',
  incident_directory_unreachable: 'incident',
  quality_hold_ungrounded_assessment: 'quality_hold',
};

/**
 * Fallback when a run carries no business code: the flow ends on one explicit
 * sink per outcome, so the state can still be read from which sink executed.
 * Ordered most specific first, since only the first match is used.
 */
export const NAWA_OUTCOME_SINKS: readonly { nodeId: string; outcome: NawaOutcome }[] = [
  { nodeId: 'sink.incident', outcome: 'incident' },
  { nodeId: 'sink.quality_hold', outcome: 'quality_hold' },
  { nodeId: 'sink.routed_elsewhere', outcome: 'routed' },
  { nodeId: 'sink.approval_refused', outcome: 'refused' },
  { nodeId: 'sink.ticket_closed', outcome: 'closed' },
];

/**
 * The business outcome the terminal sink puts on `output_ref.outcome`.
 *
 * `label` and `message` are authored and test-locked backend side, so the page
 * renders them instead of keeping a parallel copy that could drift — same rule
 * as the scenario presets. The front only holds a fallback per outcome, for a
 * run that carries no outcome at all.
 */
export interface NawaBusinessOutcome {
  code?: string;
  label?: string;
  message?: string;
  reset_performed?: boolean;
  /** Run input that applies the remediation. Drives a button, never displayed. */
  replay_input?: Record<string, string | number | boolean>;
}

/**
 * `output_ref` keys kept out of the on-screen evidence panel.
 *
 * Anything named `diagnostic_*` is, by backend convention, a value that names a
 * technical component: the automated route to the directory genuinely is not
 * provisioned here, so its raw wording points at our platform rather than at the
 * customer's directory. It must stay reachable — that is the auditability
 * argument — but in the execution journal and the native run trace, not in the
 * headline evidence.
 *
 * `evaluations` lists every branch that was evaluated with its value, so a
 * losing `execute: true` sits right next to the winning `incident: true`. Shown
 * as evidence it would read as a reset that never happened, which is why
 * nothing is ever derived from it: the winning branch comes from
 * `chosen_branch` and from the sink that actually executed. `outcome` is held
 * out only because the banner already renders it.
 */
export function isTraceOnlyOutputKey(key: string): boolean {
  return (
    key.startsWith('_') ||
    key.startsWith('diagnostic_') ||
    key === 'outcome' ||
    key === 'evaluations'
  );
}
