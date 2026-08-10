/** In-builder workbench for unsaved Flow previews, isolated Skills and golden sets. */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';
import type { CanonicalFlowNode } from '@app/core/flow-serializer.service';
import {
  FlowWorkbenchService,
  type FlowWorkbenchGoldenCase,
} from './flow-workbench.service';
import { runtimeModeLabel } from './flow-manifest.service';
import { FlowStore } from './flow.store';

type WorkbenchTab = 'chat' | 'node' | 'golden';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function identity(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/** Mirrors the backend's fail-closed Skill-binding acceptance boundary. */
export function isRunnableWorkbenchSkillNode(
  node: CanonicalFlowNode | null,
): node is CanonicalFlowNode {
  if (!node || (node.kind ?? 'task') !== 'task') return false;
  const config = isRecord(node.config) ? node.config : {};
  const data = isRecord(node.data) ? node.data : {};
  const nestedSkill = isRecord(config['skill']) ? config['skill'] : {};
  const slugs = new Set([
    identity(config['skill_slug']),
    identity(nestedSkill['slug']),
    identity(data['bound_skill_slug']),
    identity(data['skill_slug']),
  ].filter((value): value is string => value !== null));
  return slugs.size === 1;
}

export type WorkbenchParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; message: string };

export function parseWorkbenchObject(text: string): WorkbenchParseResult<Record<string, unknown>> {
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { ok: false, message: 'Enter a JSON object.' };
    }
    return { ok: true, value: value as Record<string, unknown> };
  } catch {
    return { ok: false, message: 'Enter valid JSON.' };
  }
}

export function parseWorkbenchGoldenSet(
  text: string,
): WorkbenchParseResult<FlowWorkbenchGoldenCase[]> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, message: 'Enter a valid JSON array.' };
  }
  if (!Array.isArray(value) || value.length < 1 || value.length > 20) {
    return { ok: false, message: 'A golden set must contain between 1 and 20 cases.' };
  }
  const cases: FlowWorkbenchGoldenCase[] = [];
  const ids = new Set<string>();
  for (const [index, item] of value.entries()) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      return { ok: false, message: `Golden case ${index + 1} must be an object.` };
    }
    const record = item as Record<string, unknown>;
    const id = typeof record['id'] === 'string' ? record['id'] : '';
    const inputRef = record['input_ref'];
    if (!id || id !== id.trim() || ids.has(id)) {
      return { ok: false, message: 'Golden case ids must be unique, non-empty and trimmed.' };
    }
    if (!inputRef || typeof inputRef !== 'object' || Array.isArray(inputRef)) {
      return { ok: false, message: `Golden case “${id}” needs an input_ref object.` };
    }
    ids.add(id);
    cases.push({
      id,
      input_ref: inputRef as Record<string, unknown>,
      ...(Object.prototype.hasOwnProperty.call(record, 'expected')
        ? { expected: record['expected'] }
        : {}),
    });
  }
  return { ok: true, value: cases };
}

const DEFAULT_NODE_INPUT = `{
  "prompt": "",
  "context": {}
}`;

const DEFAULT_GOLDEN_SET = `[
  {
    "id": "case-1",
    "input_ref": { "query": "" },
    "expected": { "answer": "" }
  }
]`;

@Component({
  selector: 'app-flow-workbench-panel',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './flow-workbench-panel.component.scss',
  template: `
    @if (open()) {
      <section class="ck-workbench" aria-label="Local Flow workbench">
        <header class="ck-workbench__header">
          <div class="ck-workbench__identity">
            <strong>Try this Flow before saving it</strong>
            <span class="ck-workbench__status">
              Runs {{ store.dirty() ? 'your unsaved canvas' : 'the current canvas' }}
              exactly as it is. Nothing is saved or published — but the Skills are
              real and so are their side effects.
            </span>
            <button
              type="button"
              class="ck-workbench__detail-toggle"
              [attr.aria-expanded]="detailOpen()"
              aria-controls="ck-workbench-detail"
              (click)="detailOpen.set(!detailOpen())"
            >
              What this run touches
            </button>
          </div>

          <div class="ck-workbench__tabs" role="tablist" aria-label="Workbench mode">
            <button type="button" role="tab" [attr.aria-selected]="tab() === 'chat'" (click)="tab.set('chat')">
              <app-icon name="message-square" [size]="13" /> Chat
            </button>
            <button type="button" role="tab" [attr.aria-selected]="tab() === 'node'" (click)="tab.set('node')">
              <app-icon name="target" [size]="13" /> Node
            </button>
            <button type="button" role="tab" [attr.aria-selected]="tab() === 'golden'" (click)="tab.set('golden')">
              <app-icon name="list-checks" [size]="13" /> Golden set
            </button>
          </div>

          <button type="button" class="ck-workbench__close" aria-label="Close local workbench" (click)="close.emit()">
            <app-icon name="x" [size]="15" />
          </button>
        </header>

        <dl id="ck-workbench-detail" class="ck-workbench__detail" [hidden]="!detailOpen()">
          <dt>Graph</dt>
          <dd>
            {{ store.dirty() ? 'The unsaved canvas' : 'The current canvas' }}, sent
            hash-bound so the server refuses anything that drifted since dispatch.
          </dd>
          <dt>Saving</dt>
          <dd>Autosave stays paused for as long as this panel is open.</dd>
          <dt>Publishing</dt>
          <dd>
            Never published. The published version and the ingress serving it do
            not move.
          </dd>
          <dt>Side effects</dt>
          <dd>
            Real Skills run. Whatever they write, send or call outside Agentium
            happens for real.
          </dd>
          <dt>Runtime</dt>
          <dd [attr.data-mode]="workbench.runtimeMode() ?? 'unknown'">{{ runtimeLabel() }}</dd>
        </dl>

        <label class="ck-workbench__consent">
          <input
            type="checkbox"
            [checked]="realSideEffectsAcknowledged()"
            (change)="onAcknowledgementChange($event)"
          />
          <span>
            I understand this preview invokes real Skills and may cause external side effects.
            Confirmation is valid only for the current Flow revision.
          </span>
        </label>

        @if ((tab() === 'chat' || tab() === 'golden') && workbench.ingresses().length > 0) {
          <div class="ck-workbench__ingress">
            <label for="flow-workbench-ingress">Ingress</label>
            @if (workbench.ingresses().length === 1) {
              <span>
                {{ workbench.ingresses()[0].label }} · {{ workbench.ingresses()[0].kind }}
              </span>
            } @else {
              <select
                id="flow-workbench-ingress"
                [value]="workbench.selectedIngressId()"
                (change)="onIngressChange($event)"
              >
                <option value="" disabled>Choose one ingress…</option>
                @for (ingress of workbench.ingresses(); track ingress.ingress_id) {
                  <option [value]="ingress.ingress_id">
                    {{ ingress.label }} · {{ ingress.kind }}
                  </option>
                }
              </select>
            }
          </div>
        }

        <div class="ck-workbench__body">
          @switch (tab()) {
            @case ('chat') {
              <div class="ck-workbench__chat-log" aria-live="polite">
                @for (message of workbench.chatMessages(); track message.id) {
                  <article class="ck-workbench__message" [attr.data-role]="message.role">
                    <span>{{ message.role }}</span>
                    <p>{{ message.content }}</p>
                    @if (message.runId) {
                      <code>{{ message.runId.slice(0, 8) }} · {{ message.status }}</code>
                    }
                    @if (message.output; as output) {
                      <pre class="ck-workbench__output-ref">{{ json(output) }}</pre>
                    }
                  </article>
                } @empty {
                  <p class="ck-workbench__empty">
                    Test the exact graph in the canvas. The Flow is validated and hash-bound,
                    but it is not saved or published.
                  </p>
                }
              </div>
              <div class="ck-workbench__composer">
                <label>
                  <span>Additional input_ref (JSON)</span>
                  <textarea rows="3" spellcheck="false" [value]="chatContextText()" (input)="chatContextText.set(textValue($event))"></textarea>
                </label>
                <label class="ck-workbench__prompt">
                  <span>Message</span>
                  <textarea rows="3" [value]="chatText()" (input)="chatText.set(textValue($event))" (keydown.control.enter)="runChatFromKeyboard($event)" (keydown.meta.enter)="runChatFromKeyboard($event)"></textarea>
                </label>
                <button type="button" class="is-primary" [disabled]="!canRunChat()" (click)="runChat()">
                  <app-icon [name]="workbench.busy() ? 'loader-2' : 'send'" [size]="14" />
                  {{ workbench.busy() ? 'Running…' : 'Send preview' }}
                </button>
              </div>
            }

            @case ('node') {
              <div class="ck-workbench__node-grid">
                <div class="ck-workbench__node-target">
                  <span>Selected Skill node</span>
                  @if (selectedRunnableNode(); as node) {
                    <strong>{{ node.label || node.id }}</strong>
                    <code>{{ node.id }}</code>
                  } @else {
                    <p>Select one task node with an executable Skill binding.</p>
                  }
                </div>
                <label>
                  <span>Manual input_ref (JSON)</span>
                  <textarea rows="8" spellcheck="false" [value]="nodeInputText()" (input)="nodeInputText.set(textValue($event))"></textarea>
                </label>
                <button type="button" class="is-primary" [disabled]="!canRunNode()" (click)="runNode()">
                  <app-icon [name]="workbench.busy() ? 'loader-2' : 'play'" [size]="14" />
                  {{ workbench.busy() ? 'Running…' : 'Run selected node' }}
                </button>
                @if (workbench.nodeResult(); as result) {
                  <div class="ck-workbench__result" [attr.data-status]="result.run.status">
                    <strong>{{ result.run.status }} · {{ result.run.id.slice(0, 8) }}</strong>
                    @if (result.run.error) { <p>{{ result.run.error }}</p> }
                    <pre>{{ json(result.output) }}</pre>
                  </div>
                }
              </div>
            }

            @case ('golden') {
              <div class="ck-workbench__golden-grid">
                <label>
                  <span>Golden cases (JSON · max 20)</span>
                  <textarea rows="9" spellcheck="false" [value]="goldenText()" (input)="goldenText.set(textValue($event))"></textarea>
                </label>
                <div class="ck-workbench__golden-actions">
                  <button type="button" class="is-primary" [disabled]="!canRunGolden()" (click)="runGolden()">
                    <app-icon [name]="workbench.busy() ? 'loader-2' : 'play'" [size]="14" />
                    {{ workbench.busy() ? 'Running set…' : 'Run golden set' }}
                  </button>
                  @if (workbench.goldenSummary().total > 0) {
                    <span>
                      {{ workbench.goldenSummary().completed }}/{{ workbench.goldenSummary().total }} complete ·
                      {{ workbench.goldenSummary().passed }} pass ·
                      {{ workbench.goldenSummary().failed }} fail
                    </span>
                  }
                </div>
                @if (workbench.goldenResults().length > 0) {
                  <div class="ck-workbench__golden-results" aria-live="polite">
                    @for (result of workbench.goldenResults(); track result.caseId) {
                      <article [attr.data-result]="result.passed === null ? 'pending' : result.passed ? 'pass' : 'fail'">
                        <strong>{{ result.caseId }}</strong>
                        <span>{{ result.run.status }}</span>
                        <code>{{ result.run.id.slice(0, 8) }}</code>
                        @if (result.error) { <p>{{ result.error }}</p> }
                        <div class="ck-workbench__golden-evidence">
                          <span>Expected</span>
                          @if (result.expectedProvided) {
                            <pre>{{ json(result.expected) }}</pre>
                          } @else {
                            <em>Completion only (no expected value).</em>
                          }
                          <span>Actual output_ref</span>
                          <pre>{{ json(result.actual) }}</pre>
                        </div>
                      </article>
                    }
                  </div>
                }
              </div>
            }
          }
        </div>

        @if (localError() || workbench.error(); as error) {
          <p class="ck-workbench__error" role="alert">{{ localError() || error }}</p>
        }
      </section>
    }
  `,
})
export class FlowWorkbenchPanelComponent {
  protected readonly workbench = inject(FlowWorkbenchService);
  protected readonly store = inject(FlowStore);

  readonly open = input(false);
  readonly close = output<void>();

  protected readonly tab = signal<WorkbenchTab>('chat');
  protected readonly chatText = signal('');
  protected readonly chatContextText = signal('{}');
  protected readonly nodeInputText = signal(DEFAULT_NODE_INPUT);
  protected readonly goldenText = signal(DEFAULT_GOLDEN_SET);
  protected readonly localError = signal<string | null>(null);
  protected readonly realSideEffectsAcknowledged = signal(false);
  /** The badge wall became one status line; the facts it used to shout are
   *  here, in full sentences, for whoever wants them. */
  protected readonly detailOpen = signal(false);

  protected readonly selectedRunnableNode = computed<CanonicalFlowNode | null>(() => {
    const node = this.store.selectedNode();
    return isRunnableWorkbenchSkillNode(node) ? node : null;
  });
  protected readonly canRunChat = computed(() => (
    !!this.workbench.systemId()
    && !this.workbench.busy()
  ));
  protected readonly canRunNode = computed(() => (
    !!this.workbench.systemId()
    && !this.workbench.busy()
  ));
  protected readonly canRunGolden = computed(() => (
    !!this.workbench.systemId()
    && !this.workbench.busy()
  ));

  constructor() {
    effect(() => {
      this.store.revision();
      this.realSideEffectsAcknowledged.set(false);
      this.localError.set(null);
    });
  }

  protected runtimeLabel(): string {
    return runtimeModeLabel(this.workbench.runtimeMode());
  }

  protected textValue(event: Event): string {
    return (event.target as HTMLTextAreaElement).value;
  }

  protected onIngressChange(event: Event): void {
    this.workbench.selectedIngressId.set((event.target as HTMLSelectElement).value);
    this.localError.set(null);
  }

  protected onAcknowledgementChange(event: Event): void {
    this.realSideEffectsAcknowledged.set((event.target as HTMLInputElement).checked);
    this.localError.set(null);
  }

  protected runChatFromKeyboard(event: Event): void {
    event.preventDefault();
    if (!this.workbench.busy()) void this.runChat();
  }

  protected async runChat(): Promise<void> {
    if (!this.chatText().trim()) {
      this.localError.set('Enter a message before running the local preview.');
      return;
    }
    const additionalInputRef = parseWorkbenchObject(this.chatContextText());
    if (!additionalInputRef.ok) {
      this.localError.set(additionalInputRef.message);
      return;
    }
    if (!this.requireIngress()) return;
    if (!this.requireRealSideEffectsAcknowledgement()) return;
    this.localError.set(null);
    const result = await this.workbench.runChat(
      this.chatText(),
      additionalInputRef.value,
      true,
    );
    if (result) this.chatText.set('');
  }

  protected async runNode(): Promise<void> {
    const node = this.selectedRunnableNode();
    if (!node) {
      this.localError.set('Select a task node with an executable Skill binding.');
      return;
    }
    const parsed = parseWorkbenchObject(this.nodeInputText());
    if (!parsed.ok) {
      this.localError.set(parsed.message);
      return;
    }
    if (!this.requireRealSideEffectsAcknowledgement()) return;
    this.localError.set(null);
    await this.workbench.runSelectedNode(node.id, parsed.value, true);
  }

  protected async runGolden(): Promise<void> {
    const parsed = parseWorkbenchGoldenSet(this.goldenText());
    if (!parsed.ok) {
      this.localError.set(parsed.message);
      return;
    }
    if (!this.requireIngress()) return;
    if (!this.requireRealSideEffectsAcknowledgement()) return;
    this.localError.set(null);
    await this.workbench.runGoldenSet(parsed.value, true);
  }

  protected json(value: unknown): string {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return '[Unserialisable result]';
    }
  }

  private requireIngress(): boolean {
    const ingresses = this.workbench.ingresses();
    if (ingresses.length === 0) {
      this.localError.set('The current Flow has no executable ingress.');
      return false;
    }
    if (
      ingresses.length > 1
      && !ingresses.some((item) => item.ingress_id === this.workbench.selectedIngressId())
    ) {
      this.localError.set(`Choose one of the ${ingresses.length} Flow ingresses before running the workbench.`);
      return false;
    }
    return true;
  }

  private requireRealSideEffectsAcknowledgement(): boolean {
    if (this.realSideEffectsAcknowledged()) return true;
    this.localError.set(
      'Confirm that this Workbench run invokes real Skills and may cause external side effects.',
    );
    return false;
  }
}
