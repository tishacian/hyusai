/**
 * Ephemeral Flow Builder workbench orchestration.
 *
 * Every dispatch is bound to the exact local snapshot analysed by the server.
 * It deliberately has no dependency on FlowPersistenceService: previewing a
 * dirty graph must neither save a draft nor move the published pointer.
 */
import { DestroyRef, Injectable, computed, effect, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject, firstValueFrom, timer } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import {
  CanonicalApiService,
  type FlowExecutionRuntimeMode,
  type FlowWorkbenchExecutionSurface,
  type FlowWorkbenchRun,
  type Run,
  type SystemFlowWorkbenchGoldenCase,
} from '@app/core/canonical-api.service';
import type { CanonicalFlow } from '@app/core/flow-serializer.service';
import {
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { I18nService } from '@app/core/i18n.service';
import { type I18nKey } from '@app/core/i18n.dict';
import { FlowStore } from './flow.store';
import { ingressInputSchema } from './flow-ingress-prefill';
import {
  draftTestIngressOptions,
  type DraftTestIngressOption,
} from './flow-run.service';
import { flowValidationFingerprint } from './flow-validation.service';

export interface FlowWorkbenchPollPolicy {
  intervalMs: number;
  maxAttempts: number;
  timeoutLabelKey: I18nKey;
}

/** Interactive chat/node previews retain the existing two-minute budget. */
export const FLOW_WORKBENCH_INTERACTIVE_POLL_POLICY: FlowWorkbenchPollPolicy = Object.freeze({
  intervalMs: 500,
  maxAttempts: 240,
  timeoutLabelKey: 'flow.workbench.timeout.interactive',
});

/** FastAPI executes golden BackgroundTasks sequentially. Polling follows the
 * server-owned queue order, one Run at a time, so every case gets its own
 * one-hour window without multiplying read traffic by the batch size.
 */
export const FLOW_WORKBENCH_GOLDEN_POLL_POLICY: FlowWorkbenchPollPolicy = Object.freeze({
  intervalMs: 3_000,
  maxAttempts: 1_200,
  timeoutLabelKey: 'flow.workbench.timeout.golden',
});

/** A Python recipe run may first BUILD its environment (pip install), which
 * the two-minute interactive budget cannot absorb. Thirty minutes covers the
 * env-build ceiling plus the max execution timeout, at a 1 s cadence that
 * matches the recipe status granularity. */
export const FLOW_WORKBENCH_RECIPE_POLL_POLICY: FlowWorkbenchPollPolicy = Object.freeze({
  intervalMs: 1_000,
  maxAttempts: 1_800,
  timeoutLabelKey: 'flow.workbench.timeout.recipe',
});
const TERMINAL_STATUSES = new Set<Run['status']>([
  'completed',
  'failed',
  'cancelled',
  'hitl_pending',
  'debug_pending',
]);
const RUNTIME_MODES = new Set<FlowExecutionRuntimeMode>([
  'dag_strict',
  'dag_overlay',
  'sequential_legacy',
]);

export interface FlowWorkbenchChatMessage {
  id: string;
  role: 'operator' | 'assistant' | 'system';
  content: string;
  runId?: string;
  status?: Run['status'];
  output?: Record<string, unknown>;
}

export interface FlowWorkbenchNodeResult {
  nodeId: string;
  run: FlowWorkbenchRun;
  output: Record<string, unknown>;
  successful: boolean;
}

export interface FlowWorkbenchGoldenCase extends SystemFlowWorkbenchGoldenCase {}

export interface FlowWorkbenchGoldenResult {
  caseId: string;
  expected?: unknown;
  expectedProvided: boolean;
  run: FlowWorkbenchRun;
  actual: Record<string, unknown> | null;
  passed: boolean | null;
  error: string | null;
}

export interface FlowWorkbenchGoldenSummary {
  total: number;
  completed: number;
  pending: number;
  passed: number;
  failed: number;
  unevaluated: number;
}

interface OperationContext {
  generation: number;
  systemId: string;
  revision: number;
  fingerprint: string;
  flow: CanonicalFlow;
  workspaceScope: WorkspaceRequestScope | null;
  selectedIngressId: string;
  fenceIngress: boolean;
}

interface ValidatedOperation extends OperationContext {
  flowSha256: string;
  validationRuntimeMode: FlowExecutionRuntimeMode;
}

class WorkbenchContextChangedError extends Error {
  override readonly name = 'WorkbenchContextChangedError';

  constructor(message: string) {
    super(message);
  }
}

class WorkbenchRejectedError extends Error {
  override readonly name = 'WorkbenchRejectedError';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export type FlowWorkbenchChatInput =
  | { ok: true; value: Record<string, unknown>; messageField: string }
  | { ok: false; messageKey: I18nKey; params?: Record<string, string | number> };

const CHAT_TEXT_FIELDS = ['query', 'message', 'prompt', 'text', 'input'] as const;

function schemaAcceptsText(value: unknown): boolean {
  if (!isRecord(value)) return true;
  const type = value['type'];
  return type === undefined
    || type === 'string'
    || (Array.isArray(type) && type.includes('string'));
}

/** Shape a chat message against the selected source's authored input schema.
 * Additional JSON is merged at the input_ref root; it is never hidden below a
 * synthetic `context` property. Closed schemas therefore receive no invented
 * `message`/`context` keys, while legacy open ingresses keep `query`.
 */
export function buildFlowWorkbenchChatInput(
  flow: CanonicalFlow,
  ingressId: string,
  message: string,
  additionalInputRef: Record<string, unknown>,
): FlowWorkbenchChatInput {
  const source = flow.nodes.find((node) => node.id === ingressId && node.kind === 'source');
  if (!source) {
    return { ok: false, messageKey: 'flow.workbench.error.entry_missing' };
  }
  // A port-derived schema states no `additionalProperties`, which every test
  // below reads as open — the same reading publication gives it.
  const { schema } = ingressInputSchema(source);
  const properties = isRecord(schema['properties']) ? schema['properties'] : null;

  let messageField: string | null = null;
  if (properties) {
    messageField = CHAT_TEXT_FIELDS.find(
      (key) => Object.prototype.hasOwnProperty.call(properties, key)
        && schemaAcceptsText(properties[key]),
    ) ?? null;
    const required = Array.isArray(schema['required']) ? schema['required'] : [];
    messageField ??= required.find(
      (key): key is string => typeof key === 'string'
        && Object.prototype.hasOwnProperty.call(properties, key)
        && schemaAcceptsText(properties[key]),
    ) ?? null;
    messageField ??= Object.keys(properties).find((key) => schemaAcceptsText(properties[key])) ?? null;
  }
  if (!messageField && schema['additionalProperties'] !== false) messageField = 'query';
  if (!messageField) {
    return {
      ok: false,
      messageKey: 'flow.workbench.error.entry_no_text',
    };
  }

  const inputRef = structuredClone(additionalInputRef);
  if (schema['additionalProperties'] === false && properties) {
    const unknownKeys = Object.keys(inputRef).filter(
      (key) => key !== '_debug' && !Object.prototype.hasOwnProperty.call(properties, key),
    );
    if (unknownKeys.length > 0) {
      return {
        ok: false,
        messageKey: 'flow.workbench.error.entry_rejects',
        params: { keys: unknownKeys.join(', ') },
      };
    }
  }
  inputRef[messageField] = message;

  const required = Array.isArray(schema['required'])
    ? schema['required'].filter((key): key is string => typeof key === 'string')
    : [];
  const missing = required.filter((key) => !Object.prototype.hasOwnProperty.call(inputRef, key));
  if (missing.length > 0) {
    return {
      ok: false,
      messageKey: 'flow.workbench.error.entry_requires',
      params: { keys: missing.join(', ') },
    };
  }

  return {
    ok: true,
    value: inputRef,
    messageField,
  };
}

function runtimeMode(value: unknown): FlowExecutionRuntimeMode | null {
  return typeof value === 'string' && RUNTIME_MODES.has(value as FlowExecutionRuntimeMode)
    ? value as FlowExecutionRuntimeMode
    : null;
}

function executionMetadata(run: Run): Record<string, unknown> {
  const input = isRecord(run.input_ref) ? run.input_ref : {};
  return isRecord(input['execution']) ? input['execution'] : {};
}

function outputText(output: Record<string, unknown>, fallback: string): string {
  for (const key of ['answer', 'message', 'text', 'result']) {
    if (typeof output[key] === 'string' && output[key]) return output[key] as string;
  }
  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return fallback;
  }
}

@Injectable()
export class FlowWorkbenchService {
  private readonly i18n = inject(I18nService);
  private readonly store = inject(FlowStore);
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService, { optional: true });
  private readonly destroyRef = inject(DestroyRef);
  private readonly cancelled = new Subject<void>();
  private generation = 0;
  private messageSequence = 0;
  private disposed = false;
  private unregisterWorkspaceReset: (() => void) | undefined;

  readonly systemId = signal<string | null>(null);
  readonly selectedIngressId = signal('');
  readonly ingresses = computed<DraftTestIngressOption[]>(() =>
    draftTestIngressOptions(this.store.snapshot()),
  );
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly runtimeMode = signal<FlowExecutionRuntimeMode | null>(null);
  readonly chatMessages = signal<FlowWorkbenchChatMessage[]>([]);
  readonly nodeResult = signal<FlowWorkbenchNodeResult | null>(null);
  readonly goldenResults = signal<FlowWorkbenchGoldenResult[]>([]);
  readonly goldenSummary = computed<FlowWorkbenchGoldenSummary>(() => {
    const results = this.goldenResults();
    const finished = results.filter((item) => ['completed', 'failed', 'cancelled'].includes(item.run.status));
    const pending = results.length - finished.length;
    return {
      total: results.length,
      completed: results.length - pending,
      pending,
      passed: results.filter((item) => item.passed === true).length,
      failed: results.filter((item) => item.passed === false).length,
      unevaluated: finished.filter((item) => item.passed === null).length,
    };
  });

  constructor() {
    let observedRevision = this.store.revision();
    effect(() => {
      const revision = this.store.revision();
      if (revision === observedRevision || this.disposed) return;
      observedRevision = revision;
      // Every result and runtime label belongs to one exact graph fingerprint.
      // A local edit, reload or rollback invalidates it immediately.
      this.invalidateRequests();
      this.clearEphemeralState();
    });
    this.unregisterWorkspaceReset = this.workspace?.registerContextReset(() => {
      this.bindSystem(null);
    });
    this.destroyRef.onDestroy(() => this.dispose());
  }

  bindSystem(systemId: string | null): void {
    if (this.disposed) return;
    this.invalidateRequests();
    this.systemId.set(systemId);
    this.clearEphemeralState();
  }

  reset(): void {
    if (this.disposed) return;
    this.invalidateRequests();
    this.clearEphemeralState();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.invalidateRequests();
    this.systemId.set(null);
    this.clearEphemeralState();
    this.unregisterWorkspaceReset?.();
    this.unregisterWorkspaceReset = undefined;
    this.cancelled.complete();
  }

  async runChat(
    message: string,
    additionalInputRef: Record<string, unknown> = {},
    acknowledgeRealSideEffects = false,
  ): Promise<FlowWorkbenchRun | null> {
    const normalizedMessage = message.trim();
    if (!normalizedMessage) {
      this.error.set(this.i18n.t('flow.workbench.error.message'));
      return null;
    }
    if (!this.requireRealSideEffectsAcknowledgement(acknowledgeRealSideEffects)) return null;
    const operation = this.beginOperation(true);
    if (!operation) return null;
    this.appendChat({ role: 'operator', content: normalizedMessage });

    try {
      const validated = await this.validate(operation, true);
      const ingress = this.resolveIngress(validated);
      const shapedInput = buildFlowWorkbenchChatInput(
        validated.flow,
        ingress.ingress_id,
        normalizedMessage,
        additionalInputRef,
      );
      if (!shapedInput.ok) throw new WorkbenchRejectedError(
          this.i18n.t(shapedInput.messageKey, shapedInput.params),
        );
      const initial = await this.awaitRequest(
        this.canonical.triggerSystemFlowWorkbenchPreviewRun(validated.systemId, {
          acknowledge_real_side_effects: true,
          flow_definition: validated.flow as unknown as Record<string, unknown>,
          expected_flow_sha256: validated.flowSha256,
          input_ref: shapedInput.value,
          ...ingress,
        }),
      );
      this.assertCurrent(validated);
      this.assertInitialRun(initial, validated, 'builder_preview');
      const run = await this.pollRun(initial, validated);
      const output = isRecord(run.output_ref) ? run.output_ref : {};
      const failed = run.status !== 'completed';
      this.appendChat({
        role: failed ? 'system' : 'assistant',
        content: failed
          ? run.error || `Preview stopped with status ${run.status}.`
          : outputText(output, this.i18n.t('flow.workbench.error.unserialisable')),
        runId: run.id,
        status: run.status,
        output,
      });
      return run;
    } catch (error: unknown) {
      this.reportOperationError(operation, error, true);
      return null;
    } finally {
      this.finishOperation(operation);
    }
  }

  async runSelectedNode(
    nodeId: string,
    input: Record<string, unknown>,
    acknowledgeRealSideEffects = false,
    pollPolicy: FlowWorkbenchPollPolicy = FLOW_WORKBENCH_INTERACTIVE_POLL_POLICY,
  ): Promise<FlowWorkbenchRun | null> {
    const normalizedNodeId = nodeId.trim();
    if (!normalizedNodeId) {
      this.error.set(this.i18n.t('flow.workbench.error.node'));
      return null;
    }
    if (!this.requireRealSideEffectsAcknowledgement(acknowledgeRealSideEffects)) return null;
    const operation = this.beginOperation(false);
    if (!operation) return null;
    this.nodeResult.set(null);

    try {
      // The backend shape-checks the full snapshot but executes and validates
      // only its isolated source → selected Skill → sink projection. This lets
      // an operator repair one node while unrelated dirty branches are still
      // incomplete, without weakening the hash or context fence.
      const validated = await this.validate(operation, false);
      const initial = await this.awaitRequest(
        this.canonical.triggerSystemFlowWorkbenchNodeRun(validated.systemId, {
          acknowledge_real_side_effects: true,
          flow_definition: validated.flow as unknown as Record<string, unknown>,
          expected_flow_sha256: validated.flowSha256,
          node_id: normalizedNodeId,
          input_ref: structuredClone(input),
        }),
      );
      this.assertCurrent(validated);
      this.assertInitialRun(initial, validated, 'node_preview');
      this.nodeResult.set({
        nodeId: normalizedNodeId,
        run: initial,
        output: isRecord(initial.output_ref) ? initial.output_ref : {},
        successful: false,
      });
      const run = await this.pollRun(initial, validated, pollPolicy);
      const result: FlowWorkbenchNodeResult = {
        nodeId: normalizedNodeId,
        run,
        output: isRecord(run.output_ref) ? run.output_ref : {},
        successful: run.status === 'completed',
      };
      this.nodeResult.set(result);
      return run;
    } catch (error: unknown) {
      this.reportOperationError(operation, error);
      return null;
    } finally {
      this.finishOperation(operation);
    }
  }

  async runGoldenSet(
    cases: FlowWorkbenchGoldenCase[],
    acknowledgeRealSideEffects = false,
  ): Promise<FlowWorkbenchGoldenResult[] | null> {
    if (cases.length < 1 || cases.length > 20) {
      this.error.set(this.i18n.t('flow.workbench.error.golden_size'));
      return null;
    }
    const ids = cases.map((item) => item.id);
    if (ids.some((id) => !id || id !== id.trim()) || new Set(ids).size !== ids.length) {
      this.error.set(this.i18n.t('flow.workbench.error.golden_ids'));
      return null;
    }
    if (!this.requireRealSideEffectsAcknowledgement(acknowledgeRealSideEffects)) return null;
    const operation = this.beginOperation(true);
    if (!operation) return null;
    this.goldenResults.set([]);
    const capturedCases = structuredClone(cases);

    try {
      const validated = await this.validate(operation, true);
      const ingress = this.resolveIngress(validated);
      const batch = await this.awaitRequest(
        this.canonical.triggerSystemFlowWorkbenchGoldenRuns(validated.systemId, {
          acknowledge_real_side_effects: true,
          flow_definition: validated.flow as unknown as Record<string, unknown>,
          expected_flow_sha256: validated.flowSha256,
          cases: capturedCases,
          ...ingress,
        }),
      );
      this.assertCurrent(validated);
      if (batch.flow_sha256 !== validated.flowSha256 || batch.runs.length !== capturedCases.length) {
        throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.golden_mismatch'));
      }

      const casesById = new Map(capturedCases.map((item) => [item.id, item]));
      const queued = batch.runs.map((run) => {
        this.assertInitialRun(run, validated, 'golden_preview');
        const caseId = executionMetadata(run)['golden_case_id'];
        if (typeof caseId !== 'string' || !casesById.has(caseId)) {
          throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.golden_identity'));
        }
        const goldenCase = casesById.get(caseId)!;
        return {
          goldenCase,
          initial: run,
          result: {
            caseId,
            ...(Object.prototype.hasOwnProperty.call(goldenCase, 'expected')
              ? { expected: structuredClone(goldenCase.expected) }
              : {}),
            expectedProvided: Object.prototype.hasOwnProperty.call(goldenCase, 'expected'),
            run,
            actual: null,
            passed: null,
            error: null,
          } satisfies FlowWorkbenchGoldenResult,
        };
      });
      if (new Set(queued.map((item) => item.result.caseId)).size !== capturedCases.length) {
        throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.golden_duplicates'));
      }
      this.goldenResults.set(queued.map((item) => item.result));

      for (const { goldenCase, initial } of queued) {
        const run = await this.pollRun(
          initial,
          validated,
          FLOW_WORKBENCH_GOLDEN_POLL_POLICY,
        );
        const output = isRecord(run.output_ref) ? run.output_ref : {};
        const result = run.test_result;
        const verdict = result?.case_id === goldenCase.id && result.batch_id === batch.batch_id
          ? result.verdict : null;
        const passed = run.status === 'completed' && (verdict === 'passed' || verdict === 'failed')
          ? verdict === 'passed' : null;
        this.replaceGoldenResult(goldenCase.id, {
          run,
          actual: output,
          passed,
          error: run.status === 'failed' || run.status === 'cancelled'
            ? run.error || this.i18n.t('flow.workbench.error.run_status', { status: run.status })
            : passed === false ? this.i18n.t('flow.workbench.error.golden_diff') : null,
        });
      }
      return this.goldenResults();
    } catch (error: unknown) {
      this.reportOperationError(operation, error);
      return null;
    } finally {
      this.finishOperation(operation);
    }
  }

  private beginOperation(fenceIngress: boolean): OperationContext | null {
    if (this.disposed) return null;
    if (this.busy()) {
      this.error.set(this.i18n.t('flow.workbench.error.busy'));
      return null;
    }
    const systemId = this.systemId();
    if (!systemId) {
      this.error.set(this.i18n.t('flow.workbench.error.no_system'));
      return null;
    }
    const flow = this.store.snapshot();
    const operation: OperationContext = {
      generation: ++this.generation,
      systemId,
      revision: this.store.revision(),
      fingerprint: flowValidationFingerprint(flow),
      flow,
      workspaceScope: this.workspace?.captureRequestScope() ?? null,
      selectedIngressId: this.selectedIngressId(),
      fenceIngress,
    };
    this.busy.set(true);
    this.error.set(null);
    return operation;
  }

  private async validate(
    operation: OperationContext,
    requireExecutable: boolean,
  ): Promise<ValidatedOperation> {
    const response = await this.awaitRequest(
      this.canonical.validateSystemFlow(
        operation.systemId,
        operation.flow as unknown as Record<string, unknown>,
      ),
    );
    this.assertCurrent(operation);
    if (
      requireExecutable
      && (!response.valid || response.issues.some((issue) => issue.level === 'error'))
    ) {
      throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.diagnostics'));
    }
    if (!/^[0-9a-f]{64}$/.test(response.flow_sha256)) {
      throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.digest'));
    }
    const mode = runtimeMode(response.runtime_mode);
    if (!mode) {
      throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.runtime_unsupported'));
    }
    this.runtimeMode.set(mode);
    if (mode === 'sequential_legacy') {
      throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.runtime_legacy'));
    }
    return {
      ...operation,
      flowSha256: response.flow_sha256,
      validationRuntimeMode: mode,
    };
  }

  private resolveIngress(operation: ValidatedOperation): {
    ingress_id: string;
    kind: DraftTestIngressOption['kind'];
  } {
    const options = draftTestIngressOptions(operation.flow);
    if (options.length === 0) {
      throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.no_entry'));
    }
    const selected = operation.selectedIngressId
      ? options.find((option) => option.ingress_id === operation.selectedIngressId)
      : options.length === 1 ? options[0] : null;
    if (!selected) {
      throw new WorkbenchRejectedError(
        options.length > 1
          ? this.i18n.t('flow.workbench.error.choose_entry', { count: options.length })
          : this.i18n.t('flow.workbench.error.entry_gone'),
      );
    }
    return { ingress_id: selected.ingress_id, kind: selected.kind };
  }

  private assertInitialRun(
    run: FlowWorkbenchRun,
    operation: ValidatedOperation,
    expectedSurface: FlowWorkbenchExecutionSurface,
  ): void {
    const sourceSha = run.source_flow_sha256 || executionMetadata(run)['source_flow_sha256'];
    const mode = runtimeMode(run.runtime_mode ?? executionMetadata(run)['runtime_mode']);
    if (
      run.system_id !== operation.systemId
      || run.execution_surface !== expectedSurface
      || sourceSha !== operation.flowSha256
      || !/^[0-9a-f]{64}$/.test(run.flow_sha256)
      || !mode
      || mode === 'sequential_legacy'
    ) {
      throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.evidence'));
    }
    this.runtimeMode.set(mode);
  }

  private async pollRun(
    initial: FlowWorkbenchRun,
    operation: ValidatedOperation,
    policy: FlowWorkbenchPollPolicy = FLOW_WORKBENCH_INTERACTIVE_POLL_POLICY,
  ): Promise<FlowWorkbenchRun> {
    if (TERMINAL_STATUSES.has(initial.status)) return initial;
    for (let attempt = 0; attempt < policy.maxAttempts; attempt += 1) {
      this.assertCurrent(operation);
      const projected = await this.awaitRequest(this.canonical.getRun(initial.id));
      this.assertCurrent(operation);
      if (projected) {
        if (projected.id !== initial.id || projected.system_id !== operation.systemId) {
          throw new WorkbenchRejectedError(this.i18n.t('flow.workbench.error.poll_identity'));
        }
        const merged = {
          ...initial,
          ...projected,
          execution_surface: initial.execution_surface,
          flow_sha256: initial.flow_sha256,
          source_flow_sha256: initial.source_flow_sha256,
          runtime_mode: initial.runtime_mode,
        } satisfies FlowWorkbenchRun;
        if (TERMINAL_STATUSES.has(merged.status)) return merged;
      }
      await this.awaitRequest(timer(policy.intervalMs));
    }
    const timeoutMinutes = Math.round((policy.intervalMs * policy.maxAttempts) / 60_000);
    throw new WorkbenchRejectedError(
      this.i18n.t('flow.workbench.error.timeout', {
        label: this.i18n.t(policy.timeoutLabelKey),
        minutes: timeoutMinutes,
      }),
    );
  }

  private assertCurrent(operation: OperationContext): void {
    if (
      this.disposed
      || operation.generation !== this.generation
      || this.systemId() !== operation.systemId
      || this.store.revision() !== operation.revision
      || flowValidationFingerprint(this.store.snapshot()) !== operation.fingerprint
      || (operation.fenceIngress && this.selectedIngressId() !== operation.selectedIngressId)
      || (
        operation.workspaceScope !== null
        && this.workspace !== null
        && !this.workspace.isRequestScopeCurrent(operation.workspaceScope)
      )
    ) {
      throw new WorkbenchContextChangedError(
        this.i18n.t('flow.workbench.error.context_changed'),
      );
    }
  }

  private async awaitRequest<T>(request: import('rxjs').Observable<T>): Promise<T> {
    return firstValueFrom(request.pipe(takeUntil(this.cancelled)));
  }

  private finishOperation(operation: OperationContext): void {
    if (operation.generation === this.generation) this.busy.set(false);
  }

  private reportOperationError(
    operation: OperationContext,
    error: unknown,
    appendToChat = false,
  ): void {
    if (operation.generation !== this.generation || this.disposed) return;
    const message = this.errorMessage(error);
    this.error.set(message);
    if (appendToChat) this.appendChat({ role: 'system', content: message });
  }

  private errorMessage(error: unknown): string {
    if (error instanceof WorkbenchContextChangedError || error instanceof WorkbenchRejectedError) {
      return error.message;
    }
    if (error instanceof HttpErrorResponse) {
      const detail = isRecord(error.error) ? error.error['detail'] : null;
      if (isRecord(detail) && typeof detail['message'] === 'string') return detail['message'];
      if (typeof detail === 'string' && detail) return detail;
      return this.i18n.t('flow.workbench.error.http', { status: error.status || 'network' });
    }
    return error instanceof Error && error.message
      ? error.message
      : this.i18n.t('flow.workbench.error.failed');
  }

  private appendChat(message: Omit<FlowWorkbenchChatMessage, 'id'>): void {
    this.chatMessages.update((messages) => [
      ...messages,
      { ...message, id: `workbench-message-${++this.messageSequence}` },
    ]);
  }

  private replaceGoldenResult(
    caseId: string,
    patch: Pick<FlowWorkbenchGoldenResult, 'run' | 'actual' | 'passed' | 'error'>,
  ): void {
    this.goldenResults.update((results) => results.map((item) =>
      item.caseId === caseId ? { ...item, ...patch } : item,
    ));
  }

  private invalidateRequests(): void {
    this.generation += 1;
    this.cancelled.next();
    this.busy.set(false);
  }

  private requireRealSideEffectsAcknowledgement(acknowledged: boolean): acknowledged is true {
    if (acknowledged === true) return true;
    this.error.set(this.i18n.t('flow.workbench.error.consent'));
    return false;
  }

  private clearEphemeralState(): void {
    this.selectedIngressId.set('');
    this.busy.set(false);
    this.error.set(null);
    this.runtimeMode.set(null);
    this.chatMessages.set([]);
    this.nodeResult.set(null);
    this.goldenResults.set([]);
  }
}
