/**
 * `<app-new-skill-dialog>` — define a Skill this workspace owns.
 *
 * The server owns everything the workspace does not decide: the slug is derived
 * from `local_name`, the certification is `basic`, and the runtime must be one
 * of the verified executors. So this form is built from the descriptors the API
 * serves (`GET /skills/executors`): the kinds, their parameter names, their
 * enums and their length limits are read from `params_schema` instead of being
 * restated here, and a kind added server-side gets its controls for free.
 *
 * Both contracts are parsed before the request leaves, because a JSON typo is
 * the one failure the author can fix without a round trip. Every other refusal
 * belongs to the backend and is shown verbatim.
 */
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import {
  CanonicalApiService,
  type Skill,
  type SkillDraft,
  type SkillExecutorCatalog,
  type SkillExecutorDescriptor,
} from '@app/core/canonical-api.service';
import { GlyphComponent } from '@app/shared/cockpit';

const EMPTY_SCHEMA = '{\n  "type": "object",\n  "properties": {}\n}';

/** How one executor parameter is edited, derived from its schema fragment. */
export interface ExecutorParamField {
  key: string;
  label: string;
  required: boolean;
  control: 'select' | 'registry_target' | 'json' | 'long_text' | 'text';
  options: string[];
  maxLength: number | null;
}

@Component({
  selector: 'app-new-skill-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [GlyphComponent],
  template: `
    <div class="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-auto">
      <div class="absolute inset-0" style="background:rgba(0,0,0,0.62);" (click)="dismiss()"></div>
      <div
        class="relative ck-surface rounded-md"
        style="width:100%; max-width:720px; padding:24px 28px; border:1px solid var(--ck-stroke-strong);"
      >
        <div class="flex items-start justify-between gap-4" style="margin-bottom:18px;">
          <div>
            <div class="ck-mono flex items-center gap-2" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              <ck-glyph name="ledger" [size]="12" />
              WORKSPACE SKILL
            </div>
            <h3 class="text-lg font-medium text-white" style="margin-top:6px;">New skill</h3>
            <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
              The slug is derived from the local name and this workspace. Certification stays BASIC.
            </p>
          </div>
          <button
            type="button"
            (click)="dismiss()"
            class="ck-mono"
            style="padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3); border:1px solid var(--ck-stroke-soft);"
          >
            CANCEL
          </button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2" style="gap:14px;">
          <label class="flex flex-col" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">LOCAL NAME</span>
            <input
              type="text"
              [value]="localName()"
              (input)="localName.set(value($event))"
              placeholder="reset_ticket"
              class="ck-mono"
              [style]="inputStyle"
            />
          </label>
          <label class="flex flex-col" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">DISPLAY NAME</span>
            <input
              type="text"
              [value]="name()"
              (input)="name.set(value($event))"
              placeholder="Reset a ticket"
              [style]="inputStyle"
            />
          </label>
          <label class="flex flex-col md:col-span-2" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">DESCRIPTION</span>
            <input
              type="text"
              [value]="description()"
              (input)="description.set(value($event))"
              [style]="inputStyle"
            />
          </label>
          <label class="flex flex-col" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">TYPE</span>
            <input
              type="text"
              [value]="type()"
              (input)="type.set(value($event))"
              class="ck-mono"
              [style]="inputStyle"
            />
          </label>
          <label class="flex flex-col" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">CATEGORY</span>
            <select
              [value]="category()"
              (change)="category.set(value($event))"
              class="ck-mono"
              [style]="inputStyle"
            >
              <option value="">— none —</option>
              @for (option of catalog.categories; track option) {
                <option [value]="option">{{ option }}</option>
              }
            </select>
          </label>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2" style="gap:14px; margin-top:14px;">
          <label class="flex flex-col" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">INPUT CONTRACT</span>
            <textarea
              rows="6"
              spellcheck="false"
              [value]="inputSchema()"
              (input)="inputSchema.set(value($event))"
              class="ck-mono"
              [style]="areaStyle"
            ></textarea>
          </label>
          <label class="flex flex-col" style="gap:4px;">
            <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">OUTPUT CONTRACT</span>
            <textarea
              rows="6"
              spellcheck="false"
              [value]="outputSchema()"
              (input)="outputSchema.set(value($event))"
              class="ck-mono"
              [style]="areaStyle"
            ></textarea>
          </label>
        </div>

        <div style="margin-top:18px;">
          <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">RUNTIME</span>
          <div class="flex flex-col" style="gap:8px; margin-top:6px;">
            @for (executor of catalog.executors; track executor.kind) {
              <button
                type="button"
                (click)="selectKind(executor.kind)"
                class="text-left"
                style="padding:10px 12px; border-radius:4px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft);"
                [style.boxShadow]="executorKind() === executor.kind ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
              >
                <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-1);">{{ executor.kind }}</span>
                <span class="ck-mono" style="display:block; font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                  {{ executor.summary }}
                </span>
              </button>
            }
          </div>
        </div>

        @if (fields().length) {
          <div class="flex flex-col" style="gap:12px; margin-top:14px;">
            @for (field of fields(); track field.key) {
              <label class="flex flex-col" style="gap:4px;">
                <span class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
                  {{ field.label }}@if (!field.required) { <span style="color:var(--ck-fg-5);">· optional</span> }
                </span>
                @switch (field.control) {
                  @case ('select') {
                    <select
                      [value]="param(field.key)"
                      (change)="setParam(field.key, value($event))"
                      class="ck-mono"
                      [style]="inputStyle"
                    >
                      <option value="">— choose —</option>
                      @for (option of field.options; track option) {
                        <option [value]="option">{{ option }}</option>
                      }
                    </select>
                  }
                  @case ('registry_target') {
                    <select
                      [value]="param(field.key)"
                      (change)="setParam(field.key, value($event))"
                      class="ck-mono"
                      [style]="inputStyle"
                    >
                      <option value="">— choose a catalog skill —</option>
                      @for (target of registryTargets; track target.id) {
                        <option [value]="target.slug">{{ target.name }} · {{ target.slug }}</option>
                      }
                    </select>
                  }
                  @case ('json') {
                    <textarea
                      rows="4"
                      spellcheck="false"
                      [value]="param(field.key)"
                      (input)="setParam(field.key, value($event))"
                      class="ck-mono"
                      [style]="areaStyle"
                    ></textarea>
                  }
                  @case ('long_text') {
                    <textarea
                      rows="6"
                      spellcheck="false"
                      [value]="param(field.key)"
                      (input)="setParam(field.key, value($event))"
                      class="ck-mono"
                      [style]="areaStyle"
                    ></textarea>
                  }
                  @default {
                    <input
                      type="text"
                      [value]="param(field.key)"
                      (input)="setParam(field.key, value($event))"
                      class="ck-mono"
                      [style]="inputStyle"
                    />
                  }
                }
                @if (field.maxLength) {
                  <span class="ck-mono ck-tnum" style="font-size:9px; color:var(--ck-fg-5);">
                    {{ param(field.key).length }} / {{ field.maxLength }}
                  </span>
                }
              </label>
            }
          </div>
        }

        @if (problems().length) {
          <ul class="ck-mono" style="font-size:10px; color:var(--ck-warn); margin:16px 0 0; padding-left:16px;">
            @for (problem of problems(); track problem) {
              <li>{{ problem }}</li>
            }
          </ul>
        }
        @if (error(); as message) {
          <p class="ck-mono" role="alert" style="font-size:10px; color:var(--ck-neg); margin:14px 0 0; white-space:pre-wrap;">
            {{ message }}
          </p>
        }

        <div class="flex items-center justify-end" style="gap:8px; margin-top:20px;">
          <button
            type="button"
            (click)="submit()"
            [disabled]="submitting() || problems().length > 0"
            class="ck-mono"
            style="padding:8px 14px; border-radius:4px; font-size:10px; letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-strong);"
            [style.opacity]="submitting() || problems().length > 0 ? '0.45' : '1'"
          >
            {{ submitting() ? 'CREATING…' : 'CREATE SKILL' }}
          </button>
        </div>
      </div>
    </div>
  `,
})
export class NewSkillDialogComponent {
  private readonly canonical = inject(CanonicalApiService);

  @Input({ required: true }) catalog!: SkillExecutorCatalog;
  /**
   * Rows a `registry_call` may name. The backend refuses a workspace-defined
   * slug and any row with no registered wrapper, so offering those would only
   * produce a refusal the author cannot act on.
   */
  @Input() registryTargets: Skill[] = [];

  @Output() readonly created = new EventEmitter<Skill>();
  @Output() readonly dismissed = new EventEmitter<void>();

  readonly localName = signal('');
  readonly name = signal('');
  readonly description = signal('');
  readonly type = signal('generic');
  readonly category = signal('');
  readonly inputSchema = signal(EMPTY_SCHEMA);
  readonly outputSchema = signal(EMPTY_SCHEMA);
  readonly executorKind = signal('');
  readonly params = signal<Record<string, string>>({});
  readonly submitting = signal(false);
  readonly error = signal<string | null>(null);

  protected readonly inputStyle =
    'padding:7px 10px; font-size:11px; border-radius:4px; background:var(--ck-bg-inset);'
    + ' border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1);';
  protected readonly areaStyle = this.inputStyle + ' resize:vertical;';

  descriptor(): SkillExecutorDescriptor | null {
    const kind = this.executorKind();
    return this.catalog?.executors.find((item) => item.kind === kind) ?? null;
  }

  fields(): ExecutorParamField[] {
    const schema = this.descriptor()?.params_schema;
    if (!schema) return [];
    const required = new Set(schema.required ?? []);
    return Object.entries(schema.properties ?? {}).map(([key, spec]) => ({
      key,
      label: key.replace(/_/g, ' '),
      required: required.has(key),
      control: controlFor(key, spec),
      options: spec.enum ?? [],
      maxLength: spec.maxLength ?? null,
    }));
  }

  param(key: string): string {
    return this.params()[key] ?? '';
  }

  setParam(key: string, raw: string): void {
    this.params.update((current) => ({ ...current, [key]: raw }));
  }

  selectKind(kind: string): void {
    if (this.executorKind() === kind) return;
    this.executorKind.set(kind);
    // Parameters are per-kind and the contract is closed, so carrying a value
    // across would submit a key the chosen runtime rejects.
    this.params.set({});
    this.error.set(null);
  }

  problems(): string[] {
    const issues: string[] = [];
    if (!this.localName().trim()) issues.push('A local name is required.');
    if (!this.name().trim()) issues.push('A display name is required.');
    for (const [raw, label] of [
      [this.inputSchema(), 'Input contract'],
      [this.outputSchema(), 'Output contract'],
    ] as const) {
      const problem = jsonObjectProblem(raw, label);
      if (problem) issues.push(problem);
    }
    if (!this.executorKind()) {
      issues.push('Pick the runtime this Skill binds to.');
      return issues;
    }
    for (const field of this.fields()) {
      const raw = this.param(field.key).trim();
      if (!raw) {
        if (field.required) issues.push(`${field.label} is required by this runtime.`);
        continue;
      }
      if (field.control === 'json') {
        const problem = jsonObjectProblem(raw, field.label);
        if (problem) issues.push(problem);
      }
      if (field.options.length && !field.options.includes(raw)) {
        issues.push(`${field.label} must be one of: ${field.options.join(', ')}.`);
      }
      if (field.maxLength !== null && raw.length > field.maxLength) {
        issues.push(`${field.label} exceeds ${field.maxLength} characters.`);
      }
    }
    return issues;
  }

  submit(): void {
    if (this.submitting() || this.problems().length) return;
    const draft = this.draft();
    if (!draft) return;
    this.submitting.set(true);
    this.error.set(null);
    this.canonical.createSkill(draft).subscribe({
      next: (skill) => {
        this.submitting.set(false);
        this.created.emit(skill);
      },
      error: (failure: unknown) => {
        this.submitting.set(false);
        this.error.set(backendMessage(failure));
      },
    });
  }

  dismiss(): void {
    this.dismissed.emit();
  }

  value(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  private draft(): SkillDraft | null {
    const params: Record<string, unknown> = {};
    for (const field of this.fields()) {
      const raw = this.param(field.key).trim();
      if (!raw) continue;
      params[field.key] = field.control === 'json' ? JSON.parse(raw) : raw;
    }
    const category = this.category().trim();
    return {
      local_name: this.localName().trim(),
      name: this.name().trim(),
      description: this.description().trim(),
      type: this.type().trim() || 'generic',
      category: category || null,
      input_schema: parseSchema(this.inputSchema()),
      output_schema: parseSchema(this.outputSchema()),
      executor: { kind: this.executorKind(), params },
    };
  }
}

function controlFor(key: string, spec: { type?: string; enum?: string[]; maxLength?: number }): ExecutorParamField['control'] {
  if (spec.enum?.length) return 'select';
  if (spec.type === 'object') return 'json';
  // The only free-text parameter that names another catalog row: a picker keeps
  // the author inside the set the runtime can actually resolve.
  if (key === 'skill_slug') return 'registry_target';
  if ((spec.maxLength ?? 0) > 400) return 'long_text';
  return 'text';
}

function parseSchema(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  return JSON.parse(trimmed) as Record<string, unknown>;
}

function jsonObjectProblem(raw: string, label: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return `${label} is not valid JSON.`;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return `${label} must be a JSON object, not an array or a scalar.`;
  }
  return null;
}

/** The server's own words. A refusal names the schema, the binding or the
 * permission at fault, and paraphrasing it would hide what to change. */
export function backendMessage(failure: unknown): string {
  const detail = (failure as { error?: { detail?: unknown } })?.error?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const lines = detail
      .map((item) => {
        const entry = item as { loc?: unknown[]; msg?: string };
        const where = (entry.loc ?? []).filter((part) => part !== 'body').join('.');
        return [where, entry.msg].filter(Boolean).join(': ');
      })
      .filter(Boolean);
    if (lines.length) return lines.join('\n');
  }
  if (detail && typeof detail === 'object') {
    const entry = detail as { message?: string; code?: string };
    if (entry.message) return entry.message;
    if (entry.code) return entry.code;
  }
  const message = (failure as { message?: string })?.message;
  return message || 'The Skill was not created.';
}
