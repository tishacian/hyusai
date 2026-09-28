import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin, of, type Observable } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ToastrService } from 'ngx-toastr';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Capability, type Context, type Skill, type System } from '@app/core/canonical-api.service';
import {
  FlowSerializerService,
  type CanonicalFlow,
  type SystemBuilderDraft,
} from '@app/core/flow-serializer.service';
import { I18nService } from '@app/core/i18n.service';
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { SettingsService } from '@app/core/settings.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ZoomContextService } from '@app/core/zoom-context.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  type CkGlyphName,
  CkBackLinkComponent,
  GlyphComponent,
  HelpTooltipComponent,
  LiveDotComponent,
  NavLinkDirective,
  RuntimeStatusBadgeComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { SystemsStore } from './systems.store';
import {
  type AppDef,
  appById,
  readAppToggles,
  writeAppToggles,
} from '../resources/resources.catalog';

type CanvasSectionKey =
  | 'objective'
  | 'capability'
  | 'skills'
  | 'context'
  | 'policy'
  | 'launch';

interface WorkspaceAppsResponse {
  enabled?: string[];
}

interface CanvasSection {
  key: CanvasSectionKey;
  glyph: CkGlyphName;
}

/**
 * Execution modes, by API id. Label, short line and description are read
 * from `systems.builder.execution.<id>.*`.
 */
const EXECUTION_MODES: {
  id:
    | 'real_time_decision'
    | 'batch_processing'
    | 'event_driven_automation'
    | 'continuous_monitoring'
    | 'human_augmented';
}[] = [
  { id: 'real_time_decision' },
  { id: 'batch_processing' },
  { id: 'event_driven_automation' },
  { id: 'continuous_monitoring' },
  { id: 'human_augmented' },
];

/**
 * Retrieval modes. `id` is the value the draft and the serializer carry,
 * `canonical` the API's; the label and description are read from
 * `systems.builder.rag.<canonical>.*`.
 */
const RAG_PIPELINES: { id: string; canonical: string }[] = [
  { id: 'OmniRAG', canonical: 'chah' },
  { id: 'HAH', canonical: 'hah' },
  { id: 'Hybrid', canonical: 'hybrid' },
  { id: 'Semantic', canonical: 'naive' },
  { id: 'None', canonical: 'auto' },
];

interface ReasoningTemplateOpt {
  slug: string;
  label: string;
  description: string;
}

interface ModelOpt {
  id: string;
  label: string;
  provider?: string;
  name?: string;
}

function normalizeModels(raw: Array<Record<string, unknown>>): ModelOpt[] {
  const out: ModelOpt[] = [];
  for (const m of raw) {
    const provider = (m['provider'] as string | undefined) ?? '';
    const name =
      (m['name'] as string | undefined) ??
      (m['model'] as string | undefined) ??
      (m['id'] as string | undefined) ??
      '';
    if (!name) continue;
    const id = provider ? `${provider}:${name}` : name;
    const label = provider ? `${provider} · ${name}` : name;
    out.push({ id, label, provider, name });
  }
  return out;
}

const TIER_TONE: Record<string, 'pos' | 'cool' | 'violet' | 'warn'> = {
  universal: 'pos',
  industry: 'violet',
  client: 'cool',
};

@Component({
  selector: 'app-system-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NavLinkDirective,
    CkBackLinkComponent,
    IconComponent,
    EmptyStateComponent,
    GlyphComponent,
    HelpTooltipComponent,
    LiveDotComponent,
    RuntimeStatusBadgeComponent,
    StatReadoutComponent,
    TagComponent,
    CkObjectHeaderComponent,
  ],
  template: `
    <ck-object-header
      [eyebrow]="i18n.t('experience.adoption.nav.build') + ' · ' + i18n.t('nav.zoom.system')"
      [title]="draft.name || i18n.t('systems.builder.new_title')"
      [subtitle]="draft.objective || i18n.t('systems.builder.subtitle')"
      [kpis]="headerKpis()"
    >
      <span actions>
        <ck-back-link />
        <button
          type="button"
          (click)="switchToFlow()"
          [disabled]="!canSwitchToFlow() || launching()"
          class="ck-btn-quiet inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium mr-2"
          [title]="canSwitchToFlow() ? i18n.t('systems.builder.switch_flow.title') : i18n.t('systems.builder.switch_flow.disabled')"
        >
          <app-icon name="workflow" [size]="14" /> {{ i18n.t('systems.builder.switch_flow') }}
        </button>
        <button
          type="button"
          (click)="launch()"
          [disabled]="!allGatesValid() || launching()"
          class="inline-flex items-center gap-2 px-3 py-2 rounded text-sm font-semibold transition"
          style="background:var(--ck-signal-pos); color:var(--ck-on-signal);"
          [style.opacity]="!allGatesValid() || launching() ? '0.4' : '1'"
          [title]="allGatesValid() ? i18n.t(editingSystemId() ? 'systems.builder.save.title' : 'systems.builder.create.title') : firstInvalidGateMessage()"
        >
          <ck-glyph name="bolt" [size]="12" />
          {{ launching()
            ? i18n.t(editingSystemId() ? 'systems.builder.saving' : 'systems.builder.creating')
            : i18n.t(editingSystemId() ? 'systems.builder.save' : 'systems.builder.create') }}
        </button>
      </span>
    </ck-object-header>

    <!-- Single-surface canvas: every section is always visible, collapsible,
         gated by a live badge. No prev/next — the operator can zoom into any
         concern at any time. -->
    <div class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      <div class="space-y-3">
        @for (section of sections; track section.key) {
          <section
            class="ck-surface rounded-md overflow-hidden"
            [attr.data-section-key]="section.key"
            [style.borderColor]="isSectionValid(section.key) ? 'var(--ck-stroke-soft)' : 'var(--ck-signal-warn)'"
            [style.borderWidth]="isSectionValid(section.key) ? '1px' : '1px'"
          >
            <button
              type="button"
              (click)="toggleSection(section.key)"
              class="w-full flex items-center gap-3 text-left transition"
              style="padding:14px 18px; background: var(--ck-bg-inset);"
              [attr.aria-expanded]="isSectionOpen(section.key)"
              [attr.aria-controls]="isSectionOpen(section.key) ? 'sb-panel-' + section.key : null"
            >
              <div
                class="w-8 h-8 rounded-md flex items-center justify-center shrink-0 ck-surface"
                [style.color]="isSectionValid(section.key) ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
                [style.borderColor]="isSectionValid(section.key) ? 'var(--ck-stroke-soft)' : 'var(--ck-signal-warn)'"
              >
                @if (isSectionValid(section.key)) {
                  <ck-glyph name="check" [size]="14" />
                } @else {
                  <ck-glyph [name]="section.glyph" [size]="14" />
                }
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium text-white">{{ sectionTitle(section.key) }}</span>
                  <span
                    class="text-[11px] px-1.5 py-0.5 rounded"
                    [class.ck-tone-ok]="isSectionValid(section.key)"
                    [class.ck-tone-warn]="!isSectionValid(section.key)"
                  >
                    {{ i18n.t(isSectionValid(section.key) ? 'systems.builder.status.ready' : 'systems.builder.status.pending') }}
                  </span>
                </div>
                <div class="text-[12px]" style="color:var(--ck-fg-3); margin-top:2px;">
                  {{ sectionSummary(section.key) }}
                </div>
              </div>
              <ck-glyph
                [name]="isSectionOpen(section.key) ? 'arrow-right' : 'arrow-right'"
                [size]="12"
                [style.transform]="isSectionOpen(section.key) ? 'rotate(90deg)' : 'none'"
              />
            </button>
            @if (isSectionOpen(section.key)) {
              <div
                [id]="'sb-panel-' + section.key"
                style="padding:20px 22px; border-top: 1px solid var(--ck-hair);"
                [style.opacity]="isSectionLocked(section.key) ? '0.55' : '1'"
                [style.pointerEvents]="isSectionLocked(section.key) ? 'none' : 'auto'"
              >
              @if (isSectionLocked(section.key)) {
                <div
                  class="ck-tone-warn flex items-center gap-2"
                  style="padding:8px 12px; margin-bottom:14px; border-radius:6px; pointer-events:auto;"
                >
                  <ck-glyph name="bolt" [size]="12" />
                  <div class="flex-1 text-xs">
                    {{ i18n.t('systems.builder.locked') }}
                  </div>
                  <a
                    [navLink]="{ leaf: 'system-flow', ref: editingSystemId()! }"
                    class="text-[11px] px-2 py-1 rounded"
                    style="border:1px solid currentColor; pointer-events:auto;"
                  >
                    {{ i18n.t('systems.builder.open_in_flow') }}
                  </a>
                </div>
              }
        @if (section.key === 'objective') {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="focus" [size]="16" />
                {{ sectionTitle('objective') }}
                <ck-help id="builder.steps.overview" />
              </h2>
              <p class="sb-intro">{{ i18n.t('systems.builder.objective.intro') }}</p>
            </header>
            <div>
              <label class="sb-label" for="sb-name">
                {{ i18n.t('systems.builder.objective.name') }} <span aria-hidden="true" style="color:var(--ck-signal-neg);">*</span>
              </label>
              <input
                id="sb-name"
                type="text"
                [(ngModel)]="draft.name"
                name="name"
                required
                class="ck-surface ck-mono w-full"
                style="padding: 10px 12px; border-radius:4px; font-size:14px; background:var(--ck-bg-inset);"
                [placeholder]="i18n.t('systems.builder.objective.name_placeholder')"
              />
            </div>
            <div>
              <label class="sb-label" for="sb-objective">
                {{ sectionTitle('objective') }}
              </label>
              <textarea
                id="sb-objective"
                [(ngModel)]="draft.objective"
                name="objective"
                rows="3"
                class="ck-surface w-full"
                style="padding: 10px 12px; border-radius:4px; font-size:13px; background:var(--ck-bg-inset); resize: none;"
                aria-describedby="sb-objective-hint"
                [placeholder]="i18n.t('systems.builder.objective.placeholder')"
              ></textarea>
              <p id="sb-objective-hint" class="sb-hint" style="margin-top:4px;">
                {{ i18n.t('systems.builder.objective.hint') }}
              </p>
            </div>
          </div>
        }

        @if (section.key === 'capability') {
          <div class="space-y-4">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="cube" [size]="16" />
                {{ sectionTitle('capability') }}
              </h2>
              <p class="sb-intro">{{ i18n.t('systems.builder.capability.intro') }}</p>
            </header>

            @if (loadingCaps()) {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                @for (_ of [0, 1, 2, 3]; track $index) {
                  <div class="h-28 rounded-md ck-surface" style="background:var(--ck-bg-inset); animation: pulse 2s ease-in-out infinite;"></div>
                }
              </div>
            } @else if (capabilities().length === 0) {
              <app-empty-state
                icon="database"
                [title]="i18n.t('systems.builder.capability.empty.title')"
                [description]="i18n.t('systems.builder.capability.empty.description')"
              />
            } @else {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                @for (cap of capabilities(); track cap.id) {
                  <button
                    type="button"
                    (click)="selectCapability(cap)"
                    class="text-left transition ck-surface rounded-md"
                    [attr.aria-pressed]="draft.capability_id === cap.id"
                    [style.padding]="'14px 16px'"
                    [style.borderColor]="draft.capability_id === cap.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    [style.boxShadow]="draft.capability_id === cap.id ? 'var(--ck-glow-cool)' : 'none'"
                  >
                    <div class="flex items-start justify-between gap-3 mb-2">
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <ck-tag [tone]="tierTone(cap.tier)" variant="soft">{{ tierLabel(cap.tier) }}</ck-tag>
                          @if (cap.industry) {
                            <ck-tag tone="violet" variant="outline">{{ cap.industry }}</ck-tag>
                          }
                        </div>
                        <div class="text-sm font-medium text-white truncate">{{ cap.name }}</div>
                      </div>
                      @if (draft.capability_id === cap.id) {
                        <ck-live-dot tone="cool" />
                      }
                    </div>
                    <p style="font-size:12px; color:var(--ck-fg-3); line-height:1.5; margin-bottom:10px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
                      {{ cap.description || '—' }}
                    </p>
                    <div class="flex items-center justify-between">
                      <span class="sb-hint">
                        {{ i18n.t('systems.builder.capability.skills_count', { count: '' + (cap.skill_ids?.length || 0) }) }} · {{ cap.input_unit || '—' }} → {{ cap.output_unit || '—' }}
                      </span>
                      <span class="ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
                        {{ formatPrice(cap.pricing?.unit_price) }}
                      </span>
                    </div>
                  </button>
                }
              </div>
            }

          </div>
        }

        @if (section.key === 'skills') {
          <div class="space-y-4">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="cube" [size]="16" />
                {{ sectionTitle('skills') }}
                <ck-help id="builder.steps.skills" />
              </h2>
              <p class="sb-intro">{{ i18n.t('systems.builder.skills.intro') }}</p>
            </header>

            @if (!draft.capability_id) {
              <app-empty-state
                icon="cube"
                [title]="i18n.t('systems.builder.skills.empty_pick.title')"
                [description]="i18n.t('systems.builder.skills.empty_pick.description')"
              />
            } @else if (bundledSkills().length === 0) {
              <app-empty-state
                icon="cube"
                [title]="i18n.t('systems.builder.skills.empty_none.title')"
                [description]="i18n.t('systems.builder.skills.empty_none.description')"
              />
            } @else {
              <div>
                <div class="sb-label flex items-center gap-2" style="margin-bottom:12px;">
                  <ck-glyph name="ledger" [size]="12" />
                  {{ i18n.t('systems.builder.skills.bundled', { count: '' + bundledSkills().length }) }}
                </div>
                <ul style="display:flex; flex-direction:column; gap:4px;">
                  @for (sk of bundledSkills(); track sk.id) {
                    <li style="display:grid; grid-template-columns: 96px 110px 1fr 80px 70px; gap:10px; align-items:center; padding:8px 12px; border-radius:4px; background:var(--ck-bg-inset);">
                      <ck-tag [tone]="certTone(sk.certification_level)" variant="outline">
                        {{ certLabel(sk.certification_level) }}
                      </ck-tag>
                      <ck-runtime-status [status]="sk.runtime_status" />
                      <div style="min-width:0;">
                        <div style="font-size:12px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                          {{ sk.name }}
                        </div>
                        <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                          {{ sk.slug }}
                        </div>
                      </div>
                      <span class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); text-align:right;">
                        {{ sk.type || '—' }}
                      </span>
                      <span class="ck-mono ck-tnum" style="font-size:10px; color:var(--ck-fg-3); text-align:right;">
                        {{ formatPrice(sk.pricing?.unit_price) }}
                      </span>
                    </li>
                  }
                </ul>
                @if (stubSkillsCount() > 0 || unboundSkillsCount() > 0) {
                  <div class="mt-3" style="font-size:12px; color:var(--ck-signal-warn);">
                    {{ i18n.t('systems.builder.skills.warning', { stubs: '' + stubSkillsCount(), missing: '' + unboundSkillsCount() }) }}
                  </div>
                }
              </div>
            }

            <div style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div class="sb-label flex items-center gap-2" style="margin-bottom:12px;">
                <ck-glyph name="cube" [size]="12" />
                {{ i18n.t('systems.builder.apps.title', { count: '' + enabledApps().length }) }}
              </div>
              @if (enabledApps().length === 0) {
                <p class="text-xs" style="color:var(--ck-fg-4);">
                  {{ i18n.t('systems.builder.apps.empty') }}
                  <a [navLink]="{ surface: 'apps' }" class="ck-accent">{{ i18n.t('systems.builder.apps.manage') }}</a>
                </p>
              } @else {
                <ul style="display:flex; flex-direction:column; gap:4px;">
                  @for (app of enabledApps(); track app.id) {
                    <li style="display:grid; grid-template-columns: 84px 1fr auto; gap:10px; align-items:center; padding:8px 12px; border-radius:4px; background:var(--ck-bg-inset);">
                      <ck-tag [tone]="app.wiring === 'wired' ? 'cool' : 'warn'" variant="outline">
                        {{ i18n.t(app.wiring === 'wired' ? 'systems.builder.apps.wired' : 'systems.builder.apps.catalog') }}
                      </ck-tag>
                      <div style="min-width:0;">
                        <div style="font-size:12px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                          {{ app.name }}
                        </div>
                        <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                          {{ app.id }}
                          @if (app.skillSlugs; as slugs) {
                            @if (slugs.length) {
                              · {{ slugs.join(', ') }}
                            }
                          }
                        </div>
                      </div>
                      @if (app.wiring === 'wired' && app.connectorRoute) {
                        <a
                          [navLink]="{ leaf: 'connector-rpa-bridge' }"
                          class="ck-accent"
                          style="font-size:11px; white-space:nowrap;"
                        >
                          {{ i18n.t('systems.builder.apps.configure') }}
                        </a>
                      } @else {
                        <a
                          [navLink]="{ surface: 'apps' }"
                          style="font-size:11px; color:var(--ck-fg-3); white-space:nowrap;"
                        >
                          {{ i18n.t('systems.builder.apps.catalog') }}
                        </a>
                      }
                    </li>
                  }
                </ul>
              }
            </div>
          </div>
        }

        @if (section.key === 'context') {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="ledger" [size]="16" />
                {{ sectionTitle('context') }}
                <ck-help id="builder.steps.context" />
              </h2>
              <p class="sb-intro">{{ i18n.t('systems.builder.context.intro') }}</p>
            </header>

            <!-- Reuse existing context -->
            @if (existingContexts().length > 0) {
              <div style="border-bottom: 1px solid var(--ck-hair); padding-bottom:16px;">
                <div class="sb-label" id="sb-reuse-label">
                  {{ i18n.t('systems.builder.context.reuse') }}
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2" role="group" aria-labelledby="sb-reuse-label">
                  @for (ctx of existingContexts(); track ctx.id) {
                    <button
                      type="button"
                      (click)="pickExistingContext(ctx.id)"
                      class="text-left ck-surface rounded"
                      style="padding:10px 12px;"
                      [attr.aria-pressed]="draft.reuse_context_id === ctx.id"
                      [style.borderColor]="draft.reuse_context_id === ctx.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    >
                      <div class="text-sm font-medium text-white truncate">{{ ctx.name }}</div>
                      <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                        {{ i18n.t('systems.builder.context.refs', { version: '' + (ctx.version ?? 1), count: '' + (ctx.data_refs?.length ?? 0) }) }}
                      </div>
                    </button>
                  }
                </div>
                @if (draft.reuse_context_id) {
                  <button
                    type="button"
                    class="mt-2 text-[12px]"
                    style="color: var(--ck-signal-warn);"
                    (click)="clearContextReuse()"
                  >
                    {{ i18n.t('systems.builder.context.clear') }}
                  </button>
                }
              </div>
            }

            @if (loadingCollections()) {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (_ of [0, 1, 2, 3]; track $index) {
                  <div class="h-16 rounded-md ck-surface" style="background:var(--ck-bg-inset);"></div>
                }
              </div>
            } @else if (collections().length === 0) {
              <app-empty-state
                icon="database"
                [title]="i18n.t('systems.builder.context.empty.title')"
                [description]="i18n.t('systems.builder.context.empty.description')"
              >
                <a
                  [navLink]="{ surface: 'knowledge' }"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium text-white transition"
                  style="background: var(--ck-signal-cool); color: var(--ck-on-signal);"
                >
                  {{ i18n.t('systems.builder.context.empty.open') }}
                </a>
              </app-empty-state>
            } @else {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                @for (col of collections(); track col) {
                  <label
                    class="flex items-center gap-3 ck-surface rounded cursor-pointer"
                    style="padding:10px 12px; border-radius:4px;"
                    [style.borderColor]="isCollectionChecked(col) ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                  >
                    <input
                      type="checkbox"
                      [checked]="isCollectionChecked(col)"
                      (change)="toggleCollection(col)"
                      class="accent-cyan-400"
                    />
                    <span class="ck-mono" style="font-size:12px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                      {{ col }}
                    </span>
                  </label>
                }
              </div>
            }

            <div style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div class="sb-label" id="sb-retrieval-label">
                {{ i18n.t('systems.builder.context.retrieval') }}
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-2" role="group" aria-labelledby="sb-retrieval-label">
                @for (mode of ragPipelines; track mode.id) {
                  <button
                    type="button"
                    (click)="draft.rag_mode = mode.id"
                    class="text-left transition ck-surface rounded"
                    style="padding:10px 12px;"
                    [title]="presetHealthTitle(mode.id)"
                    [attr.aria-pressed]="draft.rag_mode === mode.id"
                    [style.opacity]="presetStatus(mode.id) === 'bound' ? 1 : 0.82"
                    [style.borderColor]="draft.rag_mode === mode.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                  >
                    <div class="flex items-center gap-2 mb-1" style="justify-content:space-between;">
                      <div class="text-sm font-medium" [style.color]="draft.rag_mode === mode.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-2)'">
                        {{ ragLabel(mode.id) }}
                      </div>
                      <ck-runtime-status [status]="presetStatus(mode.id)" />
                    </div>
                    <div class="sb-hint">
                      {{ ragDescription(mode.canonical) }}
                    </div>
                  </button>
                }
              </div>
            </div>
          </div>
        }

        @if (section.key === 'policy') {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="sliders" [size]="16" />
                {{ sectionTitle('policy') }}
                <ck-help id="builder.steps.policy" />
              </h2>
              <p class="sb-intro">{{ i18n.t('systems.builder.policy.intro') }}</p>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label class="sb-label sb-label-row" for="sb-max-cost">
                  <span>{{ i18n.t('systems.builder.policy.max_cost') }}</span>
                  <span class="ck-mono ck-tnum" style="color:var(--ck-signal-cool);">\${{ draft.max_cost.toFixed(2) }}</span>
                </label>
                <input id="sb-max-cost" type="range" min="0.01" max="5" step="0.01" [(ngModel)]="draft.max_cost" class="w-full accent-cyan-400" />
              </div>
              <div>
                <label class="sb-label sb-label-row" for="sb-max-latency">
                  <span>{{ i18n.t('systems.builder.policy.max_latency') }}</span>
                  <span class="ck-mono ck-tnum" style="color:var(--ck-signal-cool);">{{ draft.max_latency_ms }}</span>
                </label>
                <input id="sb-max-latency" type="range" min="500" max="60000" step="500" [(ngModel)]="draft.max_latency_ms" class="w-full accent-cyan-400" />
              </div>
              <div>
                <label class="sb-label sb-label-row" for="sb-confidence">
                  <span>{{ i18n.t('systems.builder.policy.confidence') }}</span>
                  <span class="ck-mono ck-tnum" style="color:var(--ck-signal-violet);">{{ draft.confidence_threshold.toFixed(2) }}</span>
                </label>
                <input id="sb-confidence" type="range" min="0" max="1" step="0.01" [(ngModel)]="draft.confidence_threshold" class="w-full accent-sky-400" aria-describedby="sb-confidence-hint" />
                <p id="sb-confidence-hint" class="sb-hint" style="margin-top:4px;">
                  {{ i18n.t('systems.builder.policy.confidence_hint') }}
                </p>
              </div>
              <div>
                <label class="sb-label sb-label-row" for="sb-temperature">
                  <span>{{ i18n.t('systems.builder.policy.temperature') }}</span>
                  <span class="ck-mono ck-tnum" style="color:var(--ck-signal-violet);">{{ draft.temperature.toFixed(2) }}</span>
                </label>
                <input id="sb-temperature" type="range" min="0" max="2" step="0.05" [(ngModel)]="draft.temperature" class="w-full accent-sky-400" />
              </div>
            </div>

            <div style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div class="sb-label" id="sb-execution-label">
                {{ i18n.t('systems.builder.policy.execution_mode') }}
              </div>
              <div class="grid grid-cols-2 md:grid-cols-5 gap-2" role="group" aria-labelledby="sb-execution-label">
                @for (mode of executionModes; track mode.id) {
                  <button
                    type="button"
                    (click)="draft.execution_mode = mode.id"
                    class="text-left transition ck-surface rounded"
                    style="padding:10px 12px;"
                    [title]="executionModeText(mode.id, 'description')"
                    [attr.aria-pressed]="draft.execution_mode === mode.id"
                    [style.borderColor]="draft.execution_mode === mode.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    [style.boxShadow]="draft.execution_mode === mode.id ? 'var(--ck-glow-cool)' : 'none'"
                  >
                    <div class="text-sm font-medium" [style.color]="draft.execution_mode === mode.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-2)'">
                      {{ executionModeText(mode.id, 'label') }}
                    </div>
                    <div class="sb-hint" style="margin-top:2px;">
                      {{ executionModeText(mode.id, 'short') }}
                    </div>
                  </button>
                }
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5" style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div>
                <label class="sb-label" for="sb-reasoning">
                  {{ i18n.t('systems.builder.policy.reasoning') }}
                </label>
                <select
                  id="sb-reasoning"
                  [(ngModel)]="draft.default_prompt_type"
                  class="w-full ck-surface rounded"
                  style="padding:10px 12px; background:var(--ck-bg-inset); color:var(--ck-fg-1); font-size:13px;"
                  aria-describedby="sb-reasoning-hint"
                >
                  <option value="auto">{{ i18n.t('systems.builder.policy.reasoning_auto') }}</option>
                  @for (t of reasoningTemplates(); track t.slug) {
                    <option [value]="t.slug">{{ t.label }} — {{ t.description }}</option>
                  }
                </select>
                <p id="sb-reasoning-hint" class="sb-hint" style="margin-top:6px;">
                  {{ i18n.t('systems.builder.policy.reasoning_hint') }}
                </p>
              </div>
              <div>
                @if (isDemoMode()) {
                  <div class="sb-label">
                    {{ i18n.t('systems.builder.policy.runtime') }}
                  </div>
                  <div class="w-full ck-surface rounded" style="padding:10px 12px; background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:13px;">
                    {{ i18n.t('systems.builder.policy.managed') }}
                  </div>
                  <p class="sb-hint" style="margin-top:6px;">
                    {{ i18n.t('systems.builder.policy.managed_hint') }}
                  </p>
                } @else {
                  <label class="sb-label" for="sb-model">
                    {{ i18n.t('systems.builder.policy.model_override') }}
                  </label>
                  <select
                    id="sb-model"
                    [(ngModel)]="draft.default_model"
                    class="w-full ck-surface rounded"
                    style="padding:10px 12px; background:var(--ck-bg-inset); color:var(--ck-fg-1); font-size:13px;"
                    aria-describedby="sb-model-hint"
                  >
                    <option value="">{{ i18n.t('systems.builder.policy.model_default') }}</option>
                    @for (m of availableModels(); track m.id) {
                      <option [value]="m.id">{{ m.label }}</option>
                    }
                  </select>
                  <p id="sb-model-hint" class="sb-hint" style="margin-top:6px;">
                    {{ i18n.t('systems.builder.policy.model_hint') }}
                  </p>
                }
              </div>
            </div>

            <div class="space-y-2" style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <label class="flex items-start gap-3 ck-surface cursor-pointer" style="padding:12px 14px; border-radius:4px;">
                <input type="checkbox" [(ngModel)]="draft.require_citations" class="accent-cyan-400 mt-0.5" aria-describedby="sb-citations-hint" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">{{ i18n.t('systems.builder.policy.citations') }}</div>
                  <div id="sb-citations-hint" class="sb-hint">
                    {{ i18n.t('systems.builder.policy.citations_hint') }}
                  </div>
                </div>
              </label>
              <label class="flex items-start gap-3 ck-surface cursor-pointer" style="padding:12px 14px; border-radius:4px;">
                <input type="checkbox" [(ngModel)]="draft.enable_audit" class="accent-cyan-400 mt-0.5" aria-describedby="sb-audit-hint" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">{{ i18n.t('systems.builder.policy.audit') }}</div>
                  <div id="sb-audit-hint" class="sb-hint">
                    {{ i18n.t('systems.builder.policy.audit_hint') }}
                  </div>
                </div>
              </label>
            </div>
          </div>
        }

        @if (section.key === 'launch') {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="bolt" [size]="16" />
                {{ sectionTitle('launch') }}
              </h2>
              <p class="sb-intro">{{ i18n.t('systems.builder.launch.intro') }}</p>
            </header>

            <!-- ROI projection -->
            <div class="ck-surface rounded" style="padding:16px 18px; background: var(--ck-bg-inset);">
              <div class="sb-label" style="margin-bottom:12px;">
                {{ i18n.t('systems.builder.launch.projected') }}
              </div>
              <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:18px;">
                <ck-stat-readout [label]="i18n.t('systems.builder.launch.cost')" [value]="formatPrice(selectedCapability()?.pricing?.unit_price)" tone="cool" [size]="16" />
                <ck-stat-readout [label]="i18n.t('systems.builder.launch.value')" [value]="formatPrice(selectedCapability()?.value_per_outcome)" tone="pos" [size]="16" />
                <ck-stat-readout [label]="i18n.t('systems.builder.launch.margin')" [value]="projectedMargin()" tone="pos" [size]="16" />
                <ck-stat-readout [label]="i18n.t('systems.builder.launch.roi')" [value]="projectedRoi()" tone="violet" [size]="16" />
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="sb-label">{{ sectionTitle('objective') }}</div>
                <div class="text-sm font-medium text-white">{{ draft.name || i18n.t('systems.builder.launch.untitled') }}</div>
                <div style="font-size:12px; color:var(--ck-fg-3); margin-top:4px; line-height:1.5; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">
                  {{ draft.objective || i18n.t('systems.builder.launch.no_objective') }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="sb-label">{{ sectionTitle('capability') }}</div>
                <div class="text-sm font-medium text-white">{{ selectedCapability()?.name || '—' }}</div>
                <div style="font-size:12px; color:var(--ck-fg-3); margin-top:4px;">
                  {{ i18n.t('systems.builder.launch.skills_bundled', { tier: selectedCapability() ? tierLabel(selectedCapability()?.tier) : '—', count: '' + bundledSkills().length }) }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="sb-label">{{ sectionTitle('context') }}</div>
                <div class="text-sm text-white">
                  {{ collectionsLabel(draft.collections.length) }}
                </div>
                <div style="font-size:12px; color:var(--ck-fg-3); margin-top:4px;">
                  {{ i18n.t('systems.builder.launch.retrieval', { mode: ragLabel(draft.rag_mode) }) }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="sb-label">{{ sectionTitle('policy') }}</div>
                <div style="font-size:12px; color:var(--ck-fg-3); line-height:1.7;">
                  {{ i18n.t('systems.builder.launch.mode') }} <span style="color:var(--ck-fg-2);">{{ executionModeLabel() }}</span><br />
                  {{ i18n.t('systems.builder.launch.max_cost') }} <span class="ck-mono ck-tnum" style="color:var(--ck-fg-2);">\${{ draft.max_cost.toFixed(2) }}</span> ·
                  {{ i18n.t('systems.builder.launch.max_latency') }} <span class="ck-mono ck-tnum" style="color:var(--ck-fg-2);">{{ draft.max_latency_ms }} ms</span><br />
                  {{ i18n.t('systems.builder.launch.confidence') }} <span class="ck-mono ck-tnum" style="color:var(--ck-fg-2);">{{ draft.confidence_threshold.toFixed(2) }}</span> ·
                  {{ i18n.t('systems.builder.launch.temperature') }} <span class="ck-mono ck-tnum" style="color:var(--ck-fg-2);">{{ isDemoMode() ? i18n.t('systems.builder.launch.managed') : draft.temperature.toFixed(2) }}</span>
                </div>
              </div>
            </div>
          </div>
        }
              </div>
            }
          </section>
        }
      </div>

      <aside class="ck-surface rounded-md self-start sticky top-4" style="padding:20px;" [attr.aria-label]="i18n.t('systems.builder.preview.title')">
        <div class="flex items-center gap-3 mb-4 pb-3" style="border-bottom: 1px solid var(--ck-hair);">
          <div class="w-10 h-10 rounded-md flex items-center justify-center ck-surface" style="background:var(--ck-bg-inset); border-color: var(--ck-stroke-soft);">
            <ck-glyph name="focus" [size]="18" />
          </div>
          <div>
            <div class="sb-label" style="margin-bottom:0;">
              {{ i18n.t('systems.builder.preview.title') }}
            </div>
            <div class="text-sm font-medium text-white truncate">{{ draft.name || i18n.t('systems.builder.new_title') }}</div>
          </div>
        </div>

        <ul class="space-y-3">
          <li class="flex items-center gap-2">
            <ck-glyph name="focus" [size]="12" />
            <span class="sb-label" style="margin-bottom:0;">{{ sectionTitle('objective') }}</span>
            <span class="ml-auto" style="font-size:12px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">
              {{ draft.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="cube" [size]="12" />
            <span class="sb-label" style="margin-bottom:0;">{{ sectionTitle('capability') }}</span>
            <span class="ml-auto" style="font-size:12px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">
              {{ selectedCapability()?.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="ledger" [size]="12" />
            <span class="sb-label" style="margin-bottom:0;">{{ sectionTitle('context') }}</span>
            <span class="ml-auto ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              {{ draft.collections.length }} · {{ ragLabel(draft.rag_mode) }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="sliders" [size]="12" />
            <span class="sb-label" style="margin-bottom:0;">{{ sectionTitle('policy') }}</span>
            <span class="ml-auto ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              \${{ draft.max_cost.toFixed(2) }} · τ{{ draft.confidence_threshold.toFixed(2) }}
            </span>
          </li>
        </ul>

        <div class="mt-4 pt-4" style="border-top: 1px solid var(--ck-hair);">
          <div class="flex items-center justify-between mb-2">
            <span class="sb-label" style="margin-bottom:0;">{{ i18n.t('systems.builder.gates.title') }}</span>
            <span
              class="ck-mono ck-tnum"
              style="font-size:11px;"
              [style.color]="allGatesValid() ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
            >
              {{ gatesValidCount() }} / {{ sections.length }}
            </span>
          </div>
          <ul class="space-y-1.5">
            @for (section of sections; track section.key) {
              <li class="flex items-center gap-2">
                <span
                  class="inline-block w-2 h-2 rounded-full"
                  aria-hidden="true"
                  [style.background]="isSectionValid(section.key) ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
                ></span>
                <span style="font-size:12px; color:var(--ck-fg-3);">
                  {{ sectionTitle(section.key) }}
                </span>
                @if (!isSectionValid(section.key)) {
                  <button
                    type="button"
                    (click)="expandSection(section.key)"
                    class="ml-auto text-[12px]"
                    style="color:var(--ck-signal-warn);"
                    [attr.aria-label]="i18n.t('systems.builder.gates.fix_label', { section: sectionTitle(section.key) })"
                  >
                    {{ i18n.t('systems.builder.gates.fix') }}
                  </button>
                }
              </li>
            }
          </ul>
        </div>

        @if (!allGatesValid()) {
          <div class="mt-4" style="font-size:12px; color:var(--ck-signal-warn);">
            ⚠ {{ firstInvalidGateMessage() }}
          </div>
        }
      </aside>
    </div>
  `,
  styles: [`
    /* Field and group labels: sentence case, readable size — no mono capitals. */
    .sb-label {
      display: block;
      font-size: 12px;
      line-height: 16px;
      font-weight: 500;
      color: var(--ck-fg-3);
      margin-bottom: 8px;
    }
    .sb-label-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .sb-intro {
      font-size: 13px;
      line-height: 1.5;
      color: var(--ck-fg-3);
      margin-top: 4px;
    }
    .sb-hint {
      font-size: 12px;
      line-height: 1.45;
      color: var(--ck-fg-3);
    }
  `],
})
export class SystemBuilderComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly navigation = inject(ZoomContextService);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly health = inject(RuntimeHealthService);
  private readonly toast = inject(ToastrService);
  private readonly store = inject(SystemsStore);
  private readonly serializer = inject(FlowSerializerService);
  private readonly workspace = inject(WorkspaceService);
  readonly settings = inject(SettingsService);
  readonly i18n = inject(I18nService);
  readonly isDemoMode = computed(() => this.workspace.isDemoSafeMode());

  /**
   * When set, the builder is editing an existing System (Flow → Form
   * round-trip). Some sections may be locked as read-only depending on
   * `flow_definition.extended` / `source`.
   */
  readonly editingSystemId = signal<string | null>(null);
  readonly editingSystem = signal<System | null>(null);
  readonly flowExtended = signal(false);
  readonly flowSource = signal<'form' | 'flow'>('form');
  /** Sections frozen in read-only because the Flow builder added custom nodes. */
  readonly lockedSections = signal<Set<CanvasSectionKey>>(new Set());

  readonly ragPipelines = RAG_PIPELINES;
  readonly executionModes = EXECUTION_MODES;

  /** Label of the draft's execution mode; the raw id when the API sends an unknown one. */
  executionModeLabel(): string {
    return this.executionModeText(this.draft.execution_mode, 'label');
  }

  executionModeText(id: string, part: 'label' | 'short' | 'description'): string {
    const key = `systems.builder.execution.${id}.${part}`;
    const text = this.i18n.t(key);
    return text === key ? id : text;
  }

  /** Label of a retrieval mode by draft id (`OmniRAG`, `Hybrid`…). */
  ragLabel(id: string): string {
    const canonical = RAG_PIPELINES.find((p) => p.id === id)?.canonical;
    return canonical ? this.i18n.t(`systems.builder.rag.${canonical}.label`) : id;
  }

  ragDescription(canonical: string): string {
    return this.i18n.t(`systems.builder.rag.${canonical}.description`);
  }

  sectionTitle(key: CanvasSectionKey): string {
    return this.i18n.t(`systems.builder.section.${key}`);
  }

  /** Capability tier (`universal`, `industry`, `client`), in words. */
  tierLabel(tier: string | undefined): string {
    const value = tier || 'universal';
    const key = `hypervisor.tier.${value}`;
    const text = this.i18n.t(key);
    return text === key ? value : text;
  }

  /** Skill certification (`basic`, `production`, `enterprise`), in words. */
  certLabel(cert: string | undefined): string {
    const value = cert || 'basic';
    const key = `skills.cert.${value}`;
    const text = this.i18n.t(key);
    return text === key ? value : text;
  }

  collectionsLabel(count: number): string {
    return count === 1
      ? this.i18n.t('systems.builder.collections_one', { count: String(count) })
      : this.i18n.t('systems.builder.collections', { count: String(count) });
  }

  /**
   * Single-surface canvas — all sections are available at once (no linear
   * wizard). Each section is its own `CanvasSection` with a gate; the
   * launch action unlocks only when every gate turns green.
   */
  readonly sections: CanvasSection[] = [
    { key: 'objective', glyph: 'focus' },
    { key: 'capability', glyph: 'cube' },
    { key: 'skills', glyph: 'cube' },
    { key: 'context', glyph: 'ledger' },
    { key: 'policy', glyph: 'sliders' },
    { key: 'launch', glyph: 'bolt' },
  ];

  /** Set of expanded accordion sections; all open by default. */
  readonly openSections = signal<Set<CanvasSectionKey>>(
    new Set<CanvasSectionKey>([
      'objective',
      'capability',
      'skills',
      'context',
      'policy',
      'launch',
    ]),
  );
  readonly launching = signal(false);

  readonly capabilities = signal<Capability[]>([]);
  readonly loadingCaps = signal(false);
  readonly skills = signal<Skill[]>([]);
  readonly collections = signal<string[]>([]);
  readonly loadingCollections = signal(false);
  /** Enabled workspace app ids (API-authoritative, localStorage as cache). */
  readonly enabledAppIds = signal<string[]>([]);
  readonly enabledApps = computed<AppDef[]>(() => {
    const ids = this.enabledAppIds();
    return ids
      .map((id) => appById(id) ?? {
        id,
        name: id.replace(/_/g, ' '),
        description: '',
        icon: 'plug',
        status: 'ready' as const,
        wiring: 'catalog' as const,
      })
      .filter(Boolean);
  });

  draft = {
    name: '',
    objective: '',
    capability_id: '' as string | null,
    collections: [] as string[],
    rag_mode: 'OmniRAG',
    // If set, the new System reuses this Context id instead of creating a
    // fresh one from the chosen collections.
    reuse_context_id: '' as string | null,
    // Per-System defaults surfaced in the Policy step; picked up by the run
    // engine / RAG skill wrappers when a run is triggered.
    default_prompt_type: 'auto',
    default_model: '' as string | '',
    execution_mode: 'real_time_decision' as
      | 'real_time_decision'
      | 'batch_processing'
      | 'event_driven_automation'
      | 'continuous_monitoring'
      | 'human_augmented',
    temperature: 0.3,
    max_cost: 0.5,
    max_latency_ms: 8000,
    confidence_threshold: 0.6,
    require_citations: true,
    enable_audit: true,
  };

  readonly reasoningTemplates = signal<ReasoningTemplateOpt[]>([]);
  readonly availableModels = signal<ModelOpt[]>([]);
  readonly existingContexts = signal<Context[]>([]);

  /**
   * Signal mirror of `draft.capability_id`. `draft` is a plain object, so a
   * `computed` reading it alone kept the capability found at first render:
   * picking a card left the Launch review, the preview and the Skills list
   * on "—". Every write to the draft's capability goes through here too.
   */
  private readonly capabilityId = signal<string | null>(null);

  readonly selectedCapability = computed<Capability | null>(() => {
    const id = this.capabilityId();
    if (!id) return null;
    return this.capabilities().find((c) => c.id === id) ?? null;
  });

  readonly bundledSkills = computed<Skill[]>(() => {
    const cap = this.selectedCapability();
    if (!cap) return [];
    const ids = new Set(cap.skill_ids || []);
    return this.skills().filter((s) => ids.has(s.id));
  });

  readonly stubSkillsCount = computed(
    () => this.bundledSkills().filter((s) => s.runtime_status === 'stub').length,
  );
  readonly unboundSkillsCount = computed(
    () =>
      this.bundledSkills().filter(
        (s) => s.runtime_status === 'unbound' || s.runtime_status === 'catalog_only',
      ).length,
  );

  readonly projectedMargin = computed(() => {
    const cap = this.selectedCapability();
    if (!cap?.value_per_outcome || cap?.pricing?.unit_price == null) return '—';
    const m = cap.value_per_outcome - cap.pricing.unit_price;
    return `$${m.toFixed(2)}`;
  });

  readonly projectedRoi = computed(() => {
    const cap = this.selectedCapability();
    if (!cap?.value_per_outcome || !cap?.pricing?.unit_price) return '—';
    const roi = (cap.value_per_outcome - cap.pricing.unit_price) / cap.pricing.unit_price;
    return `${(roi * 100).toFixed(0)}%`;
  });

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    if (q.get('name')) this.draft.name = q.get('name') ?? '';
    if (q.get('objective')) this.draft.objective = q.get('objective') ?? '';

    const editId = q.get('systemId');
    if (editId) {
      // Edit mode: round-trip an existing System's flow back into the
      // canvas. Sections authored in Flow with custom nodes will be
      // rendered read-only further down.
      this.canonical.getSystem(editId).subscribe({
        next: (sys) => {
          if (sys) this.hydrateFromSystem(sys);
        },
      });
    } else {
      // Creation mode — no owning System yet; clear the System scope
      // and any stale Run focus. A pre-filled capability_id (coming from
      // a "create system for this capability" jump) will be applied
      // through `selectCapability` below.
    }

    this.settings.refresh();
    this.health.load().subscribe();
    this.loadEnabledApps();
    this.loadingCaps.set(true);
    this.loadingCollections.set(true);
    this.api
      .get<{ templates: ReasoningTemplateOpt[] }>('/reasoning/templates')
      .subscribe({
        next: (res) => this.reasoningTemplates.set(res?.templates ?? []),
        error: () => this.reasoningTemplates.set([]),
      });
    this.api
      .get<{ models: Array<Record<string, unknown>> }>('/models')
      .subscribe({
        next: (res) => this.availableModels.set(normalizeModels(res?.models ?? [])),
        error: () => this.availableModels.set([]),
      });
    this.canonical.listContexts().subscribe({
      next: (list) => this.existingContexts.set(list ?? []),
      error: () => this.existingContexts.set([]),
    });
    forkJoin({
      caps: this.canonical.listCapabilities().pipe(catchError(() => of([] as Capability[]))),
      skills: this.canonical.listSkills().pipe(catchError(() => of([] as Skill[]))),
      collections: this.api
        .get<{ collections: string[] }>('/documents/collections')
        .pipe(catchError(() => of({ collections: [] }))),
    }).subscribe(({ caps, skills, collections }) => {
      this.capabilities.set(caps);
      this.skills.set(skills);
      const cols = collections?.collections ?? [];
      this.collections.set(cols);
      if (cols.length && this.draft.collections.length === 0) {
        this.draft.collections = [cols[0]];
      }
      const s = this.settings.settings();
      if (typeof s.temperature === 'number') this.draft.temperature = s.temperature;
      if (typeof s.ragSimilarityThreshold === 'number') {
        this.draft.confidence_threshold = Math.max(0.4, s.ragSimilarityThreshold);
      }
      this.loadingCaps.set(false);
      this.loadingCollections.set(false);
    });
  }

  selectCapability(cap: Capability): void {
    this.draft.capability_id = cap.id;
    this.capabilityId.set(cap.id);
    if (!this.draft.name) this.draft.name = cap.name;
    if (!this.draft.objective && cap.description) this.draft.objective = cap.description;
    if (cap.confidence_threshold != null) this.draft.confidence_threshold = cap.confidence_threshold;
    if (cap.pricing?.unit_price != null) {
      this.draft.max_cost = Math.max(this.draft.max_cost, cap.pricing.unit_price * 2);
    }
  }

  isCollectionChecked(name: string): boolean {
    return this.draft.collections.includes(name);
  }

  private loadEnabledApps(): void {
    const slug = this.workspace.currentSlug();
    if (!slug) {
      const cached = readAppToggles(null);
      this.enabledAppIds.set(
        Object.entries(cached)
          .filter(([, on]) => on)
          .map(([id]) => id),
      );
      return;
    }
    this.api.get<WorkspaceAppsResponse>(`/workspaces/${encodeURIComponent(slug)}/apps`).subscribe({
      next: (res) => {
        const enabled = Array.isArray(res?.enabled) ? res.enabled : [];
        this.enabledAppIds.set(enabled);
        writeAppToggles(slug, enabled);
      },
      error: () => {
        const cached = readAppToggles(slug);
        this.enabledAppIds.set(
          Object.entries(cached)
            .filter(([, on]) => on)
            .map(([id]) => id),
        );
      },
    });
  }

  pickExistingContext(id: string): void {
    this.draft.reuse_context_id = this.draft.reuse_context_id === id ? null : id;
    if (this.draft.reuse_context_id) {
      const ctx = this.existingContexts().find((c) => c.id === id);
      if (ctx?.data_refs?.length) {
        // Mirror the reused context's refs into the collection picker so the
        // review pane shows a meaningful count even when reusing.
        this.draft.collections = [...ctx.data_refs];
      }
    }
  }

  clearContextReuse(): void {
    this.draft.reuse_context_id = null;
  }

  toggleCollection(name: string): void {
    const idx = this.draft.collections.indexOf(name);
    if (idx >= 0) this.draft.collections.splice(idx, 1);
    else this.draft.collections.push(name);
  }

  presetStatus(presetId: string): 'bound' | 'stub' | 'unbound' | 'catalog_only' {
    return this.health.presetStatus(presetId);
  }

  presetHealthTitle(presetId: string): string {
    const st = this.presetStatus(presetId);
    if (st === 'bound') return this.i18n.t('systems.builder.preset.bound');
    if (st === 'stub') return this.i18n.t('systems.builder.preset.stub');
    if (st === 'unbound') return this.i18n.t('systems.builder.preset.unbound');
    return this.i18n.t('systems.builder.preset.catalog_only');
  }

  /**
   * Gate evaluation — each section is independent. Skills and Launch
   * inherit their gates from upstream sections (Capability and Objective)
   * so the bottom of the canvas only turns green once the pre-requisites
   * are satisfied.
   */
  isSectionValid(key: CanvasSectionKey): boolean {
    switch (key) {
      case 'objective':
        return this.draft.name.trim().length > 0;
      case 'capability':
        return !!this.draft.capability_id;
      case 'skills':
      case 'context':
      case 'policy':
        return true;
      case 'launch':
        return this.draft.name.trim().length > 0 && !!this.draft.capability_id;
      default:
        return true;
    }
  }

  allGatesValid(): boolean {
    return this.sections.every((s) => this.isSectionValid(s.key));
  }

  gatesValidCount(): number {
    return this.sections.filter((s) => this.isSectionValid(s.key)).length;
  }

  firstInvalidGateMessage(): string {
    const first = this.sections.find((s) => !this.isSectionValid(s.key));
    if (!first) return '';
    switch (first.key) {
      case 'objective':
        return this.i18n.t('systems.builder.gate.objective');
      case 'capability':
        return this.i18n.t('systems.builder.gate.capability');
      case 'launch':
        return this.i18n.t('systems.builder.gate.launch');
      default:
        return this.i18n.t('systems.builder.gate.complete', { section: this.sectionTitle(first.key) });
    }
  }

  sectionSummary(key: CanvasSectionKey): string {
    switch (key) {
      case 'objective':
        return this.draft.name.trim() || this.i18n.t('systems.builder.summary.objective');
      case 'capability':
        return this.selectedCapability()?.name || this.i18n.t('systems.builder.summary.capability');
      case 'skills': {
        const n = this.bundledSkills().length;
        const stubs = this.stubSkillsCount();
        const unbound = this.unboundSkillsCount();
        if (!this.draft.capability_id) return this.i18n.t('systems.builder.summary.skills_pending');
        if (!n) return this.i18n.t('systems.builder.summary.skills_none');
        return this.i18n.t('systems.builder.summary.skills', {
          count: String(n),
          stubs: String(stubs),
          missing: String(unbound),
        });
      }
      case 'context':
        return `${this.collectionsLabel(this.draft.collections.length)} · ${this.ragLabel(this.draft.rag_mode)}`;
      case 'policy':
        return `${this.executionModeLabel()} · $${this.draft.max_cost.toFixed(2)} · τ${this.draft.confidence_threshold.toFixed(2)}`;
      case 'launch':
        return this.allGatesValid()
          ? this.i18n.t('systems.builder.summary.launch_ready')
          : this.i18n.t('systems.builder.summary.launch_locked');
      default:
        return '';
    }
  }

  isSectionOpen(key: CanvasSectionKey): boolean {
    return this.openSections().has(key);
  }

  /**
   * A section is "locked" when the canonical flow carries custom nodes
   * the Form can't round-trip without data loss. We only freeze the
   * downstream sections (Skills + Policy) that are most sensitive to
   * custom insertions; the upstream semantic fields (name, capability,
   * context collections) are still editable so the operator can rename
   * a system without losing their Flow work.
   */
  isSectionLocked(key: CanvasSectionKey): boolean {
    return this.lockedSections().has(key);
  }

  /**
   * The Switch-to-Flow button is live as soon as the two minimum gates
   * are satisfied (name + capability). We persist an in-flight draft
   * via createSystem/updateSystem so the Flow editor has a real row to
   * PATCH, guaranteeing a faithful round-trip.
   */
  canSwitchToFlow(): boolean {
    return this.draft.name.trim().length > 0 && !!this.draft.capability_id;
  }

  /**
   * Emit the current draft as a CanonicalFlow, persist it onto the
   * System (creating the row on first use) and navigate to
   * `/systems/:id/flow`. If an existing `flow_definition` is
   * already present we preserve its `variant` so specialised Systems
   * (e.g. intelligence) remain intact.
   */
  switchToFlow(): void {
    if (!this.canSwitchToFlow() || this.launching()) return;
    this.launching.set(true);
    const flow: CanonicalFlow = this.serializer.formToFlow(this.draftAsSerializerInput());
    const existing = (this.editingSystem()?.flow_definition ?? {}) as unknown as CanonicalFlow;
    const merged: CanonicalFlow = {
      ...flow,
      variant: existing.variant,
    };
    const body: Partial<System> = this.systemBodyFromDraft({
      flow_definition: merged as unknown as Record<string, unknown>,
    });
    const sid = this.editingSystemId();
    const op$ = sid
      ? this.canonical.updateSystem(sid, body, {
          expected_flow_sha256: this.editingSystem()?.flow_sha256,
        })
      : this.canonical.createSystem(body);
    op$.subscribe((sys) => {
      this.launching.set(false);
      if (!sys) {
        this.toast.error(
          this.i18n.t('systems.builder.toast.switch_failed'),
          this.i18n.t('systems.builder.toast.switch_failed_title'),
        );
        return;
      }
      this.toast.info(
        this.i18n.t('systems.builder.toast.switched', { name: sys.name }),
        this.i18n.t('systems.builder.toast.switched_title'),
      );
      void this.router.navigateByUrl(this.navigation.leafUrl('system-flow', { ref: sys.id }));
    });
  }

  /**
   * Shape the mutable `draft` into the `SystemBuilderDraft` interface
   * the serializer expects. This intermediate hop is cheap and lets
   * the serializer stay dependency-free.
   */
  private draftAsSerializerInput(): SystemBuilderDraft {
    return {
      name: this.draft.name,
      objective: this.draft.objective,
      capability_id: this.draft.capability_id ?? null,
      collections: [...this.draft.collections],
      rag_mode: this.draft.rag_mode,
      reuse_context_id: this.draft.reuse_context_id ?? null,
      default_prompt_type: this.draft.default_prompt_type,
      default_model: this.draft.default_model,
      execution_mode: this.draft.execution_mode,
      temperature: this.draft.temperature,
      max_cost: this.draft.max_cost,
      max_latency_ms: this.draft.max_latency_ms,
      confidence_threshold: this.draft.confidence_threshold,
      require_citations: this.draft.require_citations,
      enable_audit: this.draft.enable_audit,
    };
  }

  /**
   * Build the System PATCH/POST body from the current draft. Shared
   * between `launch()` and `switchToFlow()` so both call sites agree
   * on the canonical payload shape.
   */
  private systemBodyFromDraft(overrides: Partial<System> = {}): Partial<System> {
    const cap = this.selectedCapability();
    const pipeline = this.ragPipelines.find((p) => p.id === this.draft.rag_mode);
    const canonicalRagMode = pipeline?.canonical ?? 'auto';
    const promptType =
      this.draft.default_prompt_type && this.draft.default_prompt_type !== 'auto'
        ? this.draft.default_prompt_type
        : null;
    const defaultModel = this.draft.default_model?.trim() || null;
    const body: Partial<System> & {
      flow_definition?: Record<string, unknown>;
      default_prompt_type?: string | null;
      default_model?: string | null;
      retrieval_mode_default?: string | null;
      execution_mode?: System['execution_mode'];
    } = {
      name: this.draft.name.trim(),
      objective: this.draft.objective.trim(),
      capability_id: this.draft.capability_id ?? null,
      skill_ids: cap?.skill_ids ?? [],
      default_prompt_type: promptType,
      default_model: defaultModel,
      retrieval_mode_default: canonicalRagMode,
      execution_mode: this.draft.execution_mode,
      status: 'active',
      ...overrides,
    };
    return body;
  }

  /**
   * Hydrate the builder state from an existing System (edit mode).
   * Locks Skills + Policy sections when the flow is marked
   * `extended` so the user can't silently overwrite Flow-authored work.
   */
  private hydrateFromSystem(sys: System): void {
    this.editingSystem.set(sys);
    this.editingSystemId.set(sys.id);
    const flow = (sys.flow_definition ?? {}) as unknown as CanonicalFlow;
    const { draft: hydrated, extended } = this.serializer.flowToForm(
      flow,
      this.draftAsSerializerInput(),
    );
    this.draft.name = hydrated.name;
    this.draft.objective = hydrated.objective;
    this.draft.capability_id = hydrated.capability_id ?? null;
    this.capabilityId.set(this.draft.capability_id);
    this.draft.collections = [...hydrated.collections];
    this.draft.rag_mode = hydrated.rag_mode;
    this.draft.reuse_context_id = hydrated.reuse_context_id ?? null;
    this.draft.default_prompt_type = hydrated.default_prompt_type;
    this.draft.default_model = hydrated.default_model;
    this.draft.execution_mode =
      (hydrated.execution_mode as typeof this.draft.execution_mode) ||
      this.draft.execution_mode;
    this.draft.temperature = hydrated.temperature;
    this.draft.max_cost = hydrated.max_cost;
    this.draft.max_latency_ms = hydrated.max_latency_ms;
    this.draft.confidence_threshold = hydrated.confidence_threshold;
    this.draft.require_citations = hydrated.require_citations;
    this.draft.enable_audit = hydrated.enable_audit;

    this.flowSource.set(flow.source ?? 'form');
    this.flowExtended.set(!!extended);
    if (extended && flow.source === 'flow') {
      this.lockedSections.set(new Set<CanvasSectionKey>(['skills', 'policy']));
    } else {
      this.lockedSections.set(new Set());
    }

  }

  toggleSection(key: CanvasSectionKey): void {
    this.openSections.update((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  expandSection(key: CanvasSectionKey): void {
    this.openSections.update((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    // Scroll the section into view so the user can act immediately.
    setTimeout(() => {
      const el = document.querySelector(`[data-section-key="${key}"]`);
      if (el) (el as HTMLElement).scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 30);
  }

  /** Object-level KPIs rendered in `<ck-object-header>`. */
  headerKpis(): CkObjectKpi[] {
    const cap = this.selectedCapability();
    const gatesLabel = `${this.gatesValidCount()}/${this.sections.length}`;
    return [
      {
        label: this.i18n.t('systems.builder.gates.title'),
        value: gatesLabel,
        tone: this.allGatesValid() ? 'pos' : 'warn',
        hint: this.allGatesValid()
          ? this.i18n.t('systems.builder.kpi.gates_ok')
          : this.firstInvalidGateMessage(),
      },
      {
        label: this.sectionTitle('capability'),
        value: cap?.tier ? this.tierLabel(cap.tier) : '—',
        tone: cap ? 'cool' : 'neutral',
        hint: cap?.name ?? this.i18n.t('systems.builder.gate.capability'),
      },
      {
        label: this.sectionTitle('skills'),
        value: String(this.bundledSkills().length || 0),
        tone: this.unboundSkillsCount() ? 'warn' : 'neutral',
        hint: this.i18n.t('systems.builder.kpi.skills_hint'),
      },
      {
        label: this.i18n.t('systems.builder.kpi.cost'),
        value: this.formatPrice(cap?.pricing?.unit_price),
        tone: 'neutral',
        hint: this.i18n.t('systems.builder.kpi.cost_hint'),
      },
    ];
  }

  launch(): void {
    if (!this.allGatesValid() || this.launching()) return;
    this.launching.set(true);
    const cap = this.selectedCapability();
    const pipeline = this.ragPipelines.find((p) => p.id === this.draft.rag_mode);
    const canonicalRagMode = pipeline?.canonical ?? 'auto';
    const promptType = this.draft.default_prompt_type && this.draft.default_prompt_type !== 'auto'
      ? this.draft.default_prompt_type
      : null;
    const defaultModel = this.draft.default_model?.trim() || null;

    // If the user picked an existing context we pass its id straight through;
    // otherwise we spin a fresh one from the selected collections so every
    // Run has an attached, versioned Context (mental-model contract).
    const reuseId = this.draft.reuse_context_id || null;
    const contextOp: Observable<Context | null> = reuseId
      ? of({ id: reuseId } as Context)
      : this.draft.collections.length > 0
      ? this.canonical.createContext({
          name: this.i18n.t('systems.builder.context_name', {
            name: this.draft.name.trim() || this.i18n.t('systems.builder.context_name_fallback'),
          }),
          data_refs: [...this.draft.collections],
        })
      : of(null);

    contextOp.subscribe((ctx) => {
      // Canonical flow projection. When a System is being edited we
      // preserve the existing `variant` + any `extended` markers so the
      // specialised facets (e.g. intelligence) survive a save.
      const canonicalFlow: CanonicalFlow = this.serializer.formToFlow(
        this.draftAsSerializerInput(),
      );
      const existing = (this.editingSystem()?.flow_definition ?? {}) as unknown as CanonicalFlow;
      const mergedFlow: CanonicalFlow = {
        ...canonicalFlow,
        variant: existing.variant,
        extended: existing.extended === true ? true : canonicalFlow.extended,
      };
      const body: Partial<System> & {
        flow_definition?: Record<string, unknown>;
        default_prompt_type?: string | null;
        default_model?: string | null;
        retrieval_mode_default?: string | null;
        context_id?: string | null;
        execution_mode?: System['execution_mode'];
      } = {
        name: this.draft.name.trim(),
        objective: this.draft.objective.trim(),
        capability_id: this.draft.capability_id ?? null,
        skill_ids: cap?.skill_ids ?? [],
        context_id: ctx?.id ?? null,
        default_prompt_type: promptType,
        default_model: defaultModel,
        retrieval_mode_default: canonicalRagMode,
        execution_mode: this.draft.execution_mode,
        flow_definition: mergedFlow as unknown as Record<string, unknown>,
        status: 'active',
      };

      const sid = this.editingSystemId();
      const op$ = sid
        ? this.canonical.updateSystem(sid, body, {
            expected_flow_sha256: this.editingSystem()?.flow_sha256,
          })
        : this.canonical.createSystem(body);
      op$.subscribe((sys) => {
        this.launching.set(false);
        if (sys) {
          this.toast.success(
            this.i18n.t('systems.builder.toast.live', { name: sys.name }),
            this.i18n.t(sid ? 'systems.builder.toast.saved_title' : 'systems.builder.toast.created_title'),
          );
          void this.router.navigateByUrl(this.navigation.objectUrl('system', sys.id));
          return;
        }
        if (sid) {
          this.toast.error(
            this.i18n.t('systems.builder.toast.save_failed'),
            this.i18n.t('systems.builder.toast.save_failed_title'),
          );
          return;
        }
        const draft = this.store.createDraft({
          name: this.draft.name.trim(),
          description: this.draft.objective.trim(),
          model: 'gpt-4o-mini',
          rag_mode: this.draft.rag_mode,
          skills: cap?.skill_ids ?? [],
          collections: [...this.draft.collections],
        });
        this.toast.warning(
          this.i18n.t('systems.builder.toast.local_draft'),
          this.i18n.t('systems.builder.toast.local_draft_title'),
        );
        void this.router.navigateByUrl(this.navigation.objectUrl('system', draft.id));
      });
    });
  }

  formatPrice(v: number | null | undefined): string {
    if (v == null) return '—';
    if (v < 0.01) return `$${v.toFixed(4)}`;
    if (v < 1) return `$${v.toFixed(3)}`;
    return `$${v.toFixed(2)}`;
  }

  tierTone(tier: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' {
    return TIER_TONE[tier || 'universal'] ?? 'pos';
  }

  certTone(cert: string | undefined): 'pos' | 'cool' | 'violet' | 'warn' {
    if (cert === 'enterprise') return 'violet';
    if (cert === 'production') return 'pos';
    return 'cool';
  }
}
