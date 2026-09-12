/**
 * `<app-new-skill-dialog>` — author a Skill this workspace owns, in four steps.
 *
 * The server owns everything the workspace does not decide: the slug is derived
 * from `local_name`, and the runtime must be one of the verified executors.
 * So this form is built from the descriptors the API
 * serves (`GET /skills/executors`): the kinds, their parameter names, their
 * enums and their length limits are read from `params_schema` instead of being
 * restated here, and a kind added server-side gets its controls for free.
 *
 * Three things changed the day JSON stopped being mandatory:
 *
 * * both contracts are edited through `<ck-schema-builder>`, which keeps an
 *   "Advanced JSON" tab so nothing becomes unexpressible;
 * * the preset inputs of a wrapped skill are a form derived from that skill's
 *   own input contract — the picker already knows which skill it is;
 * * the steps are named after the Business Requirements chain (intent →
 *   contract → execution → review) and show the BRD word next to the platform
 *   word rather than inventing a third vocabulary. Each step asks its question
 *   in plain language first, with an example; the pointer into a requirements
 *   document sits one line below, behind a `ck-help` that defines the acronym,
 *   so somebody building from nothing is never held to a document they do not
 *   have.
 *
 * The same component edits an existing Skill: the screens are identical, the
 * local name is locked because the slug is the dispatch key already written
 * into every Flow node bound to this Skill.
 */
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  OnDestroy,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { Subscription } from 'rxjs';
import {
  CanonicalApiService,
  type Capability,
  type Skill,
  type SkillDraft,
  type SkillExecutorCatalog,
  type SkillExecutorDescriptor,
} from '@app/core/canonical-api.service';
import type { I18nKey } from '@app/core/i18n.dict';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { catalogModelName, selectableTextModel, type ModelCatalogEntry } from '@app/core/model-catalog';
import { GlyphComponent, HelpTooltipComponent } from '@app/shared/cockpit';
import { SkillExecutionComponent } from './skill-execution.component';
import { SchemaBuilderComponent } from '@app/shared/schema-builder/schema-builder.component';
import {
  type ValueField,
  objectToValues,
  valueFieldsFromSchema,
  valuesToObject,
} from '@app/shared/schema-builder/schema-builder.vm';

/** How one executor parameter is edited, derived from its schema fragment. */
export interface ExecutorParamField {
  key: string;
  label: string;
  required: boolean;
  control: 'select' | 'model' | 'registry_target' | 'preset_inputs' | 'json' | 'long_text' | 'text';
  options: string[];
  maxLength: number | null;
}

/** A refusal to submit, as a key the view renders in the active locale. */
export interface AuthoringProblem {
  readonly key: I18nKey;
  readonly params?: Record<string, string | number>;
}

/** What an imported Business Requirements row prefills. */
export interface SkillDraftSeed {
  localName?: string;
  name?: string;
  description?: string;
  category?: string | null;
  provider?: string;
  model?: string;
}

const STEPS = ['intent', 'contract', 'runtime', 'review'] as const;
export type AuthoringStep = (typeof STEPS)[number];

/** The shapes offered as a starting point, drawn from the seeded registry. */
export type SkillPreset = 'scratch' | 'llm' | 'wrapper';

@Component({
  selector: 'app-new-skill-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, GlyphComponent, HelpTooltipComponent, SchemaBuilderComponent, SkillExecutionComponent],
  template: `
    <div class="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-auto">
      <div class="absolute inset-0" style="background:var(--ck-scrim);" (click)="dismiss()"></div>
      <div
        class="relative ck-surface rounded-md"
        role="dialog"
        aria-modal="true"
        aria-labelledby="skill-dialog-title"
        cdkTrapFocus
        [cdkTrapFocusAutoCapture]="true"
        style="width:100%; max-width:760px; padding:24px 28px; border:1px solid var(--ck-stroke-strong);"
      >
        <div class="flex items-start justify-between gap-4" style="margin-bottom:16px;">
          <div>
            <div class="ck-mono flex items-center gap-2" style="font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              <ck-glyph name="ledger" [size]="12" />
              {{ i18n.t('skills.wizard.eyebrow') }}
              <ck-help id="concept.skill" />
            </div>
            <h2 id="skill-dialog-title" class="text-lg font-medium" style="color:var(--ck-fg-1); margin-top:6px;">
              {{ i18n.t(editing() ? 'skills.wizard.title.edit' : 'skills.wizard.title.create') }}
            </h2>
            <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
              {{ i18n.t(editing() ? 'skills.wizard.subtitle.edit' : 'skills.wizard.subtitle') }}
            </p>
          </div>
          <button type="button" (click)="dismiss()" class="ck-mono" [style]="ghostStyle">
            {{ i18n.t('skills.wizard.cancel') }}
          </button>
        </div>

        <!-- Steps -->
        <div class="flex items-center ck-scroll" style="gap:6px; margin-bottom:6px; overflow-x:auto;" role="tablist">
          @for (name of steps; track name; let index = $index) {
            <button
              type="button"
              role="tab"
              class="ck-mono"
              [id]="'skill-step-' + name"
              [attr.aria-controls]="'skill-panel-' + name"
              [attr.aria-selected]="step() === name"
              [tabIndex]="step() === name ? 0 : -1"
              (click)="goTo(name)"
              (keydown)="onStepKey($event, index)"
              [style]="stepStyle"
              [style.color]="step() === name ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)'"
              [style.background]="step() === name ? 'var(--ck-bg-inset)' : 'transparent'"
              [style.boxShadow]="step() === name ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
            >
              {{ index + 1 }} · {{ stepLabel(name) }}
            </button>
          }
        </div>
        <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin:0;">
          {{ stepHint() }}
        </p>
        <!-- The requirements document is an aid for whoever has one, never the
             instruction: the plain question above stands on its own. -->
        @if (stepBrdHint(); as brd) {
          <p
            class="ck-mono flex items-start gap-1"
            style="font-size:9px; color:var(--ck-fg-4); line-height:1.5; margin:4px 0 0;"
          >
            <ck-help id="concept.business-requirements" />
            <span>{{ brd }}</span>
          </p>
        }
        <div style="height:14px;"></div>

        <div
          role="tabpanel"
          [id]="'skill-panel-' + step()"
          [attr.aria-labelledby]="'skill-step-' + step()"
        >
        @switch (step()) {
          @case ('intent') {
            @if (!editing()) {
              <div style="margin-bottom:14px;">
                <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.preset.label') }}</span>
                <div class="flex flex-wrap" style="gap:8px; margin-top:6px;">
                  @for (option of presets(); track option.id) {
                    <button
                      type="button"
                      (click)="applyPreset(option.id)"
                      class="text-left"
                      [attr.aria-pressed]="preset() === option.id"
                      [style]="cardStyle"
                      [style.boxShadow]="preset() === option.id ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
                    >
                      <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-1);">
                        {{ i18n.t(option.label) }}
                      </span>
                      <span class="ck-mono" style="display:block; font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                        {{ i18n.t(option.summary) }}
                      </span>
                    </button>
                  }
                </div>
              </div>
            }

            <div class="grid grid-cols-1 md:grid-cols-2" style="gap:14px;">
              <label class="flex flex-col" style="gap:4px;">
                <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.field.local_name') }}</span>
                <input
                  type="text"
                  [value]="localName()"
                  (input)="localName.set(value($event))"
                  [disabled]="editing()"
                  class="ck-mono"
                  [style]="inputStyle"
                />
                <span class="ck-mono" [style]="noteStyle">
                  {{ i18n.t(editing() ? 'skills.review.slug.frozen' : 'skills.field.local_name.hint') }}
                </span>
              </label>
              <label class="flex flex-col" style="gap:4px;">
                <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.field.name') }}</span>
                <input type="text" [value]="name()" (input)="name.set(value($event))" [style]="inputStyle" />
              </label>
              <label class="flex flex-col md:col-span-2" style="gap:4px;">
                <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.field.description') }}</span>
                <input
                  type="text"
                  [value]="description()"
                  (input)="description.set(value($event))"
                  [style]="inputStyle"
                />
                <span class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.field.description.hint') }}</span>
              </label>
              <label class="flex flex-col" style="gap:4px;">
                <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.field.type') }}</span>
                <input
                  type="text"
                  [value]="type()"
                  (input)="type.set(value($event))"
                  class="ck-mono"
                  [style]="inputStyle"
                />
              </label>
              <label class="flex flex-col" style="gap:4px;">
                <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.field.category') }}</span>
                <select [value]="category()" (change)="category.set(value($event))" class="ck-mono" [style]="inputStyle">
                  <option value="">{{ i18n.t('skills.field.category.none') }}</option>
                  @for (option of catalog.categories; track option) {
                    <option [value]="option" [selected]="category() === option">{{ option }}</option>
                  }
                </select>
                <span class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.field.category.hint') }}</span>
              </label>
              @if (!editing()) {
                <label class="flex flex-col md:col-span-2" style="gap:4px;">
                  <span class="ck-mono flex items-center gap-1" [style]="labelStyle">
                    {{ i18n.t('skills.field.capability') }}
                    <ck-help id="concept.capability" />
                  </span>
                  <select
                    [value]="capabilityId()"
                    (change)="capabilityId.set(value($event))"
                    [style]="inputStyle"
                  >
                    <option value="">{{ i18n.t('skills.field.capability.none') }}</option>
                    @for (option of capabilities; track option.id) {
                      <option [value]="option.id" [selected]="capabilityId() === option.id">{{ option.name }}</option>
                    }
                  </select>
                  <span class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.field.capability.hint') }}</span>
                </label>
              }
            </div>
          }

          @case ('contract') {
            <div class="grid grid-cols-1" style="gap:18px;">
              <ck-schema-builder
                [label]="i18n.t('skills.contract.input')"
                [hint]="i18n.t('skills.contract.input.hint')"
                [value]="inputSchema()"
                (valueChange)="inputSchema.set($event)"
              />
              <ck-schema-builder
                [label]="i18n.t('skills.contract.output')"
                [hint]="i18n.t('skills.contract.output.hint')"
                [value]="outputSchema()"
                (valueChange)="outputSchema.set($event)"
              />
            </div>
          }

          @case ('runtime') {
            <div>
              <span class="ck-mono" [style]="labelStyle">{{ i18n.t('skills.runtime.label') }}</span>
              <div class="flex flex-col" style="gap:8px; margin-top:6px;">
                @for (executor of catalog.executors; track executor.kind) {
                  <button
                    type="button"
                    (click)="selectKind(executor.kind)"
                    class="text-left"
                    [attr.aria-pressed]="executorKind() === executor.kind"
                    style="padding:10px 12px; border-radius:4px; background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-soft);"
                    [style.boxShadow]="executorKind() === executor.kind ? 'inset 0 0 0 1px var(--ck-stroke-strong)' : 'none'"
                  >
                    <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-1);">
                      {{ runtimeLabel(executor.kind) }}
                    </span>
                    <span class="ck-mono" style="display:block; font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                      {{ executor.summary }}
                    </span>
                    <span
                      class="ck-mono"
                      style="display:block; font-size:9px; color:var(--ck-fg-4); margin-top:4px;"
                      [title]="i18n.t('skills.runtime.technical')"
                    >{{ i18n.t('skills.runtime.technical') }} · {{ executor.kind }}</span>
                  </button>
                }
              </div>
            </div>

            @if (fields().length) {
              <div class="flex flex-col" style="gap:12px; margin-top:14px;">
                @for (field of fields(); track field.key) {
                  <label class="flex flex-col" style="gap:4px;">
                    <span class="ck-mono flex items-center gap-1" [style]="labelStyle">
                      {{ paramLabel(field) }}@if (!field.required) {
                        <span style="color:var(--ck-fg-4);">· {{ i18n.t('skills.runtime.optional') }}</span>
                      }
                      @if (field.control === 'preset_inputs') {
                        <ck-help id="concept.preset-inputs" />
                      }
                    </span>
                    @switch (field.control) {
                      @case ('select') {
                        <select
                          [value]="param(field.key)"
                          (change)="setParam(field.key, value($event))"
                          class="ck-mono"
                          [style]="inputStyle"
                        >
                          <option value="">{{ i18n.t('skills.runtime.choose') }}</option>
                          @for (option of fieldOptions(field); track option) {
                            <option [value]="option" [disabled]="providerDisabled(field, option)" [selected]="param(field.key) === option">{{ optionLabel(field, option) }}</option>
                          }
                        </select>
                      }
                      @case ('model') {
                        <select [value]="param(field.key)" (change)="setParam(field.key, value($event))" [style]="inputStyle">
                          <option value="" [selected]="!param(field.key)">{{ i18n.t('skills.models.inherit') }}</option>
                          @if (param(field.key) && !modelListed(param(field.key))) {
                            <option [value]="param(field.key)" selected>{{ param(field.key) }} · {{ i18n.t('skills.models.saved') }}</option>
                          }
                          @for (model of providerModels(); track model.id) {
                            <option [value]="modelName(model)" [selected]="param(field.key) === modelName(model)">{{ modelName(model) }}</option>
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
                          <option value="">{{ i18n.t('skills.runtime.target.choose') }}</option>
                          @for (target of registryTargets; track target.id) {
                            <option [value]="target.slug" [selected]="param(field.key) === target.slug">{{ target.name }} · {{ target.slug }}</option>
                          }
                        </select>
                      }
                      @case ('preset_inputs') {
                        <span class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.preset_inputs.hint') }}</span>
                        <div class="flex" style="gap:4px; margin:4px 0;">
                          <button type="button" class="ck-mono" [style]="tabStyle(presetTab() === 'form')" (click)="presetTab.set('form')">
                            {{ i18n.t('skills.preset_inputs.form') }}
                          </button>
                          <button type="button" class="ck-mono" [style]="tabStyle(presetTab() === 'json')" (click)="presetTab.set('json')">
                            {{ i18n.t('skills.preset_inputs.advanced') }}
                          </button>
                        </div>
                        @if (presetTab() === 'form') {
                          @if (!presetTarget()) {
                            <span class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.preset_inputs.empty') }}</span>
                          } @else if (!presetFields().length) {
                            <span class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.preset_inputs.no_contract') }}</span>
                          } @else {
                            @for (entry of presetFields(); track entry.name) {
                              <label class="flex flex-col" style="gap:3px; margin-bottom:6px;">
                                <span class="ck-mono" [style]="noteStyle">
                                  {{ entry.name }}@if (entry.required) { <span style="color:var(--ck-fg-3);">*</span> }
                                </span>
                                @if (entry.options.length) {
                                  <select
                                    class="ck-mono"
                                    [style]="inputStyle"
                                    [value]="presetValue(entry.name)"
                                    (change)="setPresetValue(entry, value($event))"
                                  >
                                    <option value=""></option>
                                    @for (option of entry.options; track option) {
                                      <option [value]="option" [selected]="presetValue(entry.name) === option">{{ option }}</option>
                                    }
                                  </select>
                                } @else {
                                  <input
                                    type="text"
                                    class="ck-mono"
                                    [style]="inputStyle"
                                    [value]="presetValue(entry.name)"
                                    (change)="setPresetValue(entry, value($event))"
                                  />
                                }
                                @if (entry.description) {
                                  <span class="ck-mono" [style]="noteStyle">{{ entry.description }}</span>
                                }
                              </label>
                            }
                            @if (presetExtras().length) {
                              <span class="ck-mono" [style]="noteStyle">
                                {{ i18n.t('skills.preset_inputs.extra', { keys: presetExtras().join(', ') }) }}
                              </span>
                            }
                          }
                        } @else {
                          <textarea
                            rows="6"
                            spellcheck="false"
                            [value]="param(field.key)"
                            (input)="setParam(field.key, value($event))"
                            class="ck-mono"
                            [style]="areaStyle"
                          ></textarea>
                        }
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
                      <span class="ck-mono ck-tnum" style="font-size:9px; color:var(--ck-fg-4);">
                        {{ param(field.key).length }} / {{ field.maxLength }}
                      </span>
                    }
                  </label>
                }
              </div>
            }
            @if (executorKind() === 'prompt_template') {
              <div class="mt-3 flex flex-wrap gap-2 items-center text-xs">
                @if (modelsLoading()) { <span role="status">{{ i18n.t('common.loading') }}</span> }
                @if (modelsError(); as error) { <span role="alert">{{ error }}</span> }
                <button type="button" (click)="loadModels()" [disabled]="modelsLoading()" [style]="ghostStyle">{{ i18n.t('skills.models.refresh') }}</button>
              </div>
              <app-skill-execution [executor]="executionPreview()" [systemId]="systemId" [summaryOnly]="true" />
            }
          }

          @case ('review') {
            <div class="flex flex-col" style="gap:10px;">
              @for (row of review(); track row.label) {
                <div class="flex items-start justify-between" style="gap:16px;">
                  <span class="ck-mono" [style]="labelStyle">{{ i18n.t(row.label) }}</span>
                  <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-1); text-align:right;">
                    {{ row.value }}
                    @if (row.note) {
                      <span style="display:block; font-size:9px; color:var(--ck-fg-4);">{{ i18n.t(row.note) }}</span>
                    }
                  </span>
                </div>
              }
            </div>
          }
        }
        </div>

        @if (problems().length) {
          <ul class="ck-mono" style="font-size:10px; color:var(--ck-warn); margin:16px 0 0; padding-left:16px;">
            @for (problem of problems(); track problem.key + (problem.params?.['field'] ?? '')) {
              <li>{{ i18n.t(problem.key, problem.params) }}</li>
            }
          </ul>
        }
        @if (error(); as message) {
          <p class="ck-mono" role="alert" style="font-size:10px; color:var(--ck-neg); margin:14px 0 0; white-space:pre-wrap;">
            {{ message }}
          </p>
        }

        <div class="flex items-center justify-between" style="gap:8px; margin-top:20px;">
          <button
            type="button"
            (click)="previous()"
            [disabled]="stepIndex() === 0"
            class="ck-mono"
            [style]="ghostStyle"
            [style.opacity]="stepIndex() === 0 ? '0.35' : '1'"
          >
            {{ i18n.t('skills.wizard.back') }}
          </button>
          @if (stepIndex() < steps.length - 1) {
            <button type="button" (click)="next()" class="ck-mono" [style]="primaryStyle">
              {{ i18n.t('skills.wizard.next') }}
            </button>
          } @else {
            <button
              type="button"
              (click)="submit()"
              [disabled]="submitting() || problems().length > 0"
              class="ck-mono"
              [style]="primaryStyle"
              [style.opacity]="submitting() || problems().length > 0 ? '0.45' : '1'"
            >
              {{ submitLabel() }}
            </button>
          }
        </div>
      </div>
    </div>
  `,
})
export class NewSkillDialogComponent implements OnInit, OnDestroy {
  private readonly canonical = inject(CanonicalApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly i18n = inject(I18nService);

  @Input({ required: true }) catalog!: SkillExecutorCatalog;
  /**
   * Rows a wrapped-skill runtime may name. The backend refuses a
   * workspace-defined slug and any row with no registered wrapper, so offering
   * those would only produce a refusal the author cannot act on.
   */
  @Input() registryTargets: Skill[] = [];
  /** Capabilities this workspace may make carry the new Skill. */
  @Input() capabilities: Capability[] = [];
  @Input() systemId?: string;

  /** A detail-page edit can start at execution without changing the create journey. */
  @Input() set initialStep(value: AuthoringStep) {
    this.step.set(value);
  }

  /** Set to edit an existing Skill; the screens are the same, the slug is not. */
  @Input() set skill(value: Skill | null) {
    this.existing.set(value);
    if (value) this.seedFrom(value);
  }

  /** Prefill from an imported Business Requirements row. */
  @Input() set seed(value: SkillDraftSeed | null) {
    if (!value) return;
    if (value.localName) this.localName.set(value.localName);
    if (value.name) this.name.set(value.name);
    if (value.description) this.description.set(value.description);
    if (value.category) this.category.set(value.category);
    if (value.provider && value.model) {
      this.applyPreset('llm');
      this.params.set({ ...this.params(), provider: value.provider, model: value.model });
    }
  }

  @Output() readonly created = new EventEmitter<Skill>();
  @Output() readonly updated = new EventEmitter<SkillUpdateResult>();
  @Output() readonly dismissed = new EventEmitter<void>();

  protected readonly steps = STEPS;

  readonly step = signal<AuthoringStep>('intent');
  readonly preset = signal<SkillPreset>('scratch');
  readonly localName = signal('');
  readonly name = signal('');
  readonly description = signal('');
  readonly type = signal('generic');
  readonly category = signal('');
  readonly capabilityId = signal('');
  readonly inputSchema = signal<Record<string, unknown> | null>(null);
  readonly outputSchema = signal<Record<string, unknown> | null>(null);
  readonly executorKind = signal('');
  /** Raw text per parameter — including the preset-inputs object, whose form
   * and JSON tab are two views of this one string. */
  readonly params = signal<Record<string, string>>({});
  readonly presetTab = signal<'form' | 'json'>('form');
  readonly submitting = signal(false);
  readonly error = signal<string | null>(null);
  readonly models = signal<ModelCatalogEntry[]>([]);
  readonly modelsLoading = signal(false);
  readonly modelsError = signal<string | null>(null);
  private modelsSubscription: Subscription | null = null;
  private modelRequest = 0;
  private readonly unregisterModels = this.workspace.registerContextReset(() => {
    this.modelRequest += 1;
    this.modelsSubscription?.unsubscribe();
    this.models.set([]);
    this.modelsError.set(null);
    this.modelsLoading.set(false);
  });
  private readonly existing = signal<Skill | null>(null);
  private readonly previousFocus = typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;

  protected readonly inputStyle =
    'padding:7px 10px; font-size:11px; border-radius:4px; background:var(--ck-bg-inset);'
    + ' border:1px solid var(--ck-stroke-soft); color:var(--ck-fg-1);';
  protected readonly areaStyle = this.inputStyle + ' resize:vertical;';
  protected readonly labelStyle =
    'font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);';
  protected readonly noteStyle = 'font-size:9px; color:var(--ck-fg-4); line-height:1.5;';
  protected readonly ghostStyle =
    'padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em;'
    + ' text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3);'
    + ' border:1px solid var(--ck-stroke-soft);';
  protected readonly primaryStyle =
    'padding:8px 14px; border-radius:4px; font-size:10px; letter-spacing:0.14em;'
    + ' text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-1);'
    + ' border:1px solid var(--ck-stroke-strong);';
  protected readonly stepStyle =
    'padding:5px 10px; border-radius:4px; font-size:9px; letter-spacing:0.12em;'
    + ' text-transform:uppercase;';
  protected readonly cardStyle =
    'flex:1 1 200px; padding:10px 12px; border-radius:4px; background:var(--ck-bg-inset);'
    + ' border:1px solid var(--ck-stroke-soft);';

  readonly editing = computed(() => this.existing() !== null);
  readonly stepIndex = computed(() => STEPS.indexOf(this.step()));
  readonly modelName = catalogModelName;
  readonly providerModels = computed(() => this.models().filter((entry) =>
    entry.provider === (this.param('provider') === 'azure' ? 'openai' : this.param('provider'))
      && selectableTextModel(entry),
  ));
  readonly executionPreview = computed<Skill['executor']>(() => ({
    kind: this.executorKind(),
    params: { provider: this.param('provider'), ...(this.param('model') ? { model: this.param('model') } : {}) },
  }), { equal: (a, b) => a?.kind === b?.kind && a?.params?.['provider'] === b?.params?.['provider'] && a?.params?.['model'] === b?.params?.['model'] });

  ngOnInit(): void { this.loadModels(); }

  ngOnDestroy(): void {
    this.modelRequest += 1;
    this.modelsSubscription?.unsubscribe();
    this.unregisterModels();
  }

  loadModels(): void {
    this.modelsSubscription?.unsubscribe();
    const request = ++this.modelRequest;
    const scope = this.workspace.captureRequestScope();
    this.modelsLoading.set(true);
    this.modelsError.set(null);
    this.modelsSubscription = this.canonical.listModelCatalog().subscribe({
      next: (models) => {
        if (request !== this.modelRequest || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.models.set(models);
        this.modelsLoading.set(false);
      },
      error: (failure) => {
        if (request !== this.modelRequest || !this.workspace.isRequestScopeCurrent(scope)) return;
        this.models.set([]);
        this.modelsLoading.set(false);
        this.modelsError.set(backendMessage(failure, this.i18n.t('skills.models.load_error')));
      },
    });
  }

  fieldOptions(field: ExecutorParamField): string[] {
    return field.key === 'provider' && this.executorKind() === 'prompt_template'
      ? field.options.filter((value) => value !== 'azure' || this.param('provider') === 'azure')
      : field.options;
  }

  providerDisabled(field: ExecutorParamField, option: string): boolean {
    if (field.key !== 'provider' || this.executorKind() !== 'prompt_template'
      || option === this.param('provider') || option === 'workspace') return false;
    return !this.models().some((entry) => entry.provider === option && selectableTextModel(entry));
  }

  optionLabel(field: ExecutorParamField, option: string): string {
    if (field.key !== 'provider') return option;
    if (option === 'azure') return this.i18n.t('skills.models.legacy_azure');
    if (option === 'workspace') return this.i18n.t('skills.models.workspace');
    const rows = this.models().filter((entry) => entry.provider === option);
    if (rows.length && rows.every((entry) => entry.status === 'unreachable')) {
      return `${option} · ${this.i18n.t('skills.models.connection_unreachable')}`;
    }
    return option + (this.providerDisabled(field, option) ? ` · ${this.i18n.t('skills.models.unavailable')}` : '');
  }

  modelListed(model: string): boolean {
    return this.providerModels().some((entry) => catalogModelName(entry) === model);
  }

  tabStyle(active: boolean): string {
    return (
      'padding:4px 9px; border-radius:4px; font-size:9px; letter-spacing:0.1em;'
      + ' text-transform:uppercase; border:1px solid '
      + (active ? 'var(--ck-stroke-strong)' : 'transparent')
      + '; background:' + (active ? 'var(--ck-bg-inset)' : 'transparent')
      + '; color:' + (active ? 'var(--ck-fg-1)' : 'var(--ck-fg-4)') + ';'
    );
  }

  stepLabel(step: AuthoringStep): string {
    return this.i18n.t(`skills.wizard.step.${step}` as I18nKey);
  }

  stepHint(): string {
    return this.i18n.t(`skills.wizard.hint.${this.step()}` as I18nKey);
  }

  /**
   * The requirements-document pointer for this step, or '' where there is
   * none (the execution step is about the platform, not the document). Built
   * at runtime, so a missing key resolves to nothing rather than to itself.
   */
  stepBrdHint(): string {
    const key = `skills.wizard.brd.${this.step()}` as I18nKey;
    const text = this.i18n.t(key);
    return text === key ? '' : text;
  }

  submitLabel(): string {
    if (this.editing()) {
      return this.i18n.t(this.submitting() ? 'skills.wizard.saving' : 'skills.wizard.save');
    }
    return this.i18n.t(this.submitting() ? 'skills.wizard.creating' : 'skills.wizard.create');
  }

  /**
   * The runtime label is the lexicon term; the raw kind stays one line below.
   * A kind the server adds tomorrow falls back to its own name rather than
   * showing a missing key.
   */
  runtimeLabel(kind: string): string {
    const key = `skills.runtime.${kind}` as I18nKey;
    const label = this.i18n.t(key);
    return label === key ? kind : label;
  }

  paramLabel(field: ExecutorParamField): string {
    const key = `skills.param.${field.key}` as I18nKey;
    const label = this.i18n.t(key);
    return label === key ? field.label : label;
  }

  presets(): Array<{ id: SkillPreset; label: I18nKey; summary: I18nKey }> {
    const out: Array<{ id: SkillPreset; label: I18nKey; summary: I18nKey }> = [
      { id: 'scratch', label: 'skills.preset.scratch', summary: 'skills.preset.scratch.summary' },
    ];
    for (const executor of this.catalog?.executors ?? []) {
      if (executor.kind === 'prompt_template') {
        out.push({ id: 'llm', label: 'skills.runtime.prompt_template', summary: 'skills.preset.llm.summary' });
      }
      if (executor.kind === 'registry_call') {
        out.push({ id: 'wrapper', label: 'skills.runtime.registry_call', summary: 'skills.preset.wrapper.summary' });
      }
    }
    return out;
  }

  /**
   * A preset is a starting point, not a template engine: it selects the
   * runtime and proposes the contract shape the seeded registry uses for that
   * kind of Skill. Everything it writes stays editable.
   */
  applyPreset(id: SkillPreset): void {
    this.preset.set(id);
    this.error.set(null);
    if (id === 'scratch') {
      this.executorKind.set('');
      this.params.set({});
      return;
    }
    if (id === 'llm') {
      this.selectKind('prompt_template');
      this.setParam('template', '{question}');
      this.type.set('llm');
      this.category.set(this.knownCategory('LLM'));
      this.inputSchema.set({
        type: 'object',
        properties: { question: { type: 'string', description: 'What the model is asked.' } },
        required: ['question'],
      });
      this.outputSchema.set({
        type: 'object',
        properties: { completion: { type: 'string' } },
        required: ['completion'],
      });
      return;
    }
    this.selectKind('registry_call');
    this.type.set('generic');
    const target = this.registryTargets.find((row) => row.slug === 'audit_log_v1')
      ?? this.registryTargets[0];
    if (target) {
      this.setParam('skill_slug', target.slug);
      this.inputSchema.set((target.input_schema as Record<string, unknown>) ?? null);
      this.outputSchema.set((target.output_schema as Record<string, unknown>) ?? null);
    }
  }

  private knownCategory(candidate: string): string {
    return (this.catalog?.categories ?? []).includes(candidate) ? candidate : '';
  }

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
    this.params.update((current) => ({
      ...current,
      ...(key === 'provider' && raw !== current['provider'] ? { model: '' } : {}),
      [key]: raw,
    }));
  }

  selectKind(kind: string): void {
    if (this.executorKind() === kind) return;
    this.executorKind.set(kind);
    // Parameters are per-kind and the contract is closed, so carrying a value
    // across would submit a key the chosen runtime rejects.
    this.params.set({});
    this.error.set(null);
  }

  // -- Preset inputs ------------------------------------------------------

  /** The catalog row the preset-inputs form is derived from. */
  presetTarget(): Skill | null {
    const slug = this.param('skill_slug').trim();
    if (!slug) return null;
    return this.registryTargets.find((row) => row.slug === slug) ?? null;
  }

  presetFields(): ValueField[] {
    return valueFieldsFromSchema(this.presetTarget()?.input_schema);
  }

  private presetObject(): Record<string, unknown> {
    const raw = this.param('frozen_input').trim();
    if (!raw) return {};
    try {
      const parsed: unknown = JSON.parse(raw);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }

  presetValue(name: string): string {
    return objectToValues(this.presetObject())[name] ?? '';
  }

  /** Keys preset by hand that the target contract does not declare. The
   * runtime still merges them, so naming them beats hiding them. */
  presetExtras(): string[] {
    const known = new Set(this.presetFields().map((field) => field.name));
    return Object.keys(this.presetObject()).filter((key) => !known.has(key));
  }

  setPresetValue(field: ValueField, raw: string): void {
    const next = { ...this.presetObject() };
    const coerced = valuesToObject([field], { [field.name]: raw });
    if (field.name in coerced) next[field.name] = coerced[field.name];
    else delete next[field.name];
    this.setParam(
      'frozen_input',
      Object.keys(next).length ? JSON.stringify(next, null, 2) : '',
    );
  }

  // -- Navigation ---------------------------------------------------------

  goTo(step: AuthoringStep): void {
    this.step.set(step);
  }

  onStepKey(event: KeyboardEvent, index: number): void {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!delta && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    const next = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? STEPS.length - 1
        : (index + delta + STEPS.length) % STEPS.length;
    this.goTo(STEPS[next]);
    queueMicrotask(() => document.getElementById(`skill-step-${STEPS[next]}`)?.focus());
  }

  next(): void {
    this.step.set(STEPS[Math.min(this.stepIndex() + 1, STEPS.length - 1)]);
  }

  previous(): void {
    this.step.set(STEPS[Math.max(this.stepIndex() - 1, 0)]);
  }

  review(): Array<{ label: I18nKey; value: string; note?: I18nKey }> {
    const rows: Array<{ label: I18nKey; value: string; note?: I18nKey }> = [
      { label: 'skills.field.name', value: this.name().trim() || '—' },
      {
        label: 'skills.review.slug',
        value: this.existing()?.slug ?? (this.localName().trim() || '—'),
        note: this.editing() ? 'skills.review.slug.frozen' : 'skills.review.slug.derived',
      },
      {
        label: 'skills.review.runtime',
        value: this.executorKind() ? this.runtimeLabel(this.executorKind()) : '—',
      },
      { label: 'skills.field.category', value: this.category() || '—' },
    ];
    if (!this.editing()) {
      const capability = this.capabilities.find((row) => row.id === this.capabilityId());
      rows.splice(4, 0, {
        label: 'skills.review.capability',
        value: capability?.name ?? this.i18n.t('skills.field.capability.none'),
      });
    }
    return rows;
  }

  problems(): AuthoringProblem[] {
    const issues: AuthoringProblem[] = [];
    if (!this.localName().trim()) issues.push({ key: 'skills.problem.local_name' });
    if (!this.name().trim()) issues.push({ key: 'skills.problem.name' });
    if (!this.executorKind()) {
      issues.push({ key: 'skills.problem.runtime' });
      return issues;
    }
    for (const field of this.fields()) {
      const raw = this.param(field.key).trim();
      const label = this.paramLabel(field);
      if (!raw) {
        if (field.required) issues.push({ key: 'skills.problem.required', params: { field: label } });
        continue;
      }
      if (field.control === 'json' || field.control === 'preset_inputs') {
        const problem = jsonObjectProblem(raw, label);
        if (problem) issues.push(problem);
      }
      if (field.options.length && !field.options.includes(raw)) {
        issues.push({
          key: 'skills.problem.enum',
          params: { field: label, options: field.options.join(', ') },
        });
      }
      if (field.maxLength !== null && raw.length > field.maxLength) {
        issues.push({
          key: 'skills.problem.maxlength',
          params: { field: label, max: field.maxLength },
        });
      }
    }
    return issues;
  }

  submit(): void {
    if (this.submitting() || this.problems().length) return;
    this.submitting.set(true);
    this.error.set(null);
    const current = this.existing();
    if (current) {
      this.canonical.updateSkill(current.slug, this.patch()).subscribe({
        next: (skill) => {
          this.submitting.set(false);
          this.updated.emit({
            skill,
            publishedIn: publishedSystemNames(skill),
          });
        },
        error: (failure: unknown) => {
          this.submitting.set(false);
          this.error.set(backendMessage(failure, this.i18n.t('skills.error.update')));
        },
      });
      return;
    }
    this.canonical.createSkill(this.draft()).subscribe({
      next: (skill) => {
        this.submitting.set(false);
        this.created.emit(skill);
      },
      error: (failure: unknown) => {
        this.submitting.set(false);
        this.error.set(backendMessage(failure, this.i18n.t('skills.error.create')));
      },
    });
  }

  dismiss(): void {
    this.dismissed.emit();
    queueMicrotask(() => {
      if (this.previousFocus?.isConnected) this.previousFocus.focus();
    });
  }

  @HostListener('document:keydown.escape', ['$event'])
  onEscape(event: Event): void {
    event.preventDefault();
    this.dismiss();
  }

  value(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value;
  }

  private executorParams(): Record<string, unknown> {
    const params: Record<string, unknown> = {};
    for (const field of this.fields()) {
      const raw = this.param(field.key).trim();
      if (!raw) continue;
      params[field.key] = field.control === 'json' || field.control === 'preset_inputs'
        ? JSON.parse(raw)
        : raw;
    }
    return params;
  }

  private draft(): SkillDraft {
    const category = this.category().trim();
    const capabilityId = this.capabilityId().trim();
    return {
      local_name: this.localName().trim(),
      name: this.name().trim(),
      description: this.description().trim(),
      type: this.type().trim() || 'generic',
      category: category || null,
      input_schema: this.inputSchema() ?? {},
      output_schema: this.outputSchema() ?? {},
      executor: { kind: this.executorKind(), params: this.executorParams() },
      ...(capabilityId ? { capability_id: capabilityId } : {}),
    };
  }

  private patch(): Partial<Omit<SkillDraft, 'local_name'>> {
    return {
      name: this.name().trim(),
      description: this.description().trim(),
      type: this.type().trim() || 'generic',
      category: this.category().trim() || null,
      input_schema: this.inputSchema() ?? {},
      output_schema: this.outputSchema() ?? {},
      executor: { kind: this.executorKind(), params: this.executorParams() },
    };
  }

  private seedFrom(skill: Skill): void {
    this.localName.set(skill.slug.split('.').pop() ?? skill.slug);
    this.name.set(skill.name ?? '');
    this.description.set(skill.description ?? '');
    this.type.set(skill.type || 'generic');
    this.category.set(skill.category ?? '');
    this.inputSchema.set(schemaOrNull(skill.input_schema));
    this.outputSchema.set(schemaOrNull(skill.output_schema));
    const executor = skill.executor ?? null;
    this.executorKind.set(executor?.kind ?? '');
    const params: Record<string, string> = {};
    for (const [key, entry] of Object.entries(
      (executor?.params ?? {}) as Record<string, unknown>,
    )) {
      params[key] = typeof entry === 'string' ? entry : JSON.stringify(entry, null, 2);
    }
    this.params.set(params);
  }
}

/** What a saved edit tells the author about its reach. */
export interface SkillUpdateResult {
  readonly skill: Skill;
  /** Systems whose published Flow still dispatches this Skill. */
  readonly publishedIn: string[];
}

function publishedSystemNames(skill: Skill): string[] {
  const bindings = (skill as { published_bindings?: Array<{ system_name?: string }> })
    .published_bindings;
  if (!Array.isArray(bindings)) return [];
  return [...new Set(bindings.map((entry) => entry.system_name).filter(Boolean))] as string[];
}

function schemaOrNull(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return Object.keys(value).length ? (value as Record<string, unknown>) : null;
}

function controlFor(
  key: string,
  spec: { type?: string; enum?: string[]; maxLength?: number },
): ExecutorParamField['control'] {
  if (key === 'model') return 'model';
  if (spec.enum?.length) return 'select';
  // The preset inputs of a wrapped skill: the target contract is already
  // known, so the values are a form rather than an object to write.
  if (key === 'frozen_input') return 'preset_inputs';
  if (spec.type === 'object') return 'json';
  // The only free-text parameter that names another catalog row: a picker keeps
  // the author inside the set the runtime can actually resolve.
  if (key === 'skill_slug') return 'registry_target';
  if ((spec.maxLength ?? 0) > 400) return 'long_text';
  return 'text';
}

function jsonObjectProblem(raw: string, label: string): AuthoringProblem | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { key: 'skills.problem.json', params: { field: label } };
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { key: 'skills.problem.json_object', params: { field: label } };
  }
  return null;
}

/** The server's own words. A refusal names the schema, the binding or the
 * permission at fault, and paraphrasing it would hide what to change. */
export function backendMessage(failure: unknown, fallback = 'The Skill was not created.'): string {
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
  return message || fallback;
}
