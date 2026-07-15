import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
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
import { RuntimeHealthService } from '@app/core/runtime-health.service';
import { SettingsService } from '@app/core/settings.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import {
  type CkGlyphName,
  GlyphComponent,
  HelpTooltipComponent,
  LiveDotComponent,
  RuntimeStatusBadgeComponent,
  StatReadoutComponent,
  TagComponent,
} from '@app/shared/cockpit';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { SystemsStore } from './systems.store';

type CanvasSectionKey =
  | 'objective'
  | 'capability'
  | 'skills'
  | 'context'
  | 'policy'
  | 'launch';

interface CanvasSection {
  key: CanvasSectionKey;
  title: string;
  description: string;
  glyph: CkGlyphName;
}

const EXECUTION_MODES: {
  id:
    | 'real_time_decision'
    | 'batch_processing'
    | 'event_driven_automation'
    | 'continuous_monitoring'
    | 'human_augmented';
  label: string;
  short: string;
  description: string;
}[] = [
  { id: 'real_time_decision', label: 'Real-time', short: 'Synchronous per query', description: 'Synchronous — one outcome per user-initiated query (chat, API).' },
  { id: 'batch_processing', label: 'Batch', short: 'Scheduled batches', description: 'Runs over a batch of inputs on a schedule; outcomes aggregated.' },
  { id: 'event_driven_automation', label: 'Event-driven', short: 'Triggers from connectors', description: 'Triggered by external events (webhooks, connectors).' },
  { id: 'continuous_monitoring', label: 'Continuous', short: 'Always-on watcher', description: 'Always-on monitoring, emits decisions on anomalies.' },
  { id: 'human_augmented', label: 'Human-augmented', short: 'Pairs with operator', description: 'Requires human-in-the-loop for every material decision.' },
];

const RAG_PIPELINES: { id: string; canonical: string; label: string; description: string }[] = [
  { id: 'OmniRAG', canonical: 'chah', label: 'OmniRAG (C-HAH)', description: 'Composite, budget-aware variants + RRF' },
  { id: 'HAH', canonical: 'hah', label: 'HAH', description: 'Hierarchical answer harvesting' },
  { id: 'Hybrid', canonical: 'hybrid', label: 'Hybrid', description: 'Sparse + dense, single-pass' },
  { id: 'Semantic', canonical: 'naive', label: 'Semantic', description: 'Dense vectors only, single-pass' },
  { id: 'None', canonical: 'auto', label: 'Direct LLM', description: 'No retrieval — LLM only' },
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
    RouterLink,
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
      eyebrow="Build · System"
      [title]="draft.name || 'New system'"
      [subtitle]="draft.objective || 'Compose a system on a single canvas — every gate must turn green before launch.'"
      [kpis]="headerKpis()"
    >
      <span actions>
        <a
          routerLink="/systems"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition mr-2"
        >
          <app-icon name="arrow-left" [size]="14" /> Cancel
        </a>
        <button
          type="button"
          (click)="switchToFlow()"
          [disabled]="!canSwitchToFlow() || launching()"
          class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition mr-2"
          [title]="canSwitchToFlow() ? 'Open this draft as a flow graph' : 'Pick a name and a capability first'"
        >
          <app-icon name="workflow" [size]="14" /> Switch to Flow
        </button>
        <button
          type="button"
          (click)="launch()"
          [disabled]="!allGatesValid() || launching()"
          class="ck-mono inline-flex items-center gap-2 px-3 py-2 rounded text-xs font-semibold transition"
          style="letter-spacing:0.14em; text-transform:uppercase; background:var(--ck-signal-pos); color:var(--ck-on-signal);"
          [style.opacity]="!allGatesValid() || launching() ? '0.4' : '1'"
          [title]="allGatesValid() ? (editingSystemId() ? 'Save this system' : 'Create this system') : firstInvalidGateMessage()"
        >
          <ck-glyph name="bolt" [size]="12" />
          {{ launching() ? (editingSystemId() ? 'SAVING…' : 'CREATING…') : (editingSystemId() ? 'SAVE SYSTEM' : 'CREATE SYSTEM') }}
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
            [style.borderColor]="isSectionValid(section.key) ? 'var(--ck-stroke-soft)' : 'var(--ck-signal-warn)'"
            [style.borderWidth]="isSectionValid(section.key) ? '1px' : '1px'"
          >
            <button
              type="button"
              (click)="toggleSection(section.key)"
              class="w-full flex items-center gap-3 text-left transition"
              style="padding:14px 18px; background: var(--ck-bg-inset);"
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
                  <span class="text-sm font-medium text-white">{{ section.title }}</span>
                  <span
                    class="ck-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
                    [style.color]="isSectionValid(section.key) ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
                    [style.background]="isSectionValid(section.key) ? 'rgba(16,185,129,0.08)' : 'rgba(234,179,8,0.08)'"
                    [style.border]="'1px solid ' + (isSectionValid(section.key) ? 'rgba(16,185,129,0.2)' : 'rgba(234,179,8,0.25)')"
                  >
                    {{ isSectionValid(section.key) ? 'READY' : 'PENDING' }}
                  </span>
                </div>
                <div class="ck-mono text-[11px]" style="color:var(--ck-fg-4); margin-top:2px;">
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
                style="padding:20px 22px; border-top: 1px solid var(--ck-hair);"
                [style.opacity]="isSectionLocked(section.key) ? '0.55' : '1'"
                [style.pointerEvents]="isSectionLocked(section.key) ? 'none' : 'auto'"
              >
              @if (isSectionLocked(section.key)) {
                <div
                  class="flex items-center gap-2"
                  style="padding:8px 12px; margin-bottom:14px; border-radius:6px; background: rgba(234,179,8,0.08); border: 1px solid rgba(234,179,8,0.22); pointer-events:auto;"
                >
                  <ck-glyph name="bolt" [size]="12" />
                  <div class="flex-1 text-xs ck-mono" style="color:var(--ck-signal-warn);">
                    Edited in Flow — re-open this section from the flow builder to adjust it.
                  </div>
                  <a
                    [routerLink]="['/orchestration']"
                    [queryParams]="{ systemId: editingSystemId() }"
                    class="ck-mono text-[10px] uppercase tracking-wider px-2 py-1 rounded"
                    style="color: var(--ck-signal-warn); border:1px solid rgba(234,179,8,0.3); pointer-events:auto;"
                  >
                    Open in Flow
                  </a>
                </div>
              }
        @if (section.key === 'objective') {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="focus" [size]="16" />
                Objective
                <ck-help id="builder.steps.overview" />
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Define what this system should achieve — a single, measurable objective the Hypervisor can track.
              </p>
            </header>
            <div>
              <label class="ck-mono" style="display:block; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                Name <span style="color:var(--ck-signal-neg);">*</span>
              </label>
              <input
                type="text"
                [(ngModel)]="draft.name"
                name="name"
                required
                class="ck-surface ck-mono w-full"
                style="padding: 10px 12px; border-radius:4px; font-size:14px; background:var(--ck-bg-inset);"
                placeholder="Contract Analyzer"
              />
            </div>
            <div>
              <label class="ck-mono" style="display:block; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">
                Objective
              </label>
              <textarea
                [(ngModel)]="draft.objective"
                name="objective"
                rows="3"
                class="ck-surface w-full"
                style="padding: 10px 12px; border-radius:4px; font-size:13px; background:var(--ck-bg-inset); resize: none;"
                placeholder="Flag risky clauses in NDAs with legal rationale and severity."
              ></textarea>
              <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
                One sentence. Outcome-oriented. Drives the Hypervisor's value metric for this system.
              </p>
            </div>
          </div>
        }

        @if (section.key === 'capability') {
          <div class="space-y-4">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="cube" [size]="16" />
                Capability
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Pick the value-producing unit. Skills are bundled automatically.
              </p>
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
                title="No capability"
                description="Seed the catalog by restarting the backend or create one from the Catalog."
              />
            } @else {
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                @for (cap of capabilities(); track cap.id) {
                  <button
                    type="button"
                    (click)="selectCapability(cap)"
                    class="text-left transition ck-surface rounded-md"
                    [style.padding]="'14px 16px'"
                    [style.borderColor]="draft.capability_id === cap.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    [style.boxShadow]="draft.capability_id === cap.id ? 'var(--ck-glow-cool)' : 'none'"
                  >
                    <div class="flex items-start justify-between gap-3 mb-2">
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <ck-tag [tone]="tierTone(cap.tier)" variant="soft">{{ cap.tier || 'UNIV' }}</ck-tag>
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
                    <p class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.5; margin-bottom:10px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
                      {{ cap.description || '—' }}
                    </p>
                    <div class="flex items-center justify-between">
                      <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                        {{ cap.skill_ids?.length || 0 }} SKILLS · {{ cap.input_unit || '—' }} → {{ cap.output_unit || '—' }}
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
                Skills
                <ck-help id="builder.steps.skills" />
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Capability bundles a validated skill set. Runtime badges surface stubs or unbound wrappers before launch.
              </p>
            </header>

            @if (!draft.capability_id) {
              <app-empty-state
                icon="cube"
                title="Pick a capability first"
                description="Skills are derived from the capability you select in the previous step."
              />
            } @else if (bundledSkills().length === 0) {
              <app-empty-state
                icon="cube"
                title="No bundled skill"
                description="This capability has no attached skills yet. Launch will still succeed but will route through defaults."
              />
            } @else {
              <div>
                <div class="ck-mono flex items-center gap-2 mb-3" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">
                  <ck-glyph name="ledger" [size]="12" />
                  BUNDLED SKILLS · {{ bundledSkills().length }}
                </div>
                <ul style="display:flex; flex-direction:column; gap:4px;">
                  @for (sk of bundledSkills(); track sk.id) {
                    <li style="display:grid; grid-template-columns: 70px 90px 1fr 80px 70px; gap:10px; align-items:center; padding:8px 12px; border-radius:4px; background:var(--ck-bg-inset);">
                      <ck-tag [tone]="certTone(sk.certification_level)" variant="outline">
                        {{ (sk.certification_level || 'basic').slice(0, 4).toUpperCase() }}
                      </ck-tag>
                      <ck-runtime-status [status]="sk.runtime_status" />
                      <div style="min-width:0;">
                        <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
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
                  <div class="ck-mono mt-3" style="font-size:10px; color:var(--ck-signal-warn); letter-spacing:0.06em;">
                    WARNING · {{ stubSkillsCount() }} stub · {{ unboundSkillsCount() }} unbound — runs may return degraded payloads.
                  </div>
                }
              </div>
            }
          </div>
        }

        @if (section.key === 'context') {
          <div class="space-y-5">
            <header class="mb-2">
              <h2 class="text-lg font-semibold text-white flex items-center gap-2">
                <ck-glyph name="ledger" [size]="16" />
                Context
                <ck-help id="builder.steps.context" />
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Knowledge collections and the retrieval pipeline. Becomes the versioned Context attached to every Run —
                or pick an existing one to reuse.
              </p>
            </header>

            <!-- Reuse existing context -->
            @if (existingContexts().length > 0) {
              <div style="border-bottom: 1px solid var(--ck-hair); padding-bottom:16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  Reuse an existing context
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                  @for (ctx of existingContexts(); track ctx.id) {
                    <button
                      type="button"
                      (click)="pickExistingContext(ctx.id)"
                      class="text-left ck-surface rounded"
                      style="padding:10px 12px;"
                      [style.borderColor]="draft.reuse_context_id === ctx.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    >
                      <div class="text-sm font-medium text-white truncate">{{ ctx.name }}</div>
                      <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                        v{{ ctx.version ?? 1 }} · {{ (ctx.data_refs?.length ?? 0) }} refs
                      </div>
                    </button>
                  }
                </div>
                @if (draft.reuse_context_id) {
                  <button
                    type="button"
                    class="mt-2 text-[11px] ck-mono"
                    style="color: var(--ck-signal-warn);"
                    (click)="clearContextReuse()"
                  >
                    Clear selection — create a new context instead
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
                title="No collection yet"
                description="Upload documents in Knowledge to create one."
              >
                <a
                  routerLink="/knowledge"
                  class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium text-white transition"
                  style="background: var(--ck-signal-cool); color: var(--ck-on-signal);"
                >
                  Open Knowledge
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
              <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                Retrieval pipeline
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
                @for (mode of ragPipelines; track mode.id) {
                  <button
                    type="button"
                    (click)="draft.rag_mode = mode.id"
                    class="text-left transition ck-surface rounded"
                    style="padding:10px 12px;"
                    [title]="presetHealthTitle(mode.id)"
                    [style.opacity]="presetStatus(mode.id) === 'bound' ? 1 : 0.82"
                    [style.borderColor]="draft.rag_mode === mode.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                  >
                    <div class="flex items-center gap-2 mb-1" style="justify-content:space-between;">
                      <div class="text-sm font-medium" [style.color]="draft.rag_mode === mode.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-2)'">
                        {{ mode.label }}
                      </div>
                      <ck-runtime-status [status]="presetStatus(mode.id)" />
                    </div>
                    <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                      {{ mode.description }}
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
                Policy
                <ck-help id="builder.steps.policy" />
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Control guardrails and adaptive levers. Control = hard limits, Adaptive = soft directives.
              </p>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>CONTROL · max cost / outcome</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-cool);">\${{ draft.max_cost.toFixed(2) }}</span>
                </label>
                <input type="range" min="0.01" max="5" step="0.01" [(ngModel)]="draft.max_cost" class="w-full accent-cyan-400" />
              </div>
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>CONTROL · max latency (ms)</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-cool);">{{ draft.max_latency_ms }}</span>
                </label>
                <input type="range" min="500" max="60000" step="500" [(ngModel)]="draft.max_latency_ms" class="w-full accent-cyan-400" />
              </div>
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>ADAPTIVE · confidence threshold</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-violet);">{{ draft.confidence_threshold.toFixed(2) }}</span>
                </label>
                <input type="range" min="0" max="1" step="0.01" [(ngModel)]="draft.confidence_threshold" class="w-full accent-sky-400" />
                <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px;">
                  Below this score → HITL escalation (auto).
                </p>
              </div>
              <div>
                <label class="ck-mono" style="display:flex; align-items:center; justify-content:space-between; font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  <span>ADAPTIVE · temperature</span>
                  <span class="ck-tnum" style="color:var(--ck-signal-violet);">{{ draft.temperature.toFixed(2) }}</span>
                </label>
                <input type="range" min="0" max="2" step="0.05" [(ngModel)]="draft.temperature" class="w-full accent-sky-400" />
              </div>
            </div>

            <div style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                Execution mode
              </div>
              <div class="grid grid-cols-2 md:grid-cols-5 gap-2">
                @for (mode of executionModes; track mode.id) {
                  <button
                    type="button"
                    (click)="draft.execution_mode = mode.id"
                    class="text-left transition ck-surface rounded"
                    style="padding:10px 12px;"
                    [title]="mode.description"
                    [style.borderColor]="draft.execution_mode === mode.id ? 'var(--ck-stroke-strong)' : 'var(--ck-stroke-soft)'"
                    [style.boxShadow]="draft.execution_mode === mode.id ? 'var(--ck-glow-cool)' : 'none'"
                  >
                    <div class="text-sm font-medium" [style.color]="draft.execution_mode === mode.id ? 'var(--ck-fg-1)' : 'var(--ck-fg-2)'">
                      {{ mode.label }}
                    </div>
                    <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:2px;">
                      {{ mode.short }}
                    </div>
                  </button>
                }
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5" style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  Reasoning template (default)
                </div>
                <select
                  [(ngModel)]="draft.default_prompt_type"
                  class="w-full ck-surface rounded"
                  style="padding:10px 12px; background:var(--ck-bg-inset); color:var(--ck-fg-1); font-size:13px;"
                >
                  <option value="auto">Auto — heuristic selector per run</option>
                  @for (t of reasoningTemplates(); track t.slug) {
                    <option [value]="t.slug">{{ t.label }} — {{ t.description }}</option>
                  }
                </select>
                <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                  Drives the system prompt on every run; chat can still override per-message.
                </p>
              </div>
              <div>
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:8px;">
                  {{ isDemoMode() ? 'Runtime policy' : 'Model override (optional)' }}
                </div>
                @if (isDemoMode()) {
                  <div class="w-full ck-surface rounded" style="padding:10px 12px; background:var(--ck-bg-inset); color:var(--ck-fg-2); font-size:13px;">
                    Managed by workspace
                  </div>
                  <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                    Provider and model details are hidden by demo-safe presentation.
                  </p>
                } @else {
                  <select
                    [(ngModel)]="draft.default_model"
                    class="w-full ck-surface rounded"
                    style="padding:10px 12px; background:var(--ck-bg-inset); color:var(--ck-fg-1); font-size:13px;"
                  >
                    <option value="">Workspace default</option>
                    @for (m of availableModels(); track m.id) {
                      <option [value]="m.id">{{ m.label }}</option>
                    }
                  </select>
                  <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:6px;">
                    Pins a specific provider/model for every Run of this System.
                  </p>
                }
              </div>
            </div>

            <div class="space-y-2" style="border-top: 1px solid var(--ck-hair); padding-top:16px;">
              <label class="flex items-start gap-3 ck-surface cursor-pointer" style="padding:12px 14px; border-radius:4px;">
                <input type="checkbox" [(ngModel)]="draft.require_citations" class="accent-cyan-400 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Require citations</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                    Answers without a citation are blocked before returning.
                  </div>
                </div>
              </label>
              <label class="flex items-start gap-3 ck-surface cursor-pointer" style="padding:12px 14px; border-radius:4px;">
                <input type="checkbox" [(ngModel)]="draft.enable_audit" class="accent-cyan-400 mt-0.5" />
                <div class="flex-1">
                  <div class="text-sm text-white font-medium">Audit every run</div>
                  <div class="ck-mono" style="font-size:10px; color:var(--ck-fg-4);">
                    Emit a typed audit event per run (required for enterprise tier).
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
                Launch
              </h2>
              <p class="text-xs ck-mono" style="color:var(--ck-fg-3); margin-top:4px; letter-spacing:0.02em;">
                Final review before creating the System.
              </p>
            </header>

            <!-- ROI projection -->
            <div class="ck-surface rounded" style="padding:16px 18px; background: var(--ck-bg-inset);">
              <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:12px;">
                PROJECTED OUTCOME (PER RUN)
              </div>
              <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:18px;">
                <ck-stat-readout label="COST" [value]="formatPrice(selectedCapability()?.pricing?.unit_price)" tone="cool" [size]="16" />
                <ck-stat-readout label="VALUE" [value]="formatPrice(selectedCapability()?.value_per_outcome)" tone="pos" [size]="16" />
                <ck-stat-readout label="MARGIN" [value]="projectedMargin()" tone="pos" [size]="16" />
                <ck-stat-readout label="ROI" [value]="projectedRoi()" tone="violet" [size]="16" />
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">OBJECTIVE</div>
                <div class="text-sm font-medium text-white">{{ draft.name || 'Untitled' }}</div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:4px; line-height:1.5; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">
                  {{ draft.objective || 'No objective set.' }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">CAPABILITY</div>
                <div class="text-sm font-medium text-white">{{ selectedCapability()?.name || '—' }}</div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:4px;">
                  {{ selectedCapability()?.tier || '—' }} · {{ bundledSkills().length }} skills bundled
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">CONTEXT</div>
                <div class="text-sm text-white">
                  {{ draft.collections.length }} collection{{ draft.collections.length === 1 ? '' : 's' }}
                </div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); margin-top:4px;">
                  Pipeline: {{ draft.rag_mode }}
                </div>
              </div>
              <div class="ck-surface rounded" style="padding:14px 16px;">
                <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4); margin-bottom:6px;">POLICY</div>
                <div class="ck-mono" style="font-size:11px; color:var(--ck-fg-3); line-height:1.7;">
                  EXECUTION <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ executionModeLabel() }}</span><br />
                  MAX COST <span class="ck-tnum" style="color:var(--ck-fg-2);">\${{ draft.max_cost.toFixed(2) }}</span> ·
                  MAX LATENCY <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ draft.max_latency_ms }} ms</span><br />
                  CONFIDENCE ≥ <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ draft.confidence_threshold.toFixed(2) }}</span> ·
                  TEMP <span class="ck-tnum" style="color:var(--ck-fg-2);">{{ isDemoMode() ? 'managed' : draft.temperature.toFixed(2) }}</span>
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

      <aside class="ck-surface rounded-md self-start sticky top-4" style="padding:20px;">
        <div class="flex items-center gap-3 mb-4 pb-3" style="border-bottom: 1px solid var(--ck-hair);">
          <div class="w-10 h-10 rounded-md flex items-center justify-center ck-surface" style="background:var(--ck-bg-inset); border-color: var(--ck-stroke-soft);">
            <ck-glyph name="focus" [size]="18" />
          </div>
          <div>
            <div class="ck-mono" style="font-size:9px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);">
              LIVE PREVIEW
            </div>
            <div class="text-sm font-medium text-white truncate">{{ draft.name || 'New system' }}</div>
          </div>
        </div>

        <ul class="space-y-3">
          <li class="flex items-center gap-2">
            <ck-glyph name="focus" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">OBJECTIVE</span>
            <span class="ml-auto ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">
              {{ draft.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="cube" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">CAPABILITY</span>
            <span class="ml-auto ck-mono" style="font-size:11px; color:var(--ck-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;">
              {{ selectedCapability()?.name || '—' }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="ledger" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">CONTEXT</span>
            <span class="ml-auto ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              {{ draft.collections.length }} · {{ draft.rag_mode }}
            </span>
          </li>
          <li class="flex items-center gap-2">
            <ck-glyph name="sliders" [size]="12" />
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">POLICY</span>
            <span class="ml-auto ck-mono ck-tnum" style="font-size:11px; color:var(--ck-fg-2);">
              \${{ draft.max_cost.toFixed(2) }} · τ{{ draft.confidence_threshold.toFixed(2) }}
            </span>
          </li>
        </ul>

        <div class="mt-4 pt-4" style="border-top: 1px solid var(--ck-hair);">
          <div class="flex items-center justify-between mb-2">
            <span class="ck-mono" style="font-size:10px; letter-spacing:0.14em; text-transform:uppercase; color:var(--ck-fg-4);">GATES</span>
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
                  [style.background]="isSectionValid(section.key) ? 'var(--ck-signal-pos)' : 'var(--ck-signal-warn)'"
                ></span>
                <span class="ck-mono" style="font-size:11px; color:var(--ck-fg-3);">
                  {{ section.title }}
                </span>
                @if (!isSectionValid(section.key)) {
                  <button
                    type="button"
                    (click)="expandSection(section.key)"
                    class="ml-auto ck-mono text-[10px]"
                    style="color:var(--ck-signal-warn); letter-spacing:0.08em; text-transform:uppercase;"
                  >
                    FIX
                  </button>
                }
              </li>
            }
          </ul>
        </div>

        @if (!allGatesValid()) {
          <div class="ck-mono mt-4" style="font-size:10px; color:var(--ck-signal-warn); letter-spacing:0.02em;">
            ⚠ {{ firstInvalidGateMessage() }}
          </div>
        }
      </aside>
    </div>
  `,
})
export class SystemBuilderComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);
  private readonly health = inject(RuntimeHealthService);
  private readonly toast = inject(ToastrService);
  private readonly store = inject(SystemsStore);
  private readonly serializer = inject(FlowSerializerService);
  private readonly workspace = inject(WorkspaceService);
  readonly settings = inject(SettingsService);
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

  readonly executionModeLabel = computed(() => {
    const id = this.draft.execution_mode;
    return EXECUTION_MODES.find((m) => m.id === id)?.label ?? id;
  });

  /**
   * Single-surface canvas — all sections are available at once (no linear
   * wizard). Each section is its own `CanvasSection` with a gate; the
   * launch action unlocks only when every gate turns green.
   */
  readonly sections: CanvasSection[] = [
    { key: 'objective', title: 'Objective', description: 'Name & outcome', glyph: 'focus' },
    { key: 'capability', title: 'Capability', description: 'Value-producing unit', glyph: 'cube' },
    { key: 'skills', title: 'Skills', description: 'Bundled + custom runtime', glyph: 'cube' },
    { key: 'context', title: 'Context', description: 'Knowledge + retrieval', glyph: 'ledger' },
    { key: 'policy', title: 'Policy', description: 'Guardrails + levers', glyph: 'sliders' },
    { key: 'launch', title: 'Launch', description: 'Review & create', glyph: 'bolt' },
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

  readonly selectedCapability = computed<Capability | null>(() => {
    const id = this.draft.capability_id;
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
    if (st === 'bound') return 'Preset available — all required skills are bound.';
    if (st === 'stub') return 'Preset available but at least one underlying skill is a stub.';
    if (st === 'unbound') return 'Warning — at least one underlying skill has no wrapper. Runs may fail.';
    return 'Warning — at least one underlying skill is only in the catalog, not registered at runtime.';
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
        return 'Give this system a name.';
      case 'capability':
        return 'Pick the capability this system will produce.';
      case 'launch':
        return 'Fill the name and pick a capability before launching.';
      default:
        return `Complete the ${first.title} section.`;
    }
  }

  sectionSummary(key: CanvasSectionKey): string {
    switch (key) {
      case 'objective':
        return this.draft.name.trim() || 'Name & one-sentence outcome.';
      case 'capability':
        return this.selectedCapability()?.name || 'Pick a value-producing unit.';
      case 'skills': {
        const n = this.bundledSkills().length;
        const stubs = this.stubSkillsCount();
        const unbound = this.unboundSkillsCount();
        if (!this.draft.capability_id) return 'Bundled automatically once a capability is picked.';
        if (!n) return 'No bundled skill — runs will fall back to defaults.';
        return `${n} bundled · ${stubs} stub · ${unbound} unbound`;
      }
      case 'context':
        return `${this.draft.collections.length} collection${this.draft.collections.length === 1 ? '' : 's'} · ${this.draft.rag_mode}`;
      case 'policy':
        return `${this.executionModeLabel()} · $${this.draft.max_cost.toFixed(2)} · τ${this.draft.confidence_threshold.toFixed(2)}`;
      case 'launch':
        return this.allGatesValid() ? 'Ready to create this system.' : 'Unlocks once all gates are green.';
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
      ? this.canonical.updateSystem(sid, body)
      : this.canonical.createSystem(body);
    op$.subscribe((sys) => {
      this.launching.set(false);
      if (!sys) {
        this.toast.error('Could not persist draft — backend unreachable.', 'Switch to Flow');
        return;
      }
      this.toast.info(`"${sys.name}" opened in Flow`, 'Draft saved');
      this.router.navigate(['/systems', sys.id, 'flow']);
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
        label: 'Gates',
        value: gatesLabel,
        tone: this.allGatesValid() ? 'pos' : 'warn',
        hint: this.allGatesValid()
          ? 'All sections validated — launch is unlocked.'
          : this.firstInvalidGateMessage(),
      },
      {
        label: 'Capability',
        value: cap?.tier ? cap.tier.toUpperCase() : '—',
        tone: cap ? 'cool' : 'neutral',
        hint: cap?.name ?? 'Pick the capability this system will produce.',
      },
      {
        label: 'Skills',
        value: String(this.bundledSkills().length || 0),
        tone: this.unboundSkillsCount() ? 'warn' : 'neutral',
        hint: 'Skills bundled by the selected capability.',
      },
      {
        label: 'Est. cost',
        value: this.formatPrice(cap?.pricing?.unit_price),
        tone: 'neutral',
        hint: 'Projected unit cost per run based on the capability pricing.',
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
          name: `${this.draft.name.trim() || 'System'} context`,
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
        ? this.canonical.updateSystem(sid, body)
        : this.canonical.createSystem(body);
      op$.subscribe((sys) => {
        this.launching.set(false);
        if (sys) {
          this.toast.success(`"${sys.name}" is live`, sid ? 'System saved' : 'System created');
          this.router.navigate(['/systems', sys.id]);
          return;
        }
        if (sid) {
          this.toast.error('Could not save changes — backend unreachable.', 'Save failed');
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
        this.toast.warning('Created as local draft (API unreachable)', 'System draft');
        this.router.navigate(['/systems', draft.id]);
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
