import { Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { Subscription, forkJoin, map } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { ApiService, KnowledgeGuide, KnowledgeGuideStatus } from '@app/core/api.service';
import {
  WorkspaceDetail,
  WorkspaceService,
  type WorkspaceRequestScope,
} from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';

type RagMode = 'auto' | 'naive' | 'hybrid' | 'hah' | 'chah';
type SessionPromptMode = 'any' | 'replace' | 'combine';

interface KnowledgeScopeApi {
  key: string;
  label?: string | null;
  description?: string | null;
  collection_slugs: string[];
  default_mode?: RagMode | null;
  top_k?: number | null;
  is_default?: boolean;
  table_profile_key?: string | null;
  document_profile_key?: string | null;
}

interface KnowledgeScopeDraft {
  key: string;
  label: string;
  description: string;
  collection_slugs_text: string;
  default_mode: RagMode;
  top_k: number | null;
  is_default: boolean;
  table_profile_key: string;
  document_profile_key: string;
}

interface KnowledgeGuideEditorDraft {
  scope_key: string;
  guide_key?: string;
  mode: 'create' | 'edit' | 'restore';
  title: string;
  markdown: string;
  status: KnowledgeGuideStatus;
  source_version?: number;
}

interface PromptCardDraft {
  icon: string;
  label: string;
  prompt: string;
  scope_key: string;
  context_mode: SessionPromptMode;
}

interface ChatSettingsDraft {
  title: string;
  subtitle: string;
  placeholder: string;
  prompt_pack: PromptCardDraft[];
}

type VoiceLoopDefaultMode = 'batch' | 'session_loop' | 'realtime';
type VoiceCaptureMode = 'normal' | 'robust' | 'manual_safe';
type VoiceOutputLatencyProfile = 'fast' | 'balanced' | 'quality';

interface VoiceLoopSettingsDraft {
  default_mode: VoiceLoopDefaultMode;
  capture_mode: VoiceCaptureMode;
  auto_capture_mode_enabled: boolean;
  auto_send_final_transcript: boolean;
  auto_endpoint: boolean;
  auto_rearm_after_tts: boolean;
  barge_in: boolean;
  commands_enabled: boolean;
  trigger_word: string;
  command_packs_text: string;
  stop_phrases_text: string;
  silence_ms: number;
  dictation_silence_ms: number;
  min_speech_ms: number;
  dictation_min_speech_ms: number;
  max_turn_ms: number;
  cooldown_ms: number;
  rms_threshold: number;
  endpoint_grace_ms: number;
  vad_hangover_ms: number;
  vad_calibration_ms: number;
  vad_min_silence_frames_ms: number;
}

interface VoiceOutputSettingsDraft {
  latency_profile: VoiceOutputLatencyProfile;
  voice: string;
  flush_first_chars: number;
  flush_next_chars: number;
  flush_timeout_ms: number;
  interrupt_on_user_speech: boolean;
}

interface WorkspaceActionSettingsDraft {
  enabled_packs_text: string;
  hidden_packs_text: string;
  enabled_actions_text: string;
  hidden_actions_text: string;
}

interface TableProfileDraft {
  key: string;
  label: string;
  description: string;
  synonyms_text: string;
  metric_aliases_text: string;
  allow_mean: boolean;
  require_compatible_units: boolean;
  exclude_non_numeric: boolean;
  ambiguity_policy: string;
  require_cell_citations: boolean;
  show_excluded_values: boolean;
}

interface TableIntelligenceSettingsDraft {
  default_profile: string;
  profiles: TableProfileDraft[];
}

interface DocumentProfileDraft {
  key: string;
  label: string;
  description: string;
  synonyms_text: string;
  max_candidate_facts: number;
  max_evidence_rows: number;
}

interface OcrSettingsDraft {
  enabled: boolean;
  provider_priority_text: string;
  languages_text: string;
  required: boolean;
  force_ocr: boolean;
  scan_detection: boolean;
  min_native_pdf_chars: number;
  min_confidence: number;
  timeout_seconds: number;
  retries: number;
  ppocr_endpoint_url: string;
  openai_vision_enabled: boolean;
  openai_model: string;
  openai_detail: 'low' | 'high' | 'auto';
  openai_max_image_bytes: number;
  openai_enrich_min_chars: number;
  openai_enrich_min_confidence: number;
}

interface DocumentIntelligenceSettingsDraft {
  default_profile: string;
  profiles: DocumentProfileDraft[];
  ocr: OcrSettingsDraft;
}

interface AssistantProfileDraft {
  key: string;
  label?: string;
  subtitle?: string;
  default_knowledge_scope?: string;
  executive_mode?: boolean;
  showcase_mode?: string;
  design_mode?: string;
  tone?: string;
  prompt_pack?: PromptCardDraft[];
  chat?: Record<string, unknown>;
  voice_loop?: Record<string, unknown>;
}

@Component({
  selector: 'app-chat-knowledge-settings',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent, SectionHeaderComponent],
  template: `
    <app-section-header
      breadcrumb="Workspace · Defaults"
      title="Chat & Sources"
      icon="database"
      subtitle="Configure the source scopes, chat defaults and assistant metadata used by Quick ask."
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 text-gray-200 ring-1 ring-white/10 transition"
        (click)="load()"
      >
        <app-icon name="refresh-cw" [size]="14" /> Refresh
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-semibold bg-cyan-500 hover:bg-cyan-400 text-white disabled:opacity-50 transition"
        [disabled]="saving() || !canEdit()"
        (click)="saveAll()"
      >
        <app-icon name="save" [size]="14" /> {{ saving() ? 'Saving...' : 'Save defaults' }}
      </button>
    </app-section-header>

    @if (error(); as message) {
      <div class="mb-4 rounded-md border border-red-400/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
        {{ message }}
      </div>
    }

    <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="space-y-5">
        <section class="ck-surface rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Source routing</p>
              <h3 class="text-base font-semibold text-white mt-1">Source scopes</h3>
              <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
                A scope gives Quick ask a clear label and maps it to one or more indexed collections.
                The default scope is the workspace context used when no System is selected.
              </p>
            </div>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-sm font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
              [disabled]="!canEdit()"
              (click)="addScope()"
            >
              <app-icon name="plus" [size]="14" /> Add scope
            </button>
          </div>

          <div class="divide-y divide-white/5">
            @for (scope of scopes(); track scope.key; let i = $index) {
              <article class="p-5">
                <div class="flex flex-wrap items-center justify-between gap-3 mb-5">
                  <label class="scope-default-toggle">
                    <input
                      type="radio"
                      name="default_scope"
                      [checked]="scope.is_default"
                      [disabled]="!canEdit()"
                      (change)="setDefaultScope(i)"
                    />
                    <span>
                      <span class="block text-sm font-semibold text-gray-100">Default context</span>
                      <span class="block text-xs text-gray-500">Used by Quick ask unless the default assistant profile defines another source.</span>
                    </span>
                  </label>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1.5 rounded bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-200 ring-1 ring-red-400/20 disabled:opacity-40"
                    [disabled]="!canEdit() || scopes().length <= 1"
                    (click)="removeScope(i)"
                  >
                    <app-icon name="trash-2" [size]="13" /> Remove
                  </button>
                </div>

                <div class="grid gap-4 md:grid-cols-[minmax(150px,0.75fr)_minmax(240px,1.25fr)]">
                  <label class="block">
                    <span class="field-label">Key</span>
                    <input class="ag-field font-mono" [(ngModel)]="scope.key" [disabled]="!canEdit()" />
                  </label>
                  <label class="block">
                    <span class="field-label">Visible label</span>
                    <input class="ag-field" [(ngModel)]="scope.label" [disabled]="!canEdit()" />
                  </label>
                </div>

                <div class="grid gap-4 mt-4 md:grid-cols-2 xl:grid-cols-[minmax(160px,220px)_minmax(110px,140px)_minmax(200px,1fr)_minmax(200px,1fr)]">
                  <label class="block">
                    <span class="field-label">Retrieval mode</span>
                    <span class="ag-select-wrap">
                      <select class="ag-select" [(ngModel)]="scope.default_mode" [disabled]="!canEdit()">
                        @for (mode of ragModes; track mode) {
                          <option [ngValue]="mode">{{ mode }}</option>
                        }
                      </select>
                      <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                    </span>
                  </label>
                  <label class="block">
                    <span class="field-label">Top-K</span>
                    <input class="ag-field" type="number" min="1" max="50" [(ngModel)]="scope.top_k" [disabled]="!canEdit()" />
                  </label>
                  <label class="block">
                    <span class="field-label">Table profile</span>
                    <span class="ag-select-wrap">
                      <select class="ag-select" [(ngModel)]="scope.table_profile_key" [disabled]="!canEdit()">
                        <option value="">Workspace default</option>
                        @for (profile of tableProfileOptions(); track profile.key) {
                          <option [ngValue]="profile.key">{{ profile.label || profile.key }}</option>
                        }
                      </select>
                      <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                    </span>
                  </label>
                  <label class="block">
                    <span class="field-label">Document profile</span>
                    <span class="ag-select-wrap">
                      <select class="ag-select" [(ngModel)]="scope.document_profile_key" [disabled]="!canEdit()">
                        <option value="">Workspace default</option>
                        @for (profile of documentProfileOptions(); track profile.key) {
                          <option [ngValue]="profile.key">{{ profile.label || profile.key }}</option>
                        }
                      </select>
                      <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                    </span>
                  </label>
                </div>

                <label class="block mt-4">
                  <span class="field-label">Description</span>
                  <input class="ag-field" [(ngModel)]="scope.description" [disabled]="!canEdit()" />
                </label>

                <label class="block mt-4">
                  <span class="field-label">Collection slugs</span>
                  <input
                    class="ag-field font-mono"
                    [(ngModel)]="scope.collection_slugs_text"
                    [disabled]="!canEdit()"
                    placeholder="collection-a, collection-b"
                  />
                </label>

                <div class="knowledge-guide-panel mt-5">
                  <div class="knowledge-guide-header">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Knowledge guide</p>
                      <h4 class="text-sm font-semibold text-white mt-1">Markdown context for this scope</h4>
                      <p class="text-xs text-gray-500 mt-1 leading-relaxed">
                        Published guides are injected into retrieval, query expansion and the answer prompt as a source distinct from raw documents.
                      </p>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                      @if (currentGuideForScope(scope.key); as guide) {
                        <span class="guide-badge" [class.guide-badge-published]="guide.status === 'published'">
                          v{{ guide.version }} · {{ guide.status }}
                        </span>
                        <button
                          type="button"
                          class="guide-button"
                          (click)="openGuideEditor(scope.key, guide)"
                        >
                          <app-icon name="pencil" [size]="13" /> Edit
                        </button>
                      } @else {
                        <button
                          type="button"
                          class="guide-button"
                          [disabled]="!canEdit()"
                          (click)="openGuideEditor(scope.key)"
                        >
                          <app-icon name="plus" [size]="13" /> Add guide
                        </button>
                      }
                      <button
                        type="button"
                        class="guide-button"
                        [disabled]="guideVersionsForScope(scope.key).length === 0"
                        (click)="toggleGuideHistory(scope.key)"
                      >
                        <app-icon name="history" [size]="13" /> History
                      </button>
                    </div>
                  </div>

                  @if (currentGuideForScope(scope.key); as guide) {
                    <div class="knowledge-guide-current">
                      <div class="min-w-0">
                        <p class="text-sm font-semibold text-gray-100 truncate">{{ guide.title }}</p>
                        <p class="mt-1 text-xs leading-relaxed text-gray-500 line-clamp-2">{{ guide.snippet || guide.markdown || 'No markdown yet.' }}</p>
                      </div>
                      <div class="guide-current-actions">
                        @if (guide.status !== 'published') {
                          <button type="button" class="guide-button guide-button-good" [disabled]="!canEdit()" (click)="publishGuide(guide)">
                            <app-icon name="send" [size]="13" /> Publish
                          </button>
                        }
                        @if (guide.status !== 'archived') {
                          <button type="button" class="guide-button guide-button-danger" [disabled]="!canEdit()" (click)="archiveGuide(guide)">
                            <app-icon name="archive" [size]="13" /> Archive
                          </button>
                        }
                      </div>
                    </div>
                  } @else {
                    <div class="knowledge-guide-empty">
                      No guide attached to this scope yet. Add one when users need domain vocabulary, abbreviations or interpretation rules that should travel with retrieval.
                    </div>
                  }

                  @if (guideHistoryScope() === scope.key) {
                    <div class="guide-history">
                      @for (version of guideVersionsForScope(scope.key); track version.id) {
                        <div class="guide-history-row">
                          <div class="min-w-0">
                            <p class="text-xs font-semibold text-gray-100 truncate">
                              v{{ version.version }} · {{ version.status }} · {{ version.title }}
                            </p>
                            <p class="mt-1 text-[11px] text-gray-500">
                              {{ formatDate(version.created_at) }} @if (version.published_at) { · published {{ formatDate(version.published_at) }} }
                            </p>
                          </div>
                          <div class="flex items-center gap-2">
                            <button type="button" class="guide-button" (click)="openGuideEditor(scope.key, version, 'restore')">
                              <app-icon name="rotate-ccw" [size]="13" /> Restore
                            </button>
                            <button type="button" class="guide-button" (click)="openGuideEditor(scope.key, version)">
                              <app-icon name="eye" [size]="13" /> View
                            </button>
                          </div>
                        </div>
                      } @empty {
                        <p class="px-3 py-2 text-xs text-gray-500">No version history yet.</p>
                      }
                    </div>
                  }

                  @if (guideEditor()?.scope_key === scope.key) {
                    @if (guideEditor(); as editor) {
                      <div class="guide-editor">
                        <div class="guide-editor-bar">
                          <div>
                            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">
                              {{ editor.mode === 'create' ? 'New guide' : editor.mode === 'restore' ? 'Restore version' : 'Edit guide' }}
                            </p>
                            <h5 class="text-sm font-semibold text-white mt-1">
                              {{ editor.mode === 'restore' ? 'Create a new current version from v' + editor.source_version : 'Versioned Markdown editor' }}
                            </h5>
                          </div>
                          <button type="button" class="guide-button" (click)="closeGuideEditor()">
                            <app-icon name="x" [size]="13" /> Close
                          </button>
                        </div>

                        <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_160px]">
                          <label class="block">
                            <span class="field-label">Title</span>
                            <input
                              class="ag-field"
                              [ngModel]="editor.title"
                              [disabled]="!canEdit()"
                              (ngModelChange)="updateGuideEditor('title', $event)"
                            />
                          </label>
                          <label class="block">
                            <span class="field-label">Status</span>
                            <span class="ag-select-wrap">
                              <select
                                class="ag-select"
                                [ngModel]="editor.status"
                                [disabled]="!canEdit()"
                                (ngModelChange)="updateGuideEditor('status', $event)"
                              >
                                <option value="draft">draft</option>
                                <option value="published">published</option>
                                <option value="archived">archived</option>
                              </select>
                              <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                            </span>
                          </label>
                        </div>

                        <div class="guide-editor-grid">
                          <label class="block">
                            <span class="field-label">Markdown</span>
                            <textarea
                              class="ag-field guide-markdown-field"
                              [ngModel]="editor.markdown"
                              [disabled]="!canEdit()"
                              spellcheck="false"
                              (ngModelChange)="updateGuideEditor('markdown', $event)"
                            ></textarea>
                          </label>
                          <div class="guide-preview">
                            <span class="field-label">Preview</span>
                            <div class="guide-preview-body">
                              @for (line of markdownPreviewLines(editor.markdown); track $index) {
                                @if (markdownLineKind(line) === 'h1') {
                                  <h1>{{ cleanMarkdownLine(line) }}</h1>
                                } @else if (markdownLineKind(line) === 'h2') {
                                  <h2>{{ cleanMarkdownLine(line) }}</h2>
                                } @else if (markdownLineKind(line) === 'h3') {
                                  <h3>{{ cleanMarkdownLine(line) }}</h3>
                                } @else if (markdownLineKind(line) === 'li') {
                                  <p class="guide-preview-li">{{ cleanMarkdownLine(line) }}</p>
                                } @else if (cleanMarkdownLine(line)) {
                                  <p>{{ cleanMarkdownLine(line) }}</p>
                                } @else {
                                  <div class="h-2"></div>
                                }
                              }
                            </div>
                          </div>
                        </div>

                        <div class="guide-editor-actions">
                          <p class="text-xs text-gray-500">
                            Saving creates a new auditable version. Published versions are used by chat retrieval immediately.
                          </p>
                          <div class="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              class="guide-button"
                              [disabled]="guideSaving() || !canEdit()"
                              (click)="saveGuide('draft')"
                            >
                              <app-icon name="save" [size]="13" /> Save draft
                            </button>
                            <button
                              type="button"
                              class="guide-button guide-button-good"
                              [disabled]="guideSaving() || !canEdit()"
                              (click)="saveGuide('published')"
                            >
                              <app-icon name="send" [size]="13" /> Publish
                            </button>
                          </div>
                        </div>
                      </div>
                    }
                  }
                </div>
              </article>
            }
          </div>
        </section>

        <section class="ck-surface rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Table Intelligence</p>
              <h3 class="text-base font-semibold text-white mt-1">Analytical spreadsheet profiles</h3>
              <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
                Profiles tell Agentium how to interpret table facts for lookup, comparison and calculation. They guide
                query expansion and aggregation, while raw cells remain the proof source.
              </p>
            </div>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-sm font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
              [disabled]="!canEdit()"
              (click)="addTableProfile()"
            >
              <app-icon name="plus" [size]="14" /> Add profile
            </button>
          </div>

          <div class="p-5 space-y-5">
            <label class="block max-w-md">
              <span class="field-label">Workspace default profile</span>
              <span class="ag-select-wrap">
                <select class="ag-select" [(ngModel)]="tableIntelligenceDraft.default_profile" [disabled]="!canEdit()">
                  <option value="">Generic default</option>
                  @for (profile of tableIntelligenceDraft.profiles; track profile.key) {
                    <option [ngValue]="profile.key">{{ profile.label || profile.key }}</option>
                  }
                </select>
                <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
              </span>
            </label>

            <div class="space-y-4">
              @for (profile of tableIntelligenceDraft.profiles; track profile; let i = $index) {
                <article class="table-profile-card">
                  <div class="table-profile-head">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Profile {{ i + 1 }}</p>
                      <h4 class="text-sm font-semibold text-white mt-1">{{ profile.label || profile.key || 'Untitled profile' }}</h4>
                    </div>
                    <button
                      type="button"
                      class="guide-button guide-button-danger"
                      [disabled]="!canEdit()"
                      (click)="removeTableProfile(i)"
                    >
                      <app-icon name="trash-2" [size]="13" /> Remove
                    </button>
                  </div>

                  <div class="grid gap-4 md:grid-cols-[minmax(160px,0.8fr)_minmax(220px,1fr)]">
                    <label class="block">
                      <span class="field-label">Key</span>
                      <input class="ag-field font-mono" [(ngModel)]="profile.key" [disabled]="!canEdit()" placeholder="generic_industrial_tests" />
                    </label>
                    <label class="block">
                      <span class="field-label">Label</span>
                      <input class="ag-field" [(ngModel)]="profile.label" [disabled]="!canEdit()" placeholder="Industrial test tables" />
                    </label>
                  </div>

                  <label class="block mt-4">
                    <span class="field-label">Description</span>
                    <input
                      class="ag-field"
                      [(ngModel)]="profile.description"
                      [disabled]="!canEdit()"
                      placeholder="How this profile should interpret spreadsheet facts."
                    />
                  </label>

                  <div class="grid gap-4 mt-4 lg:grid-cols-2">
                    <label class="block">
                      <span class="field-label">Synonyms</span>
                      <textarea
                        class="ag-field table-map-field"
                        [(ngModel)]="profile.synonyms_text"
                        [disabled]="!canEdit()"
                        spellcheck="false"
                        placeholder="dimension: diameter, length, thickness&#10;hemp: chanvre"
                      ></textarea>
                    </label>
                    <label class="block">
                      <span class="field-label">Metric aliases</span>
                      <textarea
                        class="ag-field table-map-field"
                        [(ngModel)]="profile.metric_aliases_text"
                        [disabled]="!canEdit()"
                        spellcheck="false"
                        placeholder="weight: poids, mass&#10;dimension: diamètre, épaisseur"
                      ></textarea>
                    </label>
                  </div>

                  <div class="grid gap-3 mt-4 lg:grid-cols-3">
                    <label class="voice-toggle-row voice-toggle-compact">
                      <input type="checkbox" [(ngModel)]="profile.allow_mean" [disabled]="!canEdit()" />
                      <span>
                        <strong>Allow mean</strong>
                        <small>Permit average calculations when evidence is compatible.</small>
                      </span>
                    </label>
                    <label class="voice-toggle-row voice-toggle-compact">
                      <input type="checkbox" [(ngModel)]="profile.require_compatible_units" [disabled]="!canEdit()" />
                      <span>
                        <strong>Require compatible units</strong>
                        <small>Block aggregate answers when units cannot be reconciled.</small>
                      </span>
                    </label>
                    <label class="voice-toggle-row voice-toggle-compact">
                      <input type="checkbox" [(ngModel)]="profile.exclude_non_numeric" [disabled]="!canEdit()" />
                      <span>
                        <strong>Exclude non numeric</strong>
                        <small>Keep textual or empty values visible as exclusions.</small>
                      </span>
                    </label>
                  </div>

                  <div class="grid gap-4 mt-4 md:grid-cols-3">
                    <label class="block">
                      <span class="field-label">Ambiguity policy</span>
                      <span class="ag-select-wrap">
                        <select class="ag-select" [(ngModel)]="profile.ambiguity_policy" [disabled]="!canEdit()">
                          <option value="ask_when_metric_unclear">Ask when metric unclear</option>
                          <option value="answer_with_assumptions">Answer with assumptions</option>
                          <option value="evidence_gap">Say when sources are insufficient</option>
                        </select>
                        <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                      </span>
                    </label>
                    <label class="voice-toggle-row voice-toggle-compact">
                      <input type="checkbox" [(ngModel)]="profile.require_cell_citations" [disabled]="!canEdit()" />
                      <span>
                        <strong>Cell citations</strong>
                        <small>Require file, sheet and cell evidence.</small>
                      </span>
                    </label>
                    <label class="voice-toggle-row voice-toggle-compact">
                      <input type="checkbox" [(ngModel)]="profile.show_excluded_values" [disabled]="!canEdit()" />
                      <span>
                        <strong>Show exclusions</strong>
                        <small>Expose rows skipped by calculation.</small>
                      </span>
                    </label>
                  </div>
                </article>
              } @empty {
                <div class="rounded-md border border-white/10 bg-black/10 px-4 py-5 text-sm text-gray-500">
                  No custom table profile. Agentium will use its generic provider-agnostic table interpretation profile.
                </div>
              }
            </div>
          </div>
        </section>

        <section class="ck-surface rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
            <div>
              <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Document & OCR Intelligence</p>
              <h3 class="text-base font-semibold text-white mt-1">Manuals, scans and visual evidence</h3>
              <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
                Document profiles guide procedure, warning and parameter lookup. OCR settings control how scans,
                images and low-text PDFs become searchable evidence.
              </p>
            </div>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-sm font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
              [disabled]="!canEdit()"
              (click)="addDocumentProfile()"
            >
              <app-icon name="plus" [size]="14" /> Add profile
            </button>
          </div>

          <div class="p-5 space-y-5">
            <div class="grid gap-4 lg:grid-cols-[minmax(260px,360px)_1fr]">
              <label class="block">
                <span class="field-label">Workspace default document profile</span>
                <span class="ag-select-wrap">
                  <select class="ag-select" [(ngModel)]="documentIntelligenceDraft.default_profile" [disabled]="!canEdit()">
                    <option value="">Generic default</option>
                    @for (profile of documentIntelligenceDraft.profiles; track profile.key) {
                      <option [ngValue]="profile.key">{{ profile.label || profile.key }}</option>
                    }
                  </select>
                  <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                </span>
              </label>
              <div class="rounded border border-cyan-400/20 bg-cyan-500/5 px-4 py-3 text-xs leading-relaxed text-cyan-50/80">
                V1 extracts structure and document facts. V1.5 exposes OCR evidence in the UI. V2 adds provider gating,
                OpenAI Vision enrichment and service-first OCR without locking Agentium to one provider.
              </div>
            </div>

            <div class="space-y-4">
              @for (profile of documentIntelligenceDraft.profiles; track profile; let i = $index) {
                <article class="table-profile-card">
                  <div class="table-profile-head">
                    <div>
                      <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Document profile {{ i + 1 }}</p>
                      <h4 class="text-sm font-semibold text-white mt-1">{{ profile.label || profile.key || 'Untitled profile' }}</h4>
                    </div>
                    <button
                      type="button"
                      class="guide-button guide-button-danger"
                      [disabled]="!canEdit()"
                      (click)="removeDocumentProfile(i)"
                    >
                      <app-icon name="trash-2" [size]="13" /> Remove
                    </button>
                  </div>

                  <div class="grid gap-4 md:grid-cols-[minmax(160px,0.8fr)_minmax(220px,1fr)]">
                    <label class="block">
                      <span class="field-label">Key</span>
                      <input class="ag-field font-mono" [(ngModel)]="profile.key" [disabled]="!canEdit()" placeholder="manuals_generic" />
                    </label>
                    <label class="block">
                      <span class="field-label">Label</span>
                      <input class="ag-field" [(ngModel)]="profile.label" [disabled]="!canEdit()" placeholder="Manuals and procedures" />
                    </label>
                  </div>

                  <label class="block mt-4">
                    <span class="field-label">Description</span>
                    <input class="ag-field" [(ngModel)]="profile.description" [disabled]="!canEdit()" placeholder="How this profile should interpret manuals and OCR facts." />
                  </label>

                  <div class="grid gap-4 mt-4 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
                    <label class="block">
                      <span class="field-label">Synonyms</span>
                      <textarea
                        class="ag-field table-map-field"
                        [(ngModel)]="profile.synonyms_text"
                        [disabled]="!canEdit()"
                        spellcheck="false"
                        placeholder="warning: attention, danger&#10;procedure: procédure, consigne"
                      ></textarea>
                    </label>
                    <label class="block">
                      <span class="field-label">Max candidate facts</span>
                      <input class="ag-field" type="number" min="100" max="20000" [(ngModel)]="profile.max_candidate_facts" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Max evidence rows</span>
                      <input class="ag-field" type="number" min="3" max="100" [(ngModel)]="profile.max_evidence_rows" [disabled]="!canEdit()" />
                    </label>
                  </div>
                </article>
              } @empty {
                <div class="rounded-md border border-white/10 bg-black/10 px-4 py-5 text-sm text-gray-500">
                  No custom document profile. Agentium will use its generic provider-neutral document interpretation profile.
                </div>
              }
            </div>

            <article class="table-profile-card">
              <div class="table-profile-head">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">OCR providers</p>
                  <h4 class="text-sm font-semibold text-white mt-1">Visual document ingestion</h4>
                  <p class="mt-1 text-xs text-gray-500">
                    Provider order is tried left-to-right. OpenAI Vision is opt-in and only used when enabled.
                  </p>
                </div>
              </div>

              <div class="grid gap-3 lg:grid-cols-3">
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="documentIntelligenceDraft.ocr.enabled" [disabled]="!canEdit()" />
                  <span><strong>OCR enabled</strong><small>Allow image and scanned-PDF text extraction.</small></span>
                </label>
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="documentIntelligenceDraft.ocr.scan_detection" [disabled]="!canEdit()" />
                  <span><strong>Auto scan detection</strong><small>Run OCR when native PDF text is weak.</small></span>
                </label>
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="documentIntelligenceDraft.ocr.required" [disabled]="!canEdit()" />
                  <span><strong>Required</strong><small>Fail ingestion if no OCR provider can return text.</small></span>
                </label>
              </div>

              <div class="grid gap-4 mt-4 lg:grid-cols-2">
                <label class="block">
                  <span class="field-label">Provider priority</span>
                  <input class="ag-field font-mono" [(ngModel)]="documentIntelligenceDraft.ocr.provider_priority_text" [disabled]="!canEdit()" placeholder="ppocr_service, tesseract_local, openai_vision" />
                </label>
                <label class="block">
                  <span class="field-label">Languages</span>
                  <input class="ag-field font-mono" [(ngModel)]="documentIntelligenceDraft.ocr.languages_text" [disabled]="!canEdit()" placeholder="eng, fra" />
                </label>
              </div>

              <div class="grid gap-4 mt-4 md:grid-cols-2 xl:grid-cols-4">
                <label class="block">
                  <span class="field-label">Min native PDF chars</span>
                  <input class="ag-field" type="number" min="0" max="5000" [(ngModel)]="documentIntelligenceDraft.ocr.min_native_pdf_chars" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Min confidence</span>
                  <input class="ag-field" type="number" min="0" max="1" step="0.05" [(ngModel)]="documentIntelligenceDraft.ocr.min_confidence" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Timeout seconds</span>
                  <input class="ag-field" type="number" min="1" max="180" [(ngModel)]="documentIntelligenceDraft.ocr.timeout_seconds" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Retries</span>
                  <input class="ag-field" type="number" min="0" max="5" [(ngModel)]="documentIntelligenceDraft.ocr.retries" [disabled]="!canEdit()" />
                </label>
              </div>

              <label class="block mt-4">
                <span class="field-label">PP-OCR endpoint URL</span>
                <input class="ag-field font-mono" [(ngModel)]="documentIntelligenceDraft.ocr.ppocr_endpoint_url" [disabled]="!canEdit()" placeholder="http://ocr-service:8000" />
              </label>

              <div class="grid gap-3 mt-4 lg:grid-cols-3">
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="documentIntelligenceDraft.ocr.force_ocr" [disabled]="!canEdit()" />
                  <span><strong>Force OCR</strong><small>OCR every PDF page even if native text exists.</small></span>
                </label>
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="documentIntelligenceDraft.ocr.openai_vision_enabled" [disabled]="!canEdit()" />
                  <span><strong>OpenAI Vision fallback</strong><small>Use only when listed in priority and deterministic OCR is weak.</small></span>
                </label>
                <label class="block">
                  <span class="field-label">OpenAI detail</span>
                  <span class="ag-select-wrap">
                    <select class="ag-select" [(ngModel)]="documentIntelligenceDraft.ocr.openai_detail" [disabled]="!canEdit()">
                      <option value="low">low</option>
                      <option value="auto">auto</option>
                      <option value="high">high</option>
                    </select>
                    <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                  </span>
                </label>
              </div>

              <div class="grid gap-4 mt-4 md:grid-cols-2 xl:grid-cols-4">
                <label class="block">
                  <span class="field-label">OpenAI model</span>
                  <input class="ag-field font-mono" [(ngModel)]="documentIntelligenceDraft.ocr.openai_model" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Max image bytes</span>
                  <input class="ag-field" type="number" min="100000" max="50000000" [(ngModel)]="documentIntelligenceDraft.ocr.openai_max_image_bytes" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Enrich min chars</span>
                  <input class="ag-field" type="number" min="0" max="1000" [(ngModel)]="documentIntelligenceDraft.ocr.openai_enrich_min_chars" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Enrich confidence</span>
                  <input class="ag-field" type="number" min="0" max="1" step="0.05" [(ngModel)]="documentIntelligenceDraft.ocr.openai_enrich_min_confidence" [disabled]="!canEdit()" />
                </label>
              </div>
            </article>
          </div>
        </section>

        <section class="ck-surface rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Chat surface</p>
              <h3 class="text-base font-semibold text-white mt-1">Chat defaults</h3>
            <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
              Chat defaults are the portable baseline. The preview below shows the effective Quick ask surface after
              assistant profile overrides and generated source prompts are applied.
            </p>
          </div>

          <div class="p-5 space-y-4">
            <div class="grid gap-4 lg:grid-cols-2">
              <label class="block">
                <span class="field-label">Empty state title</span>
                <input class="ag-field" [(ngModel)]="chatDraft.title" [disabled]="!canEdit()" placeholder="Posez votre question" />
              </label>
              <label class="block">
                <span class="field-label">Input placeholder</span>
                <input class="ag-field" [(ngModel)]="chatDraft.placeholder" [disabled]="!canEdit()" placeholder="Posez votre question..." />
              </label>
            </div>
            <label class="block">
              <span class="field-label">Subtitle</span>
              <input class="ag-field" [(ngModel)]="chatDraft.subtitle" [disabled]="!canEdit()" placeholder="Posez une question sur le contexte du workspace." />
            </label>

            <div class="rounded-md border border-white/10 bg-black/10">
              <div class="px-4 py-3 border-b border-white/5 flex items-center justify-between gap-3">
                <div>
                  <h4 class="text-sm font-semibold text-white">Suggested prompts</h4>
                  <p class="text-xs text-gray-500 mt-0.5">Optional. Leave empty to use generated prompts based on the active source.</p>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10"
                  [disabled]="!canEdit()"
                  (click)="addPrompt()"
                >
                  <app-icon name="plus" [size]="13" /> Add prompt
                </button>
              </div>

              <div class="divide-y divide-white/5">
                @if (chatDraft.prompt_pack.length === 0) {
                  <p class="px-4 py-5 text-sm text-gray-500">No custom prompts. The chat will use contextual Agentium suggestions.</p>
                }
                @for (prompt of chatDraft.prompt_pack; track prompt; let i = $index) {
                  <div class="p-4 grid gap-3 lg:grid-cols-[120px_1fr_180px_140px_40px] lg:items-end">
                    <label class="block">
                      <span class="field-label">Icon</span>
                      <input class="ag-field" [(ngModel)]="prompt.icon" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Prompt</span>
                      <input class="ag-field" [(ngModel)]="prompt.prompt" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Label</span>
                      <input class="ag-field" [(ngModel)]="prompt.label" [disabled]="!canEdit()" />
                    </label>
                    <label class="block">
                      <span class="field-label">Scope</span>
                      <span class="ag-select-wrap">
                        <select class="ag-select" [(ngModel)]="prompt.scope_key" [disabled]="!canEdit()">
                          <option value="">Any</option>
                          @for (scope of scopes(); track scope.key) {
                            <option [ngValue]="scope.key">{{ scope.label || scope.key }}</option>
                          }
                        </select>
                        <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                      </span>
                    </label>
                    <button
                      type="button"
                      class="h-10 rounded bg-red-500/10 text-red-200 ring-1 ring-red-400/20 disabled:opacity-40"
                      [disabled]="!canEdit()"
                      (click)="removePrompt(i)"
                      title="Remove prompt"
                    >
                      <app-icon name="trash-2" [size]="14" class="inline" />
                    </button>
                  </div>
                }
              </div>
            </div>

            <div class="effective-preview">
              <div class="effective-preview-header">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Effective Quick ask</p>
                  <h4 class="text-sm font-semibold text-white mt-1">What the chat will show now</h4>
                </div>
                <div class="text-right">
                  <p class="text-[10px] uppercase tracking-[0.16em] text-gray-500">Auto source</p>
                  <p class="text-sm font-semibold text-cyan-100">{{ effectiveScopeLabel() }}</p>
                </div>
              </div>

              @if (activeProfileChatOverrides()) {
                <div class="mx-4 mt-4 rounded border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                  The default assistant profile contributes chat metadata. This is why the live chat can differ from empty workspace fields.
                </div>
              }

              <div class="p-4">
                <div class="rounded border border-white/10 bg-black/20 p-4">
                  <div class="flex items-start gap-3">
                    <span class="preview-orb">
                      <app-icon name="sparkles" [size]="18" />
                    </span>
                    <div class="min-w-0">
                      <h5 class="text-base font-semibold text-white">{{ effectiveChatTitle() }}</h5>
                      <p class="mt-1 text-sm text-gray-400 leading-relaxed">{{ effectiveChatSubtitle() }}</p>
                      <p class="mt-3 rounded bg-black/25 px-3 py-2 text-xs text-gray-500 ring-1 ring-white/10">
                        Placeholder: <span class="text-gray-300">{{ effectiveChatPlaceholder() }}</span>
                      </p>
                    </div>
                  </div>

                  <div class="mt-4 grid gap-3 md:grid-cols-2">
                    @for (prompt of effectivePromptCards(); track prompt.label + prompt.prompt) {
                      <div class="preview-prompt">
                        <span class="preview-prompt-icon">
                          <app-icon [name]="prompt.icon || 'sparkles'" [size]="14" />
                        </span>
                        <div class="min-w-0">
                          <p class="text-sm font-semibold text-white truncate">{{ prompt.label }}</p>
                          <p class="mt-1 text-xs leading-relaxed text-gray-400 line-clamp-2">{{ prompt.prompt }}</p>
                        </div>
                      </div>
                    }
                  </div>
                </div>

                <button
                  type="button"
                  class="mt-3 inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
                  [disabled]="!canEdit()"
                  (click)="copyEffectiveChatToWorkspace()"
                >
                  <app-icon name="copy" [size]="13" /> Copy preview into chat defaults
                </button>
              </div>
            </div>
          </div>
        </section>

        <section class="ck-surface rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Voice interaction</p>
            <h3 class="text-base font-semibold text-white mt-1">Voice conversation defaults</h3>
            <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
              These settings make voice-to-voice a reusable workspace capability. Assistant profiles may override them
              in JSON, while demo mode only changes what users see.
            </p>
          </div>

          <div class="p-5 space-y-5">
            <div>
              <span class="field-label">Default voice mode</span>
              <div class="voice-mode-grid">
                @for (mode of voiceModeOptions; track mode.value) {
                  <button
                    type="button"
                    class="voice-mode-card"
                    [class.voice-mode-card-active]="voiceLoopDraft.default_mode === mode.value"
                    [disabled]="!canEdit()"
                    (click)="voiceLoopDraft.default_mode = mode.value"
                  >
                    <app-icon [name]="mode.icon" [size]="16" />
                    <span>
                      <strong>{{ mode.label }}</strong>
                      <small>{{ mode.help }}</small>
                    </span>
                  </button>
                }
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-3">
              <label class="block">
                <span class="field-label">Capture mode</span>
                <select class="ag-field" [(ngModel)]="voiceLoopDraft.capture_mode" [disabled]="!canEdit()">
                  <option value="normal">Normal</option>
                  <option value="robust">Robust</option>
                  <option value="manual_safe">Manual safe</option>
                </select>
              </label>
              <label class="voice-toggle-row">
                <input type="checkbox" [(ngModel)]="voiceLoopDraft.auto_capture_mode_enabled" [disabled]="!canEdit()" />
                <span>
                  <strong>Auto robust capture</strong>
                  <small>Reserved for metric-based degradation detection; off by default.</small>
                </span>
              </label>
              <label class="block">
                <span class="field-label">RMS threshold</span>
                <input class="ag-field" type="number" min="0.001" max="0.15" step="0.001" [(ngModel)]="voiceLoopDraft.rms_threshold" [disabled]="!canEdit()" />
              </label>
            </div>

            <div class="grid gap-3 lg:grid-cols-2">
              <label class="voice-toggle-row">
                <input type="checkbox" [(ngModel)]="voiceLoopDraft.auto_send_final_transcript" [disabled]="!canEdit()" />
                <span>
                  <strong>Auto-send final transcript</strong>
                  <small>Final speech becomes one chat turn; existing draft text is replaced.</small>
                </span>
              </label>
              <label class="voice-toggle-row">
                <input type="checkbox" [(ngModel)]="voiceLoopDraft.auto_endpoint" [disabled]="!canEdit()" />
                <span>
                  <strong>Auto endpoint</strong>
                  <small>Close the current voice turn after speech followed by silence.</small>
                </span>
              </label>
              <label class="voice-toggle-row">
                <input type="checkbox" [(ngModel)]="voiceLoopDraft.auto_rearm_after_tts" [disabled]="!canEdit()" />
                <span>
                  <strong>Rearm after spoken answer</strong>
                  <small>Reopen the microphone after TTS plus cooldown in conversation mode.</small>
                </span>
              </label>
              <label class="voice-toggle-row">
                <input type="checkbox" [(ngModel)]="voiceLoopDraft.barge_in" [disabled]="!canEdit()" />
                <span>
                  <strong>Barge-in</strong>
                  <small>Pause agent speech if the user starts talking again.</small>
                </span>
              </label>
            </div>

            <div class="grid gap-4 md:grid-cols-4">
              <label class="block">
                <span class="field-label">Silence ms</span>
                <input class="ag-field" type="number" min="300" max="5000" [(ngModel)]="voiceLoopDraft.silence_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">Min speech ms</span>
                <input class="ag-field" type="number" min="100" max="3000" [(ngModel)]="voiceLoopDraft.min_speech_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">Max turn ms</span>
                <input class="ag-field" type="number" min="5000" max="180000" [(ngModel)]="voiceLoopDraft.max_turn_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">Cooldown ms</span>
                <input class="ag-field" type="number" min="0" max="5000" [(ngModel)]="voiceLoopDraft.cooldown_ms" [disabled]="!canEdit()" />
              </label>
            </div>

            <div class="grid gap-4 md:grid-cols-5">
              <label class="block">
                <span class="field-label">Dictation silence ms</span>
                <input class="ag-field" type="number" min="300" max="30000" [(ngModel)]="voiceLoopDraft.dictation_silence_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">Dictation min speech ms</span>
                <input class="ag-field" type="number" min="100" max="3000" [(ngModel)]="voiceLoopDraft.dictation_min_speech_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">Endpoint grace ms</span>
                <input class="ag-field" type="number" min="0" max="3000" [(ngModel)]="voiceLoopDraft.endpoint_grace_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">VAD hangover ms</span>
                <input class="ag-field" type="number" min="0" max="2000" [(ngModel)]="voiceLoopDraft.vad_hangover_ms" [disabled]="!canEdit()" />
              </label>
              <label class="block">
                <span class="field-label">Min silence frames ms</span>
                <input class="ag-field" type="number" min="0" max="2000" [(ngModel)]="voiceLoopDraft.vad_min_silence_frames_ms" [disabled]="!canEdit()" />
              </label>
            </div>

            <div class="rounded-md border border-white/10 bg-black/10 p-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="voiceLoopDraft.commands_enabled" [disabled]="!canEdit()" />
                  <span>
                    <strong>Voice commands enabled</strong>
                    <small>Generic commands can be inherited by AYA, Andritz and future workspace assistants.</small>
                  </span>
                </label>
                <label class="block min-w-56 flex-1">
                  <span class="field-label">Optional trigger word</span>
                  <input class="ag-field" [(ngModel)]="voiceLoopDraft.trigger_word" [disabled]="!canEdit()" placeholder="Agentium" />
                </label>
              </div>
              <div class="grid gap-4 mt-4 lg:grid-cols-2">
                <label class="block">
                  <span class="field-label">Command packs</span>
                  <input class="ag-field font-mono" [(ngModel)]="voiceLoopDraft.command_packs_text" [disabled]="!canEdit()" placeholder="generic, fr_basic" />
                </label>
                <label class="block">
                  <span class="field-label">Stop phrases</span>
                  <input
                    class="ag-field"
                    [(ngModel)]="voiceLoopDraft.stop_phrases_text"
                    [disabled]="!canEdit()"
                    placeholder="on peut s'arrêter là, ça suffit"
                  />
                </label>
              </div>
              <p class="mt-3 text-xs text-gray-500 leading-relaxed">
                Profiles can override this with <span class="font-mono text-gray-300">voice_loop</span>. Example:
                AYA can keep the same voice conversation while changing only command wording or default mode.
              </p>
            </div>

            <div class="rounded-md border border-cyan-400/20 bg-cyan-500/5 p-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Voice output</p>
                  <h4 class="text-sm font-semibold text-white mt-1">Low-latency TTS playback</h4>
                  <p class="text-xs text-gray-400 mt-1 max-w-xl leading-relaxed">
                    Fast mode starts synthesis on short text chunks while the answer is still streaming. Demo mode shows
                    this as Voice output · Fast without revealing provider or model.
                  </p>
                </div>
                <label class="voice-toggle-row voice-toggle-compact">
                  <input type="checkbox" [(ngModel)]="voiceOutputDraft.interrupt_on_user_speech" [disabled]="!canEdit()" />
                  <span>
                    <strong>Interrupt on speech</strong>
                    <small>Stop queued TTS when the user starts speaking again.</small>
                  </span>
                </label>
              </div>
              <div class="mt-4 grid gap-4 md:grid-cols-3">
                <label class="block">
                  <span class="field-label">Latency profile</span>
                  <span class="ag-select-wrap">
                    <select class="ag-select" [(ngModel)]="voiceOutputDraft.latency_profile" [disabled]="!canEdit()">
                      <option value="fast">Fast</option>
                      <option value="balanced">Balanced</option>
                      <option value="quality">Quality</option>
                    </select>
                    <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                  </span>
                </label>
                <label class="block">
                  <span class="field-label">Voice</span>
                  <input class="ag-field" [(ngModel)]="voiceOutputDraft.voice" [disabled]="!canEdit()" placeholder="nova" />
                </label>
                <label class="block">
                  <span class="field-label">First flush ms</span>
                  <input class="ag-field" type="number" min="250" max="5000" [(ngModel)]="voiceOutputDraft.flush_timeout_ms" [disabled]="!canEdit()" />
                </label>
              </div>
              <div class="mt-4 grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="field-label">First chunk chars</span>
                  <input class="ag-field" type="number" min="12" max="240" [(ngModel)]="voiceOutputDraft.flush_first_chars" [disabled]="!canEdit()" />
                </label>
                <label class="block">
                  <span class="field-label">Next chunk chars</span>
                  <input class="ag-field" type="number" min="40" max="600" [(ngModel)]="voiceOutputDraft.flush_next_chars" [disabled]="!canEdit()" />
                </label>
              </div>
            </div>
          </div>
        </section>

        <section class="ck-surface rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5">
            <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Actions & Assistants</p>
            <h3 class="text-base font-semibold text-white mt-1">Action inheritance</h3>
            <p class="text-sm text-gray-400 mt-1 max-w-2xl leading-relaxed">
              Action packs are inherited by Chat, Voice, Flow Builder and System workbenches. Sentinel-CI keeps AYA
              actions isolated; Andritz inherits industrial Knowledge actions unless explicitly changed here.
            </p>
          </div>
          <div class="p-5 space-y-4">
            <div class="grid gap-4 lg:grid-cols-2">
              <label class="block">
                <span class="field-label">Enabled packs</span>
                <input
                  class="ag-field font-mono"
                  [(ngModel)]="actionSettingsDraft.enabled_packs_text"
                  [disabled]="!canEdit()"
                  placeholder="andritz_industrial_v1, sentinel_ci_aya_v1"
                />
              </label>
              <label class="block">
                <span class="field-label">Hidden packs</span>
                <input
                  class="ag-field font-mono"
                  [(ngModel)]="actionSettingsDraft.hidden_packs_text"
                  [disabled]="!canEdit()"
                  placeholder="sentinel_ci_aya_v1"
                />
              </label>
              <label class="block">
                <span class="field-label">Enabled actions</span>
                <input
                  class="ag-field font-mono"
                  [(ngModel)]="actionSettingsDraft.enabled_actions_text"
                  [disabled]="!canEdit()"
                  placeholder="aya.action_plan_status"
                />
              </label>
              <label class="block">
                <span class="field-label">Hidden actions</span>
                <input
                  class="ag-field font-mono"
                  [(ngModel)]="actionSettingsDraft.hidden_actions_text"
                  [disabled]="!canEdit()"
                  placeholder="aya.map_focus"
                />
              </label>
            </div>
            <div class="rounded-md border border-white/10 bg-black/10 px-4 py-3 text-xs text-gray-400 leading-relaxed">
              Resolution order: system override → assistant profile → workspace action pack → capability template → global default.
              Side-effect actions require confirmation unless marked direct-safe by the backend manifest.
            </div>
          </div>
        </section>
      </div>

      <aside class="space-y-5">
        <section class="ck-surface rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Available collections</p>
          <h3 class="text-sm font-semibold text-white mt-1">Indexed collections</h3>
          <p class="text-xs text-gray-500 mt-2">
            Collections are raw indexed stores. Add one to the default context so Chat can use it, or open the
            collection for diagnostics. Copying the slug is only for manual edits.
          </p>
          <div class="mt-4 max-h-72 overflow-y-auto space-y-2 pr-1">
            @for (collection of collections(); track collection) {
              <article class="collection-option" [class.collection-option-attached]="collectionInDefaultScope(collection)">
                <button
                  type="button"
                  class="collection-option-main"
                  [disabled]="!canEdit() || collectionInDefaultScope(collection)"
                  (click)="addCollectionToDefaultScope(collection)"
                >
                  <span class="font-mono">{{ collection }}</span>
                  <small>
                    {{ collectionInDefaultScope(collection) ? 'In default context' : 'Add to default context' }}
                  </small>
                </button>
                <div class="collection-option-actions">
                  <a class="guide-button" [routerLink]="['/knowledge', collection]">
                    <app-icon name="external-link" [size]="13" /> Open
                  </a>
                  <button type="button" class="guide-button" (click)="copyCollection(collection)">
                    <app-icon name="copy" [size]="13" /> Copy
                  </button>
                </div>
              </article>
            } @empty {
              <p class="text-sm text-gray-500">No indexed collection reported yet.</p>
            }
          </div>
        </section>

        <section class="ck-surface rounded-md p-5">
          <p class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Assistant profile</p>
          <h3 class="text-sm font-semibold text-white mt-1">Default assistant</h3>
          <p class="mt-2 text-xs text-gray-500 leading-relaxed">
            The default assistant may set the automatic source scope and, when configured, the visible Quick ask surface.
          </p>
          <div class="effective-source-note mt-4">
            <span class="ck-mono text-[10px] uppercase tracking-wider text-cyan-300">Effective Quick ask source</span>
            <strong>{{ effectiveScopeLabel() }}</strong>
            <small>{{ effectiveScopeOrigin() }}</small>
          </div>
          <label class="block mt-4">
            <span class="field-label">assistant_profile_default</span>
            <span class="ag-select-wrap">
              <select class="ag-select" [(ngModel)]="assistantProfileDefault" [disabled]="!canEdit()">
                <option value="">None</option>
                @for (profile of assistantProfileOptions(); track profile) {
                  <option [ngValue]="profile">{{ profile }}</option>
                }
              </select>
              <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
            </span>
          </label>

          <div class="mt-5 rounded-md border border-white/10 bg-black/10 overflow-hidden">
            <div class="px-4 py-3 border-b border-white/5 flex items-center justify-between gap-3">
              <div>
                <h4 class="text-sm font-semibold text-white">Profile editor</h4>
                <p class="text-xs text-gray-500 mt-0.5">Edit the reusable assistant persona without touching raw JSON.</p>
              </div>
              <button
                type="button"
                class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-1.5 text-xs text-gray-200 ring-1 ring-white/10 disabled:opacity-40"
                [disabled]="!canEdit()"
                (click)="addAssistantProfile()"
              >
                <app-icon name="plus" [size]="13" /> Add
              </button>
            </div>

            @if (activeProfileDraft(); as profile) {
              <div class="p-4 space-y-4">
                <div class="flex items-center gap-2">
                  <span class="ag-select-wrap flex-1">
                    <select
                      class="ag-select"
                      [ngModel]="selectedAssistantProfileIndex()"
                      [disabled]="!canEdit()"
                      (ngModelChange)="selectedAssistantProfileIndex.set($event)"
                    >
                      @for (item of assistantProfiles(); track item.key || $index; let i = $index) {
                        <option [ngValue]="i">{{ item.label || item.key || ('Profile ' + (i + 1)) }}</option>
                      }
                    </select>
                    <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                  </span>
                  <button
                    type="button"
                    class="h-10 px-3 rounded bg-red-500/10 text-red-200 ring-1 ring-red-400/20 disabled:opacity-40"
                    [disabled]="!canEdit()"
                    (click)="removeAssistantProfile(selectedAssistantProfileIndex())"
                    title="Remove profile"
                  >
                    <app-icon name="trash-2" [size]="14" class="inline" />
                  </button>
                </div>

                <div class="grid gap-3 md:grid-cols-2">
                  <label class="block">
                    <span class="field-label">Key</span>
                    <input class="ag-field font-mono" [ngModel]="profile.key || ''" [disabled]="!canEdit()" (ngModelChange)="updateAssistantProfileField('key', $event)" />
                  </label>
                  <label class="block">
                    <span class="field-label">Label</span>
                    <input class="ag-field" [ngModel]="profile.label || ''" [disabled]="!canEdit()" (ngModelChange)="updateAssistantProfileField('label', $event)" />
                  </label>
                </div>

                <label class="block">
                  <span class="field-label">Subtitle</span>
                  <input class="ag-field" [ngModel]="profile.subtitle || ''" [disabled]="!canEdit()" (ngModelChange)="updateAssistantProfileField('subtitle', $event)" />
                </label>

                <label class="block">
                  <span class="field-label">Default source scope</span>
                  <span class="ag-select-wrap">
                    <select
                      class="ag-select"
                      [ngModel]="profile.default_knowledge_scope || ''"
                      [disabled]="!canEdit()"
                      (ngModelChange)="updateAssistantProfileField('default_knowledge_scope', $event)"
                    >
                      <option value="">Workspace default</option>
                      @for (scope of scopes(); track scope.key) {
                        <option [ngValue]="scope.key">{{ scope.label || scope.key }}</option>
                      }
                    </select>
                    <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                  </span>
                </label>

                <div class="grid gap-3 md:grid-cols-2">
                  <label class="block">
                    <span class="field-label">Design mode</span>
                    <input class="ag-field" [ngModel]="profile.design_mode || ''" [disabled]="!canEdit()" placeholder="agentium, sentinel_ci" (ngModelChange)="updateAssistantProfileField('design_mode', $event)" />
                  </label>
                  <label class="block">
                    <span class="field-label">Tone</span>
                    <input class="ag-field" [ngModel]="profile.tone || ''" [disabled]="!canEdit()" placeholder="technical, ministerial" (ngModelChange)="updateAssistantProfileField('tone', $event)" />
                  </label>
                </div>

                <div class="rounded-md border border-white/10 bg-white/[0.025] p-3 space-y-3">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="text-sm font-semibold text-white">Profile chat override</p>
                      <p class="text-xs text-gray-500 mt-0.5">Optional surface metadata for Quick ask.</p>
                    </div>
                    <button
                      type="button"
                      class="inline-flex items-center gap-1.5 rounded bg-white/5 px-2.5 py-1.5 text-[11px] text-gray-200 ring-1 ring-white/10 disabled:opacity-40"
                      [disabled]="!canEdit()"
                      (click)="copyWorkspaceChatToProfile()"
                    >
                      <app-icon name="copy" [size]="12" /> Use workspace chat
                    </button>
                  </div>
                  <label class="block">
                    <span class="field-label">Chat title</span>
                    <input class="ag-field" [ngModel]="profileChatField('title')" [disabled]="!canEdit()" (ngModelChange)="updateAssistantProfileChatField('title', $event)" />
                  </label>
                  <label class="block">
                    <span class="field-label">Placeholder</span>
                    <input class="ag-field" [ngModel]="profileChatField('placeholder')" [disabled]="!canEdit()" (ngModelChange)="updateAssistantProfileChatField('placeholder', $event)" />
                  </label>
                </div>

                <div class="rounded-md border border-white/10 bg-white/[0.025] p-3 space-y-3">
                  <p class="text-sm font-semibold text-white">Profile voice override</p>
                  <div class="grid gap-3 md:grid-cols-2">
                    <label class="block">
                      <span class="field-label">Voice mode</span>
                      <span class="ag-select-wrap">
                        <select
                          class="ag-select"
                          [ngModel]="profileVoiceField('default_mode') || ''"
                          [disabled]="!canEdit()"
                          (ngModelChange)="updateAssistantProfileVoiceField('default_mode', $event)"
                        >
                          <option value="">Workspace default</option>
                          @for (mode of voiceModeOptions; track mode.value) {
                            <option [ngValue]="mode.value">{{ mode.label }}</option>
                          }
                        </select>
                        <app-icon name="chevron-down" [size]="14" class="ag-select-chevron" />
                      </span>
                    </label>
                    <label class="block">
                      <span class="field-label">Stop phrases</span>
                      <input
                        class="ag-field"
                        [ngModel]="profileVoiceListField('stop_phrases')"
                        [disabled]="!canEdit()"
                        placeholder="on peut s'arrêter là"
                        (ngModelChange)="updateAssistantProfileVoiceListField('stop_phrases', $event)"
                      />
                    </label>
                  </div>
                </div>
              </div>
            } @else {
              <p class="px-4 py-5 text-sm text-gray-500">No assistant profiles yet. Add one to define a reusable chat and voice persona.</p>
            }
          </div>

          <label class="block mt-4">
            <span class="field-label">assistant_profiles JSON · advanced</span>
            <textarea
              class="ag-field min-h-56 font-mono text-xs leading-relaxed"
              [(ngModel)]="assistantProfilesJson"
              [disabled]="!canEdit()"
              spellcheck="false"
            ></textarea>
          </label>
          <p class="mt-3 text-xs text-gray-500 leading-relaxed">
            This remains an advanced field until assistant profiles get a dedicated editor.
          </p>
        </section>
      </aside>
    </div>
  `,
  styles: [`
    .field-label {
      display: block;
      margin-bottom: 0.375rem;
      font-size: 10px;
      line-height: 1;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: rgb(107 114 128);
      font-weight: 700;
    }
    .ag-field {
      width: 100%;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.28);
      color: rgb(243 244 246);
      padding: 0.625rem 0.75rem;
      font-size: 0.875rem;
      outline: none;
      transition: border-color 120ms, box-shadow 120ms, background 120ms;
    }
    .ag-field:focus {
      border-color: rgba(56,189,248,0.65);
      box-shadow: 0 0 0 2px rgba(56,189,248,0.18);
      background: rgba(0,0,0,0.36);
    }
    .ag-field:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .ag-select-wrap {
      position: relative;
      display: block;
    }
    .ag-select {
      width: 100%;
      height: 40px;
      appearance: none;
      -webkit-appearance: none;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.30);
      color: rgb(243 244 246);
      padding: 0 2.25rem 0 0.75rem;
      font-size: 0.875rem;
      outline: none;
      color-scheme: dark;
    }
    .ag-select:focus {
      border-color: rgba(56,189,248,0.65);
      box-shadow: 0 0 0 2px rgba(56,189,248,0.18);
    }
    .ag-select-chevron {
      position: absolute;
      right: 0.75rem;
      top: 50%;
      transform: translateY(-50%);
      color: rgb(156 163 175);
      pointer-events: none;
    }
    .scope-default-toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.75rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.025);
      padding: 0.625rem 0.75rem;
    }
    .scope-default-toggle input {
      width: 1rem;
      height: 1rem;
      accent-color: rgb(56 189 248);
    }
    .effective-preview {
      overflow: hidden;
      border-radius: 8px;
      border: 1px solid rgba(34,211,238,0.22);
      background:
        radial-gradient(circle at 80% 0%, rgba(34,211,238,0.08), transparent 34%),
        rgba(0,0,0,0.12);
    }
    .effective-preview-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding: 1rem;
    }
    .preview-orb {
      display: inline-flex;
      width: 2.5rem;
      height: 2.5rem;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(14,165,233,0.18), rgba(124,58,237,0.22));
      color: rgb(34 211 238);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
    }
    .preview-prompt {
      display: flex;
      min-height: 5rem;
      align-items: flex-start;
      gap: 0.75rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.025);
      padding: 0.875rem;
    }
    .preview-prompt-icon {
      display: inline-flex;
      width: 2rem;
      height: 2rem;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      border-radius: 7px;
      background: rgba(34,211,238,0.10);
      color: rgb(34 211 238);
    }
    .voice-mode-grid {
      display: grid;
      gap: 0.75rem;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .voice-mode-card {
      min-height: 5.5rem;
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.025);
      padding: 0.875rem;
      text-align: left;
      color: rgb(209 213 219);
      transition: border-color 120ms, background 120ms, box-shadow 120ms;
    }
    .voice-mode-card:hover:not(:disabled) {
      border-color: rgba(56,189,248,0.35);
      background: rgba(34,211,238,0.05);
    }
    .voice-mode-card-active {
      border-color: rgba(34,211,238,0.75);
      background: rgba(34,211,238,0.09);
      box-shadow: 0 0 0 1px rgba(34,211,238,0.12);
      color: white;
    }
    .voice-mode-card strong {
      display: block;
      font-size: 0.875rem;
      color: inherit;
    }
    .voice-mode-card small {
      display: block;
      margin-top: 0.35rem;
      font-size: 0.75rem;
      line-height: 1.35;
      color: rgb(156 163 175);
    }
    .voice-toggle-row {
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      min-height: 4.25rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.025);
      padding: 0.875rem;
    }
    .voice-toggle-compact {
      min-height: 0;
      flex: 1 1 18rem;
    }
    .voice-toggle-row input[type='checkbox'] {
      width: 1rem;
      height: 1rem;
      margin-top: 0.125rem;
      accent-color: rgb(34 211 238);
    }
    .voice-toggle-row strong {
      display: block;
      font-size: 0.875rem;
      color: rgb(243 244 246);
    }
    .voice-toggle-row small {
      display: block;
      margin-top: 0.25rem;
      font-size: 0.75rem;
      line-height: 1.35;
      color: rgb(156 163 175);
    }
    .knowledge-guide-panel {
      overflow: hidden;
      border-radius: 8px;
      border: 1px solid rgba(34,211,238,0.18);
      background:
        linear-gradient(180deg, rgba(34,211,238,0.045), rgba(255,255,255,0.015)),
        rgba(0,0,0,0.12);
    }
    .knowledge-guide-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      padding: 1rem;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .guide-badge {
      display: inline-flex;
      align-items: center;
      height: 2rem;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.045);
      padding: 0 0.75rem;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: rgb(209 213 219);
    }
    .guide-badge-published {
      border-color: rgba(52,211,153,0.28);
      background: rgba(16,185,129,0.10);
      color: rgb(167 243 208);
    }
    .guide-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
      min-height: 2rem;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.045);
      padding: 0.45rem 0.7rem;
      color: rgb(229 231 235);
      font-size: 0.75rem;
      font-weight: 600;
      transition: border-color 120ms, background 120ms, color 120ms;
    }
    .guide-button:hover:not(:disabled) {
      border-color: rgba(34,211,238,0.35);
      background: rgba(34,211,238,0.08);
      color: white;
    }
    .guide-button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .guide-button-good {
      border-color: rgba(52,211,153,0.22);
      background: rgba(16,185,129,0.10);
      color: rgb(187 247 208);
    }
    .guide-button-danger {
      border-color: rgba(248,113,113,0.22);
      background: rgba(239,68,68,0.08);
      color: rgb(254 202 202);
    }
    .knowledge-guide-current {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      padding: 1rem;
    }
    .guide-current-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 0.5rem;
      flex: 0 0 auto;
    }
    .knowledge-guide-empty {
      padding: 1rem;
      color: rgb(107 114 128);
      font-size: 0.8rem;
      line-height: 1.55;
    }
    .guide-history {
      border-top: 1px solid rgba(255,255,255,0.06);
      background: rgba(0,0,0,0.14);
    }
    .guide-history-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      border-top: 1px solid rgba(255,255,255,0.05);
    }
    .guide-history-row:first-child {
      border-top: 0;
    }
    .guide-editor {
      padding: 1rem;
      border-top: 1px solid rgba(255,255,255,0.06);
      background: rgba(0,0,0,0.18);
    }
    .guide-editor-bar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .guide-editor-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
      gap: 1rem;
      margin-top: 1rem;
    }
    .guide-markdown-field {
      min-height: 24rem;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 0.78rem;
      line-height: 1.55;
    }
    .guide-preview-body {
      min-height: 24rem;
      max-height: 38rem;
      overflow: auto;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(0,0,0,0.24);
      padding: 1rem;
      color: rgb(209 213 219);
    }
    .guide-preview-body h1 {
      margin: 0 0 0.75rem;
      color: white;
      font-size: 1.05rem;
      font-weight: 700;
    }
    .guide-preview-body h2 {
      margin: 1rem 0 0.5rem;
      color: rgb(165 243 252);
      font-size: 0.92rem;
      font-weight: 700;
    }
    .guide-preview-body h3 {
      margin: 0.75rem 0 0.35rem;
      color: rgb(224 242 254);
      font-size: 0.84rem;
      font-weight: 700;
    }
    .guide-preview-body p {
      margin: 0.35rem 0;
      font-size: 0.78rem;
      line-height: 1.55;
      color: rgb(156 163 175);
    }
    .guide-preview-li {
      padding-left: 0.4rem;
    }
    .guide-editor-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-top: 1rem;
    }
    .collection-option {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: stretch;
      gap: 0.5rem;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.025);
      padding: 0.5rem;
    }
    .collection-option-attached {
      border-color: rgba(34,211,238,0.24);
      background: rgba(34,211,238,0.06);
    }
    .collection-option-main {
      min-width: 0;
      text-align: left;
      color: rgb(229 231 235);
    }
    .collection-option-main span {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 0.78rem;
    }
    .collection-option-main small {
      display: block;
      margin-top: 0.2rem;
      color: rgb(107 114 128);
      font-size: 0.68rem;
    }
    .collection-option-main:hover:not(:disabled) span {
      color: white;
    }
    .collection-option-main:disabled {
      cursor: default;
      opacity: 0.78;
    }
    .collection-option-actions {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }
    .effective-source-note {
      border-radius: 8px;
      border: 1px solid rgba(34,211,238,0.18);
      background: rgba(34,211,238,0.055);
      padding: 0.75rem;
    }
    .effective-source-note strong {
      display: block;
      margin-top: 0.35rem;
      color: white;
      font-size: 0.875rem;
    }
    .effective-source-note small {
      display: block;
      margin-top: 0.2rem;
      color: rgb(148 163 184);
      font-size: 0.72rem;
      line-height: 1.35;
    }
    .table-profile-card {
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.10);
      background:
        linear-gradient(180deg, rgba(34,211,238,0.035), rgba(255,255,255,0.015)),
        rgba(0,0,0,0.12);
      padding: 1rem;
    }
    .table-profile-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .table-map-field {
      min-height: 7.5rem;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 0.78rem;
      line-height: 1.5;
    }
    @media (max-width: 900px) {
      .voice-mode-grid {
        grid-template-columns: 1fr;
      }
      .knowledge-guide-header,
      .knowledge-guide-current,
      .guide-history-row,
      .table-profile-head,
      .guide-editor-actions {
        flex-direction: column;
        align-items: stretch;
      }
      .guide-editor-grid {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class ChatKnowledgeSettingsComponent {
  private readonly api = inject(ApiService);
  protected readonly workspace = inject(WorkspaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly toastr = inject(ToastrService);
  private readonly destroyRef = inject(DestroyRef);
  private loadRequest: Subscription | null = null;
  private saveRequest: Subscription | null = null;
  private guideRequest: Subscription | null = null;
  private loadGeneration = 0;
  private saveGeneration = 0;
  private guideGeneration = 0;
  private unregisterContextReset: () => void = () => undefined;
  private destroyed = false;

  private readonly routeSlug = toSignal(
    this.route.parent!.paramMap.pipe(map((p) => p.get('slug') ?? null)),
    { initialValue: null as string | null },
  );

  readonly detail = signal<WorkspaceDetail | null>(null);
  readonly collections = signal<string[]>([]);
  readonly scopes = signal<KnowledgeScopeDraft[]>([]);
  readonly knowledgeGuides = signal<KnowledgeGuide[]>([]);
  readonly guideEditor = signal<KnowledgeGuideEditorDraft | null>(null);
  readonly guideHistoryScope = signal<string | null>(null);
  readonly guideSaving = signal(false);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly selectedAssistantProfileIndex = signal(0);

  readonly ragModes: RagMode[] = ['auto', 'naive', 'hybrid', 'hah', 'chah'];
  readonly voiceModeOptions: { value: VoiceLoopDefaultMode; label: string; icon: string; help: string }[] = [
    { value: 'batch', label: 'Batch', icon: 'mic', help: 'Push-to-talk voice turn.' },
    { value: 'session_loop', label: 'Conversation', icon: 'waves', help: 'Hands-free voice conversation.' },
    { value: 'realtime', label: 'Realtime', icon: 'radio', help: 'WebRTC lane when enabled.' },
  ];
  assistantProfileDefault = '';
  assistantProfilesJson = '[]';
  chatDraft: ChatSettingsDraft = {
    title: '',
    subtitle: '',
    placeholder: '',
    prompt_pack: [],
  };
  voiceLoopDraft: VoiceLoopSettingsDraft = this.defaultVoiceLoopDraft();
  voiceOutputDraft: VoiceOutputSettingsDraft = this.defaultVoiceOutputDraft();
  actionSettingsDraft: WorkspaceActionSettingsDraft = this.defaultActionSettingsDraft();
  tableIntelligenceDraft: TableIntelligenceSettingsDraft = this.defaultTableIntelligenceDraft();
  documentIntelligenceDraft: DocumentIntelligenceSettingsDraft = this.defaultDocumentIntelligenceDraft();

  readonly canEdit = computed(() => {
    const role = this.detail()?.role;
    const template = this.detail()?.role_template;
    return role === 'owner' || role === 'admin' || template === 'workspace_owner' || template === 'workspace_admin';
  });

  readonly assistantProfileOptions = computed(() => {
    return this.assistantProfiles()
      .map((profile) => typeof profile?.key === 'string' ? profile.key : '')
      .filter(Boolean);
  });

  readonly assistantProfiles = computed<AssistantProfileDraft[]>(() => {
    try {
      const parsed = JSON.parse(this.assistantProfilesJson || '[]');
      return Array.isArray(parsed) ? parsed.filter((profile) => this.asRecord(profile)) as AssistantProfileDraft[] : [];
    } catch {
      return [];
    }
  });

  readonly activeAssistantProfile = computed<AssistantProfileDraft | null>(() =>
    this.assistantProfiles().find((profile) => profile.key === this.assistantProfileDefault) ?? null,
  );

  readonly activeProfileDraft = computed<AssistantProfileDraft | null>(() =>
    this.assistantProfiles()[this.selectedAssistantProfileIndex()] ?? null,
  );

  readonly workspaceDefaultScope = computed(() =>
    this.scopes().find((scope) => scope.is_default)?.key || this.scopes()[0]?.key || null,
  );

  readonly workspaceDefaultScopeDraft = computed(() =>
    this.scopes().find((scope) => scope.is_default) || this.scopes()[0] || null,
  );

  readonly effectiveScopeKey = computed(() =>
    this.activeAssistantProfile()?.default_knowledge_scope || this.workspaceDefaultScope(),
  );

  readonly effectiveScopeLabel = computed(() => this.scopeLabel(this.effectiveScopeKey()));

  readonly effectiveScopeOrigin = computed(() => {
    const profile = this.activeAssistantProfile();
    if (profile?.default_knowledge_scope) {
      const label = profile.label || profile.key || 'default assistant profile';
      return `Selected by assistant profile "${label}", overriding the default context.`;
    }
    return 'Selected from the default context.';
  });

  tableProfileOptions(): TableProfileDraft[] {
    return this.tableIntelligenceDraft.profiles.filter((profile) => profile.key.trim());
  }

  documentProfileOptions(): DocumentProfileDraft[] {
    return this.documentIntelligenceDraft.profiles.filter((profile) => profile.key.trim());
  }

  readonly activeProfileChatOverrides = computed(() => {
    const profile = this.activeAssistantProfile();
    if (!profile) return false;
    const chat = this.asRecord(profile.chat);
    return Boolean(
      this.str(chat['title'])
      || this.str(chat['subtitle'])
      || this.str(chat['placeholder'])
      || this.promptPackDraft(chat['prompt_pack']).length,
    );
  });

  readonly effectiveChatTitle = computed(() => {
    const configured = this.str(this.effectiveChatConfig()['title']);
    if (configured) return configured;
    const profile = this.activeAssistantProfile();
    if (profile?.label) return `Interroger ${profile.label}`;
    return 'Posez votre question';
  });

  readonly effectiveChatSubtitle = computed(() => {
    const configured = this.str(this.effectiveChatConfig()['subtitle']);
    if (configured) return configured;
    const scope = this.effectiveScopeLabel();
    return scope && scope !== 'workspace'
      ? `Posez une question sur le contexte ${scope}.`
      : 'Posez une question sur le contexte du workspace. La réponse cite les sources utilisées.';
  });

  readonly effectiveChatPlaceholder = computed(() => {
    const configured = this.str(this.effectiveChatConfig()['placeholder']);
    if (configured) return configured;
    return 'Posez votre question...';
  });

  readonly effectivePromptCards = computed<PromptCardDraft[]>(() => {
    const config = this.effectiveChatConfig();
    const activeScope = this.effectiveScopeKey();
    const byScope = this.asRecord(config['prompt_pack_by_scope']);
    const scopedPack = activeScope ? this.promptPackDraft(byScope[activeScope]) : [];
    if (scopedPack.length) return scopedPack.slice(0, 4);
    const workspacePack = this.promptPackDraft(config['prompt_pack']).filter((card) => {
      return !card.scope_key || !activeScope || card.scope_key === activeScope;
    });
    if (workspacePack.length) return workspacePack.slice(0, 4);
    return this.generatedKnowledgePrompts(this.effectiveScopeLabel());
  });

  constructor() {
    this.unregisterContextReset = this.workspace.registerContextReset(() => {
      this.resetWorkspaceContext();
    });
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      this.unregisterContextReset();
      this.cancelLoad();
      this.cancelSave();
      this.cancelGuide();
    });
    effect(() => {
      const slug = this.routeSlug();
      if (slug) this.load();
    });
  }

  load(): void {
    const slug = this.routeSlug();
    const scope = this.workspace.captureRequestScope();
    if (!slug || !scope.workspaceSlug || slug !== scope.workspaceSlug) return;

    this.cancelLoad();
    const generation = ++this.loadGeneration;
    this.error.set(null);
    const request = forkJoin({
      workspace: this.workspace.getWorkspace(slug, { workspaceSlug: scope.workspaceSlug }),
      scopes: this.api.get<{ scopes: KnowledgeScopeApi[] }>(
        '/knowledge/scopes',
        undefined,
        { workspaceSlug: scope.workspaceSlug },
      ),
      collections: this.api.get<{ collections: string[] }>(
        '/documents/collections',
        undefined,
        { workspaceSlug: scope.workspaceSlug },
      ),
      guides: this.api.listKnowledgeGuides(
        { current_only: false },
        { workspaceSlug: scope.workspaceSlug },
      ),
    }).subscribe({
      next: ({ workspace, scopes, collections, guides }) => {
        if (!this.isLoadCurrent(scope, generation)) return;
        this.detail.set(workspace);
        this.hydrateSettings(workspace);
        this.scopes.set((scopes.scopes || []).map((scope) => this.scopeToDraft(scope)));
        if (this.scopes().length === 0) this.addScope();
        this.collections.set([...(collections.collections || [])].sort((a, b) => a.localeCompare(b)));
        this.knowledgeGuides.set(guides.items || []);
      },
      error: () => {
        if (!this.isLoadCurrent(scope, generation)) return;
        this.loadRequest = null;
        this.error.set('Unable to load workspace chat and Knowledge settings.');
      },
      complete: () => {
        if (generation === this.loadGeneration) this.loadRequest = null;
      },
    });
    this.loadRequest = request.closed ? null : request;
  }

  addScope(): void {
    const next = [...this.scopes()];
    next.push({
      key: `scope_${next.length + 1}`,
      label: `Scope ${next.length + 1}`,
      description: '',
      collection_slugs_text: this.collections()[0] || '',
      default_mode: 'chah',
      top_k: 5,
      is_default: next.length === 0,
      table_profile_key: '',
      document_profile_key: '',
    });
    this.scopes.set(next);
  }

  removeScope(index: number): void {
    const next = this.scopes().filter((_, i) => i !== index);
    if (next.length && !next.some((scope) => scope.is_default)) next[0].is_default = true;
    this.scopes.set(next);
  }

  setDefaultScope(index: number): void {
    this.scopes.set(this.scopes().map((scope, i) => ({ ...scope, is_default: i === index })));
  }

  addPrompt(): void {
    this.chatDraft.prompt_pack = [
      ...this.chatDraft.prompt_pack,
      {
        icon: 'search',
        label: 'Poser une question',
        prompt: 'Que disent les documents sélectionnés sur [votre sujet] ? Cite les sources utilisées.',
        scope_key: '',
        context_mode: 'any',
      },
    ];
  }

  removePrompt(index: number): void {
    this.chatDraft.prompt_pack = this.chatDraft.prompt_pack.filter((_, i) => i !== index);
  }

  copyEffectiveChatToWorkspace(): void {
    this.chatDraft = {
      title: this.effectiveChatTitle(),
      subtitle: this.effectiveChatSubtitle(),
      placeholder: this.effectiveChatPlaceholder(),
      prompt_pack: this.effectivePromptCards().map((prompt) => ({ ...prompt })),
    };
    this.toastr.info('Preview copied into editable chat defaults', 'Workspace');
  }

  copyCollection(collection: string): void {
    void navigator.clipboard?.writeText(collection);
    this.toastr.info(collection, 'Collection slug copied');
  }

  addCollectionToDefaultScope(collection: string): void {
    const slug = collection.trim();
    if (!slug || !this.canEdit()) return;
    const next = [...this.scopes()];
    let index = next.findIndex((scope) => scope.is_default);
    if (index < 0) index = 0;
    if (index < 0) {
      next.push({
        key: 'workspace_default',
        label: 'Default context',
        description: '',
        collection_slugs_text: slug,
        default_mode: 'chah',
        top_k: 5,
        is_default: true,
        table_profile_key: '',
        document_profile_key: '',
      });
    } else {
      const current = next[index];
      const slugs = this.collectionSlugs(current);
      if (slugs.includes(slug)) {
        this.toastr.info(slug, 'Already in default context');
        return;
      }
      next[index] = { ...current, collection_slugs_text: [...slugs, slug].join(', ') };
    }
    this.scopes.set(next);
    this.toastr.success('Save defaults to apply this routing change.', 'Added to default context');
  }

  collectionInDefaultScope(collection: string): boolean {
    const scope = this.workspaceDefaultScopeDraft();
    return !!scope && this.collectionSlugs(scope).includes(collection.trim());
  }

  currentGuideForScope(scopeKey: string): KnowledgeGuide | null {
    return this.guideVersionsForScope(scopeKey).find((guide) => guide.is_current) ?? null;
  }

  guideVersionsForScope(scopeKey: string): KnowledgeGuide[] {
    return this.knowledgeGuides()
      .filter((guide) => guide.target_type === 'scope' && guide.target_ref === scopeKey)
      .sort((a, b) => (b.version || 0) - (a.version || 0));
  }

  toggleGuideHistory(scopeKey: string): void {
    this.guideHistoryScope.set(this.guideHistoryScope() === scopeKey ? null : scopeKey);
  }

  openGuideEditor(scopeKey: string, guide?: KnowledgeGuide, mode: 'create' | 'edit' | 'restore' = 'edit'): void {
    const scope = this.scopes().find((item) => item.key === scopeKey);
    const label = scope?.label || scopeKey;
    if (guide) {
      this.guideEditor.set({
        scope_key: scopeKey,
        guide_key: guide.guide_key,
        mode,
        title: guide.title || `${label} Knowledge Guide`,
        markdown: guide.markdown || '',
        status: guide.status || 'draft',
        source_version: mode === 'restore' ? guide.version : undefined,
      });
      return;
    }

    this.guideEditor.set({
      scope_key: scopeKey,
      mode: 'create',
      title: `${label} Knowledge Guide`,
      markdown: this.defaultGuideMarkdown(label),
      status: 'draft',
    });
  }

  closeGuideEditor(): void {
    this.guideEditor.set(null);
  }

  updateGuideEditor(field: 'title' | 'markdown' | 'status', value: string): void {
    const editor = this.guideEditor();
    if (!editor) return;
    const next: KnowledgeGuideEditorDraft = { ...editor };
    if (field === 'status') {
      next.status = value === 'published' || value === 'archived' ? value : 'draft';
    } else {
      next[field] = value;
    }
    this.guideEditor.set(next);
  }

  saveGuide(status?: KnowledgeGuideStatus): void {
    const editor = this.guideEditor();
    if (!editor || !this.canEdit()) return;
    const scope = this.captureCurrentRouteScope();
    if (!scope) return;
    const title = editor.title.trim();
    const markdown = editor.markdown.trim();
    if (!title || !markdown) {
      this.error.set('Knowledge guide needs a title and Markdown content.');
      return;
    }
    const payload = {
      target_type: 'scope' as const,
      target_ref: editor.scope_key,
      title,
      markdown,
      status: status || editor.status,
    };
    this.cancelGuide();
    const generation = ++this.guideGeneration;
    const operation = new Subscription();
    this.guideRequest = operation;
    this.guideSaving.set(true);
    this.error.set(null);
    const request = editor.guide_key
      ? this.api.updateKnowledgeGuide(
          editor.guide_key,
          payload,
          { workspaceSlug: scope.workspaceSlug },
        )
      : this.api.createKnowledgeGuide(payload, { workspaceSlug: scope.workspaceSlug });
    operation.add(
      request.subscribe({
        next: () => {
          if (!this.isGuideCurrent(scope, generation, operation)) return;
          this.guideSaving.set(false);
          this.guideEditor.set(null);
          this.toastr.success(payload.status === 'published' ? 'Guide published' : 'Guide saved', 'Knowledge guide');
          this.loadKnowledgeGuides(scope, generation, operation);
        },
        error: (err) => {
          if (!this.isGuideCurrent(scope, generation, operation)) return;
          this.guideSaving.set(false);
          this.error.set(err?.error?.detail || 'Unable to save Knowledge guide.');
          this.finishGuide(operation, generation);
        },
      }),
    );
  }

  publishGuide(guide: KnowledgeGuide): void {
    if (!this.canEdit()) return;
    this.patchGuideStatus(guide, 'published');
  }

  archiveGuide(guide: KnowledgeGuide): void {
    if (!this.canEdit()) return;
    this.patchGuideStatus(guide, 'archived');
  }

  formatDate(value?: string | null): string {
    if (!value) return 'no date';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  }

  markdownPreviewLines(markdown: string): string[] {
    return (markdown || '').split('\n').slice(0, 80);
  }

  markdownLineKind(line: string): 'h1' | 'h2' | 'h3' | 'li' | 'p' {
    const trimmed = line.trim();
    if (trimmed.startsWith('# ')) return 'h1';
    if (trimmed.startsWith('## ')) return 'h2';
    if (trimmed.startsWith('### ')) return 'h3';
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) return 'li';
    return 'p';
  }

  cleanMarkdownLine(line: string): string {
    return line
      .trim()
      .replace(/^###\s+/, '')
      .replace(/^##\s+/, '')
      .replace(/^#\s+/, '')
      .replace(/^[-*]\s+/, '• ');
  }

  addAssistantProfile(): void {
    const profiles = this.parseAssistantProfilesForEdit();
    const index = profiles.length + 1;
    profiles.push({
      key: `assistant_${index}`,
      label: `Assistant ${index}`,
      subtitle: '',
      default_knowledge_scope: this.workspaceDefaultScope() || '',
      design_mode: 'agentium',
      tone: 'technical',
      chat: {},
      voice_loop: {},
    });
    this.writeAssistantProfiles(profiles);
    this.selectedAssistantProfileIndex.set(profiles.length - 1);
  }

  removeAssistantProfile(index: number): void {
    const profiles = this.parseAssistantProfilesForEdit();
    if (index < 0 || index >= profiles.length) return;
    const removed = profiles[index]?.key;
    profiles.splice(index, 1);
    if (removed && this.assistantProfileDefault === removed) {
      this.assistantProfileDefault = profiles[0]?.key || '';
    }
    this.writeAssistantProfiles(profiles);
    this.selectedAssistantProfileIndex.set(Math.max(0, Math.min(index, profiles.length - 1)));
  }

  updateAssistantProfileField(field: keyof AssistantProfileDraft, value: unknown): void {
    this.mutateSelectedAssistantProfile((profile) => {
      const draft = profile as unknown as Record<string, unknown>;
      if (typeof value === 'string') {
        const trimmed = value.trim();
        if (trimmed) draft[field] = trimmed;
        else delete draft[field];
      } else {
        draft[field] = value;
      }
    });
  }

  profileChatField(field: string): string {
    return this.str(this.asRecord(this.activeProfileDraft()?.chat)[field]);
  }

  updateAssistantProfileChatField(field: string, value: string): void {
    this.mutateSelectedAssistantProfile((profile) => {
      const chat = { ...this.asRecord(profile.chat) };
      this.setOrDelete(chat, field, value);
      if (Object.keys(chat).length) profile.chat = chat;
      else delete profile.chat;
    });
  }

  copyWorkspaceChatToProfile(): void {
    this.mutateSelectedAssistantProfile((profile) => {
      profile.chat = this.cleanChatSettings(this.asRecord(profile.chat));
    });
    this.toastr.info('Workspace chat defaults copied into selected profile', 'Assistant profile');
  }

  profileVoiceField(field: string): string {
    const value = this.asRecord(this.activeProfileDraft()?.voice_loop)[field];
    return typeof value === 'string' ? value : '';
  }

  profileVoiceListField(field: string): string {
    return this.listToCsv(this.asRecord(this.activeProfileDraft()?.voice_loop)[field]);
  }

  updateAssistantProfileVoiceField(field: string, value: string): void {
    this.mutateSelectedAssistantProfile((profile) => {
      const voice = { ...this.asRecord(profile.voice_loop) };
      this.setOrDelete(voice, field, value);
      if (Object.keys(voice).length) profile.voice_loop = voice;
      else delete profile.voice_loop;
    });
  }

  updateAssistantProfileVoiceListField(field: string, value: string): void {
    this.mutateSelectedAssistantProfile((profile) => {
      const voice = { ...this.asRecord(profile.voice_loop) };
      const list = this.csvToList(value);
      if (list.length) voice[field] = list;
      else delete voice[field];
      if (Object.keys(voice).length) profile.voice_loop = voice;
      else delete profile.voice_loop;
    });
  }

  saveAll(): void {
    const detail = this.detail();
    if (!detail) return;
    const scope = this.workspace.captureRequestScope();
    if (!scope.workspaceSlug || detail.slug !== scope.workspaceSlug) {
      this.error.set('Workspace changed before save. Reload these settings and try again.');
      return;
    }
    const scopePayload = this.toScopePayload();
    if (!scopePayload) return;

    let assistantProfiles: unknown;
    try {
      assistantProfiles = JSON.parse(this.assistantProfilesJson || '[]');
      if (!Array.isArray(assistantProfiles)) throw new Error('assistant_profiles must be an array');
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Invalid assistant_profiles JSON.');
      return;
    }

    const settings = { ...(detail.settings || {}) };
    settings['knowledge_scopes'] = scopePayload;
    settings['chat'] = this.cleanChatSettings(this.asRecord(settings['chat']));
    settings['voice_loop'] = this.cleanVoiceLoopSettings();
    settings['voice_output'] = this.cleanVoiceOutputSettings();
    settings['actions'] = this.cleanActionSettings();
    const tableIntelligence = this.cleanTableIntelligenceSettings();
    if (!tableIntelligence) return;
    settings['table_intelligence'] = tableIntelligence;
    const documentIntelligence = this.cleanDocumentIntelligenceSettings();
    if (!documentIntelligence) return;
    settings['document_intelligence'] = documentIntelligence;
    settings['assistant_profile_default'] = this.assistantProfileDefault || null;
    settings['assistant_profiles'] = assistantProfiles;

    this.cancelSave();
    const generation = ++this.saveGeneration;
    const request = new Subscription();
    this.saveRequest = request;
    this.saving.set(true);
    this.error.set(null);
    request.add(
      this.api.patch(
        '/knowledge/scopes',
        { scopes: scopePayload },
        { workspaceSlug: scope.workspaceSlug },
      ).subscribe({
        next: () => {
          if (!this.isSaveCurrent(scope, generation, request)) return;
          request.add(
            this.workspace.updateWorkspaceSettings(
              detail.slug,
              settings,
              { workspaceSlug: scope.workspaceSlug },
            ).subscribe({
              next: (workspace) => {
                if (!this.isSaveCurrent(scope, generation, request)) return;
                this.saving.set(false);
                this.detail.set(workspace);
                this.toastr.success('Chat and source defaults saved', 'Workspace');
                this.finishSave(request, generation);
                // Reload the authoritative scopes/settings just as before. The
                // load owns its own A scope and is cancelled by the same reset.
                this.load();
              },
              error: (err) => {
                if (!this.isSaveCurrent(scope, generation, request)) return;
                this.saving.set(false);
                this.error.set(err?.error?.detail || 'Source scopes saved, but chat defaults could not be saved.');
                this.finishSave(request, generation);
              },
            }),
          );
        },
        error: (err) => {
          if (!this.isSaveCurrent(scope, generation, request)) return;
          this.saving.set(false);
          this.error.set(err?.error?.detail || 'Unable to save source scopes.');
          this.finishSave(request, generation);
        },
      }),
    );
  }

  private isLoadCurrent(scope: WorkspaceRequestScope, generation: number): boolean {
    return (
      !this.destroyed
      && generation === this.loadGeneration
      && this.routeSlug() === scope.workspaceSlug
      && this.workspace.isRequestScopeCurrent(scope)
    );
  }

  private isSaveCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
    request: Subscription,
  ): boolean {
    return (
      !this.destroyed
      && !request.closed
      && this.saveRequest === request
      && generation === this.saveGeneration
      && this.workspace.isRequestScopeCurrent(scope)
    );
  }

  private finishSave(request: Subscription, generation: number): void {
    if (this.saveRequest === request && generation === this.saveGeneration) {
      this.saveRequest = null;
    }
    request.unsubscribe();
  }

  private cancelLoad(): void {
    this.loadGeneration += 1;
    this.loadRequest?.unsubscribe();
    this.loadRequest = null;
  }

  private cancelSave(): void {
    this.saveGeneration += 1;
    this.saveRequest?.unsubscribe();
    this.saveRequest = null;
    this.saving.set(false);
  }

  private cancelGuide(): void {
    this.guideGeneration += 1;
    this.guideRequest?.unsubscribe();
    this.guideRequest = null;
    this.guideSaving.set(false);
  }

  private resetWorkspaceContext(): void {
    this.cancelLoad();
    this.cancelSave();
    this.cancelGuide();
    this.detail.set(null);
    this.collections.set([]);
    this.scopes.set([]);
    this.knowledgeGuides.set([]);
    this.guideEditor.set(null);
    this.guideHistoryScope.set(null);
    this.error.set(null);
  }

  private loadKnowledgeGuides(
    scope: WorkspaceRequestScope,
    generation: number,
    operation: Subscription,
  ): void {
    operation.add(
      this.api.listKnowledgeGuides(
        { current_only: false },
        { workspaceSlug: scope.workspaceSlug },
      ).subscribe({
        next: (guides) => {
          if (!this.isGuideCurrent(scope, generation, operation)) return;
          this.knowledgeGuides.set(guides.items || []);
        },
        error: () => {
          if (!this.isGuideCurrent(scope, generation, operation)) return;
          this.toastr.warning('Knowledge guides could not be refreshed.', 'Workspace');
          this.finishGuide(operation, generation);
        },
        complete: () => this.finishGuide(operation, generation),
      }),
    );
  }

  private patchGuideStatus(guide: KnowledgeGuide, status: KnowledgeGuideStatus): void {
    const scope = this.captureCurrentRouteScope();
    if (!scope) return;
    this.cancelGuide();
    const generation = ++this.guideGeneration;
    const operation = new Subscription();
    this.guideRequest = operation;
    this.guideSaving.set(true);
    this.error.set(null);
    operation.add(
      this.api.updateKnowledgeGuide(guide.guide_key, {
        target_type: guide.target_type,
        target_ref: guide.target_ref,
        title: guide.title,
        markdown: guide.markdown || '',
        status,
      }, { workspaceSlug: scope.workspaceSlug }).subscribe({
        next: () => {
          if (!this.isGuideCurrent(scope, generation, operation)) return;
          this.guideSaving.set(false);
          this.toastr.success(status === 'published' ? 'Guide published' : 'Guide archived', 'Knowledge guide');
          this.loadKnowledgeGuides(scope, generation, operation);
        },
        error: (err) => {
          if (!this.isGuideCurrent(scope, generation, operation)) return;
          this.guideSaving.set(false);
          this.error.set(err?.error?.detail || 'Unable to update Knowledge guide.');
          this.finishGuide(operation, generation);
        },
      }),
    );
  }

  private captureCurrentRouteScope(): WorkspaceRequestScope | null {
    const scope = this.workspace.captureRequestScope();
    if (!scope.workspaceSlug || this.routeSlug() !== scope.workspaceSlug) {
      this.error.set('Workspace changed. Reload these settings and try again.');
      return null;
    }
    return scope;
  }

  private isGuideCurrent(
    scope: WorkspaceRequestScope,
    generation: number,
    operation: Subscription,
  ): boolean {
    return (
      !this.destroyed
      && !operation.closed
      && this.guideRequest === operation
      && generation === this.guideGeneration
      && this.routeSlug() === scope.workspaceSlug
      && this.workspace.isRequestScopeCurrent(scope)
    );
  }

  private finishGuide(operation: Subscription, generation: number): void {
    if (this.guideRequest === operation && generation === this.guideGeneration) {
      this.guideRequest = null;
    }
    operation.unsubscribe();
  }

  private defaultGuideMarkdown(label: string): string {
    return [
      `# ${label} Knowledge Guide`,
      '',
      '## Purpose',
      'Describe how this Knowledge scope should be interpreted during retrieval and answer generation.',
      '',
      '## Vocabulary and aliases',
      '- Add domain terms, abbreviations and common synonyms that help query expansion.',
      '',
      '## Interpretation rules',
      '- Explain how to read recurring tables, labels, units or business conventions.',
      '- Keep uncertain conventions explicit; do not invent values that are absent from source documents.',
      '',
      '## Evidence policy',
      '- Prefer answers with citations to raw documents.',
      '- If the guide clarifies vocabulary but the source document is not enough to answer, say so clearly.',
    ].join('\n');
  }

  private hydrateSettings(workspace: WorkspaceDetail): void {
    const settings = workspace.settings || {};
    const chat = this.asRecord(settings['chat']);
    this.chatDraft = {
      title: this.str(chat['title']),
      subtitle: this.str(chat['subtitle']),
      placeholder: this.str(chat['placeholder']),
      prompt_pack: this.promptPackDraft(chat['prompt_pack']),
    };
    this.voiceLoopDraft = this.voiceLoopToDraft(settings['voice_loop']);
    this.voiceOutputDraft = this.voiceOutputToDraft(settings['voice_output']);
    this.actionSettingsDraft = this.actionSettingsToDraft(settings['actions']);
    this.tableIntelligenceDraft = this.tableIntelligenceToDraft(settings['table_intelligence']);
    this.documentIntelligenceDraft = this.documentIntelligenceToDraft(settings['document_intelligence']);
    this.assistantProfileDefault = this.str(settings['assistant_profile_default']);
    this.assistantProfilesJson = JSON.stringify(Array.isArray(settings['assistant_profiles']) ? settings['assistant_profiles'] : [], null, 2);
    this.selectedAssistantProfileIndex.set(0);
  }

  private scopeToDraft(scope: KnowledgeScopeApi): KnowledgeScopeDraft {
    return {
      key: scope.key,
      label: scope.label || scope.key,
      description: scope.description || '',
      collection_slugs_text: (scope.collection_slugs || []).join(', '),
      default_mode: scope.default_mode || 'auto',
      top_k: scope.top_k || null,
      is_default: !!scope.is_default,
      table_profile_key: scope.table_profile_key || '',
      document_profile_key: scope.document_profile_key || '',
    };
  }

  private toScopePayload(): KnowledgeScopeApi[] | null {
    const payload = this.scopes().map((scope) => {
      const collections = scope.collection_slugs_text
        .split(',')
        .map((slug) => slug.trim())
        .filter(Boolean);
      return {
        key: scope.key.trim(),
        label: scope.label.trim(),
        description: scope.description.trim(),
        collection_slugs: collections,
        default_mode: scope.default_mode || 'auto',
        top_k: scope.top_k ? Number(scope.top_k) : null,
        is_default: !!scope.is_default,
        table_profile_key: scope.table_profile_key?.trim() || null,
        document_profile_key: scope.document_profile_key?.trim() || null,
      };
    });

    if (payload.some((scope) => !scope.key || scope.collection_slugs.length === 0)) {
      this.error.set('Each Knowledge scope needs a key and at least one collection slug.');
      return null;
    }
    if (new Set(payload.map((scope) => scope.key)).size !== payload.length) {
      this.error.set('Knowledge scope keys must be unique.');
      return null;
    }
    if (!payload.some((scope) => scope.is_default)) payload[0].is_default = true;
    return payload;
  }

  private cleanChatSettings(base: Record<string, unknown> = {}): Record<string, unknown> {
    const chat: Record<string, unknown> = { ...base };
    this.setOrDelete(chat, 'title', this.chatDraft.title);
    this.setOrDelete(chat, 'subtitle', this.chatDraft.subtitle);
    this.setOrDelete(chat, 'placeholder', this.chatDraft.placeholder);
    const prompts = this.chatDraft.prompt_pack
      .map((prompt) => ({
        icon: prompt.icon.trim() || 'sparkles',
        label: prompt.label.trim(),
        prompt: prompt.prompt.trim(),
        scope_key: prompt.scope_key || undefined,
        context_mode: prompt.context_mode && prompt.context_mode !== 'any' ? prompt.context_mode : undefined,
      }))
      .filter((prompt) => prompt.label && prompt.prompt);
    if (prompts.length) chat['prompt_pack'] = prompts;
    else delete chat['prompt_pack'];
    return chat;
  }

  private cleanTableIntelligenceSettings(): Record<string, unknown> | null {
    const profiles = this.tableIntelligenceDraft.profiles.map((profile) => ({
      key: profile.key.trim(),
      label: profile.label.trim() || profile.key.trim(),
      description: profile.description.trim(),
      synonyms: this.mapTextToRecord(profile.synonyms_text),
      metric_aliases: this.mapTextToRecord(profile.metric_aliases_text),
      aggregation_policy: {
        allow_mean: !!profile.allow_mean,
        require_compatible_units: !!profile.require_compatible_units,
        exclude_non_numeric: !!profile.exclude_non_numeric,
      },
      ambiguity_policy: profile.ambiguity_policy || 'ask_when_metric_unclear',
      evidence_policy: {
        require_cell_citations: !!profile.require_cell_citations,
        show_excluded_values: !!profile.show_excluded_values,
      },
    })).filter((profile) => profile.key);

    if (new Set(profiles.map((profile) => profile.key)).size !== profiles.length) {
      this.error.set('Table Intelligence profile keys must be unique.');
      return null;
    }
    const defaultProfile = this.tableIntelligenceDraft.default_profile.trim();
    if (defaultProfile && !profiles.some((profile) => profile.key === defaultProfile)) {
      this.error.set('The default Table Intelligence profile must exist in the profile list.');
      return null;
    }
    return {
      default_profile: defaultProfile || null,
      profiles,
    };
  }

  private cleanDocumentIntelligenceSettings(): Record<string, unknown> | null {
    const profiles = this.documentIntelligenceDraft.profiles.map((profile) => ({
      key: profile.key.trim(),
      label: profile.label.trim() || profile.key.trim(),
      description: profile.description.trim(),
      synonyms: this.mapTextToRecord(profile.synonyms_text),
      max_candidate_facts: this.clampNumber(profile.max_candidate_facts, 5000, 100, 20000),
      max_evidence_rows: this.clampNumber(profile.max_evidence_rows, 24, 3, 100),
    })).filter((profile) => profile.key);

    if (new Set(profiles.map((profile) => profile.key)).size !== profiles.length) {
      this.error.set('Document Intelligence profile keys must be unique.');
      return null;
    }
    const defaultProfile = this.documentIntelligenceDraft.default_profile.trim();
    if (defaultProfile && !profiles.some((profile) => profile.key === defaultProfile)) {
      this.error.set('The default Document Intelligence profile must exist in the profile list.');
      return null;
    }
    const ocr = this.documentIntelligenceDraft.ocr;
    return {
      default_profile: defaultProfile || null,
      profiles,
      ocr: {
        enabled: !!ocr.enabled,
        provider_priority: this.csvToList(ocr.provider_priority_text),
        ppocr_endpoint_url: ocr.ppocr_endpoint_url.trim() || null,
        languages: this.csvToList(ocr.languages_text),
        scan_detection: !!ocr.scan_detection,
        force_ocr: !!ocr.force_ocr,
        min_text_chars_for_native_pdf: this.clampNumber(ocr.min_native_pdf_chars, 80, 0, 5000),
        min_confidence: this.clampFloat(ocr.min_confidence, 0, 0, 1),
        timeout_seconds: this.clampNumber(ocr.timeout_seconds, 30, 1, 180),
        retries: this.clampNumber(ocr.retries, 2, 0, 5),
        required: !!ocr.required,
        openai_vision_enabled: !!ocr.openai_vision_enabled,
        openai_model: ocr.openai_model.trim() || 'gpt-4o-mini',
        openai_detail: ocr.openai_detail || 'low',
        openai_max_image_bytes: this.clampNumber(ocr.openai_max_image_bytes, 5_000_000, 100_000, 50_000_000),
        openai_enrich_min_chars: this.clampNumber(ocr.openai_enrich_min_chars, 24, 0, 1000),
        openai_enrich_min_confidence: this.clampFloat(ocr.openai_enrich_min_confidence, 0.45, 0, 1),
      },
    };
  }

  private cleanVoiceLoopSettings(): Record<string, unknown> {
    return {
      default_mode: this.voiceLoopDraft.default_mode,
      capture_mode: this.voiceLoopDraft.capture_mode || 'normal',
      auto_capture_mode_enabled: !!this.voiceLoopDraft.auto_capture_mode_enabled,
      enabled_default: this.voiceLoopDraft.default_mode === 'session_loop',
      auto_send_final_transcript: !!this.voiceLoopDraft.auto_send_final_transcript,
      auto_endpoint: !!this.voiceLoopDraft.auto_endpoint,
      auto_rearm_after_tts: !!this.voiceLoopDraft.auto_rearm_after_tts,
      barge_in: !!this.voiceLoopDraft.barge_in,
      commands_enabled: !!this.voiceLoopDraft.commands_enabled,
      trigger_word: this.voiceLoopDraft.trigger_word.trim() || null,
      command_packs: this.csvToList(this.voiceLoopDraft.command_packs_text),
      stop_phrases: this.csvToList(this.voiceLoopDraft.stop_phrases_text),
      silence_ms: this.clampNumber(this.voiceLoopDraft.silence_ms, 1200, 300, 5000),
      dictation_silence_ms: this.clampNumber(this.voiceLoopDraft.dictation_silence_ms, 2000, 300, 30000),
      min_speech_ms: this.clampNumber(this.voiceLoopDraft.min_speech_ms, 350, 100, 3000),
      dictation_min_speech_ms: this.clampNumber(this.voiceLoopDraft.dictation_min_speech_ms, 300, 100, 3000),
      max_turn_ms: this.clampNumber(this.voiceLoopDraft.max_turn_ms, 45000, 5000, 180000),
      cooldown_ms: this.clampNumber(this.voiceLoopDraft.cooldown_ms, 500, 0, 5000),
      rms_threshold: this.clampFloat(this.voiceLoopDraft.rms_threshold, 0.018, 0.001, 0.15),
      endpoint_grace_ms: this.clampNumber(this.voiceLoopDraft.endpoint_grace_ms, 0, 0, 3000),
      vad_hangover_ms: this.clampNumber(this.voiceLoopDraft.vad_hangover_ms, 0, 0, 2000),
      vad_calibration_ms: this.clampNumber(this.voiceLoopDraft.vad_calibration_ms, 300, 0, 3000),
      vad_min_silence_frames_ms: this.clampNumber(this.voiceLoopDraft.vad_min_silence_frames_ms, 0, 0, 2000),
    };
  }

  private cleanVoiceOutputSettings(): Record<string, unknown> {
    return {
      latency_profile: this.voiceOutputDraft.latency_profile,
      voice: this.voiceOutputDraft.voice.trim() || 'nova',
      flush_first_chars: this.clampNumber(this.voiceOutputDraft.flush_first_chars, 24, 12, 240),
      flush_next_chars: this.clampNumber(this.voiceOutputDraft.flush_next_chars, 80, 40, 600),
      flush_timeout_ms: this.clampNumber(this.voiceOutputDraft.flush_timeout_ms, 900, 250, 5000),
      interrupt_on_user_speech: !!this.voiceOutputDraft.interrupt_on_user_speech,
    };
  }

  private cleanActionSettings(): Record<string, unknown> {
    const actions: Record<string, unknown> = {};
    const enabledPacks = this.csvToList(this.actionSettingsDraft.enabled_packs_text);
    const hiddenPacks = this.csvToList(this.actionSettingsDraft.hidden_packs_text);
    const enabledActions = this.csvToList(this.actionSettingsDraft.enabled_actions_text);
    const hiddenActions = this.csvToList(this.actionSettingsDraft.hidden_actions_text);
    if (enabledPacks.length) actions['enabled_packs'] = enabledPacks;
    if (hiddenPacks.length) actions['hidden_packs'] = hiddenPacks;
    if (enabledActions.length) actions['enabled_actions'] = enabledActions;
    if (hiddenActions.length) actions['hidden_actions'] = hiddenActions;
    return actions;
  }

  private parseAssistantProfilesForEdit(): AssistantProfileDraft[] {
    try {
      const parsed = JSON.parse(this.assistantProfilesJson || '[]');
      return Array.isArray(parsed)
        ? parsed
            .filter((profile) => this.asRecord(profile))
            .map((profile) => ({ ...(profile as AssistantProfileDraft) }))
        : [];
    } catch {
      return [];
    }
  }

  private writeAssistantProfiles(profiles: AssistantProfileDraft[]): void {
    this.assistantProfilesJson = JSON.stringify(profiles, null, 2);
  }

  private mutateSelectedAssistantProfile(mutator: (profile: AssistantProfileDraft) => void): void {
    const profiles = this.parseAssistantProfilesForEdit();
    const index = this.selectedAssistantProfileIndex();
    if (!profiles[index]) return;
    mutator(profiles[index]);
    this.writeAssistantProfiles(profiles);
  }

  private voiceLoopToDraft(value: unknown): VoiceLoopSettingsDraft {
    const config = this.asRecord(value);
    const mode = config['default_mode'] === 'session_loop' || config['default_mode'] === 'realtime'
      ? config['default_mode'] as VoiceLoopDefaultMode
      : config['enabled_default'] === true
        ? 'session_loop'
        : 'batch';
    return {
      default_mode: mode,
      capture_mode: config['capture_mode'] === 'robust' || config['capture_mode'] === 'manual_safe'
        ? config['capture_mode'] as VoiceCaptureMode
        : 'normal',
      auto_capture_mode_enabled: config['auto_capture_mode_enabled'] === true,
      auto_send_final_transcript: config['auto_send_final_transcript'] === true,
      auto_endpoint: config['auto_endpoint'] !== false,
      auto_rearm_after_tts: config['auto_rearm_after_tts'] !== false,
      barge_in: config['barge_in'] !== false,
      commands_enabled: config['commands_enabled'] !== false,
      trigger_word: this.str(config['trigger_word']),
      command_packs_text: this.listToCsv(config['command_packs']) || 'generic, fr_basic',
      stop_phrases_text: this.listToCsv(config['stop_phrases']) || "on peut s'arrêter là, ça suffit, fin de session",
      silence_ms: this.num(config['silence_ms'], 1200),
      dictation_silence_ms: this.num(config['dictation_silence_ms'], 2000),
      min_speech_ms: this.num(config['min_speech_ms'], 350),
      dictation_min_speech_ms: this.num(config['dictation_min_speech_ms'], 300),
      max_turn_ms: this.num(config['max_turn_ms'], 45000),
      cooldown_ms: this.num(config['cooldown_ms'], 500),
      rms_threshold: this.num(config['rms_threshold'], 0.018),
      endpoint_grace_ms: this.num(config['endpoint_grace_ms'], 0),
      vad_hangover_ms: this.num(config['vad_hangover_ms'], 0),
      vad_calibration_ms: this.num(config['vad_calibration_ms'], 300),
      vad_min_silence_frames_ms: this.num(config['vad_min_silence_frames_ms'], 0),
    };
  }

  private voiceOutputToDraft(value: unknown): VoiceOutputSettingsDraft {
    const config = this.asRecord(value);
    const profile = config['latency_profile'] === 'balanced' || config['latency_profile'] === 'quality'
      ? config['latency_profile'] as VoiceOutputLatencyProfile
      : 'fast';
    return {
      latency_profile: profile,
      voice: this.str(config['voice']) || 'nova',
      flush_first_chars: this.num(config['flush_first_chars'], 24),
      flush_next_chars: this.num(config['flush_next_chars'], 80),
      flush_timeout_ms: this.num(config['flush_timeout_ms'], 900),
      interrupt_on_user_speech: config['interrupt_on_user_speech'] !== false,
    };
  }

  private defaultVoiceLoopDraft(): VoiceLoopSettingsDraft {
    return {
      default_mode: 'batch',
      capture_mode: 'normal',
      auto_capture_mode_enabled: false,
      auto_send_final_transcript: false,
      auto_endpoint: true,
      auto_rearm_after_tts: true,
      barge_in: true,
      commands_enabled: true,
      trigger_word: '',
      command_packs_text: 'generic, fr_basic',
      stop_phrases_text: "on peut s'arrêter là, ça suffit, fin de session",
      silence_ms: 1200,
      dictation_silence_ms: 2000,
      min_speech_ms: 350,
      dictation_min_speech_ms: 300,
      max_turn_ms: 45000,
      cooldown_ms: 500,
      rms_threshold: 0.018,
      endpoint_grace_ms: 0,
      vad_hangover_ms: 0,
      vad_calibration_ms: 300,
      vad_min_silence_frames_ms: 0,
    };
  }

  private defaultVoiceOutputDraft(): VoiceOutputSettingsDraft {
    return {
      latency_profile: 'fast',
      voice: 'nova',
      flush_first_chars: 24,
      flush_next_chars: 80,
      flush_timeout_ms: 900,
      interrupt_on_user_speech: true,
    };
  }

  private defaultTableIntelligenceDraft(): TableIntelligenceSettingsDraft {
    return {
      default_profile: '',
      profiles: [],
    };
  }

  private defaultDocumentIntelligenceDraft(): DocumentIntelligenceSettingsDraft {
    return {
      default_profile: '',
      profiles: [],
      ocr: {
        enabled: true,
        provider_priority_text: 'ppocr_service, tesseract_local',
        languages_text: 'eng, fra',
        required: false,
        force_ocr: false,
        scan_detection: true,
        min_native_pdf_chars: 80,
        min_confidence: 0,
        timeout_seconds: 30,
        retries: 2,
        ppocr_endpoint_url: '',
        openai_vision_enabled: false,
        openai_model: 'gpt-4o-mini',
        openai_detail: 'low',
        openai_max_image_bytes: 5000000,
        openai_enrich_min_chars: 24,
        openai_enrich_min_confidence: 0.45,
      },
    };
  }

  private tableIntelligenceToDraft(value: unknown): TableIntelligenceSettingsDraft {
    const config = this.asRecord(value);
    const profilesRaw = Array.isArray(config['profiles']) ? config['profiles'] : [];
    const profiles = profilesRaw
      .map((raw) => this.tableProfileToDraft(this.asRecord(raw)))
      .filter((profile) => profile.key || profile.label);
    return {
      default_profile: this.str(config['default_profile']),
      profiles,
    };
  }

  private tableProfileToDraft(raw: Record<string, unknown>): TableProfileDraft {
    const aggregation = this.asRecord(raw['aggregation_policy']);
    const evidence = this.asRecord(raw['evidence_policy']);
    return {
      key: this.str(raw['key']),
      label: this.str(raw['label']),
      description: this.str(raw['description']),
      synonyms_text: this.recordToMapText(raw['synonyms']),
      metric_aliases_text: this.recordToMapText(raw['metric_aliases']),
      allow_mean: aggregation['allow_mean'] !== false,
      require_compatible_units: aggregation['require_compatible_units'] !== false,
      exclude_non_numeric: aggregation['exclude_non_numeric'] !== false,
      ambiguity_policy: this.str(raw['ambiguity_policy']) || 'ask_when_metric_unclear',
      require_cell_citations: evidence['require_cell_citations'] !== false,
      show_excluded_values: evidence['show_excluded_values'] !== false,
    };
  }

  private documentIntelligenceToDraft(value: unknown): DocumentIntelligenceSettingsDraft {
    const config = this.asRecord(value);
    const profilesRaw = Array.isArray(config['profiles']) ? config['profiles'] : [];
    const profiles = profilesRaw
      .map((raw) => this.documentProfileToDraft(this.asRecord(raw)))
      .filter((profile) => profile.key || profile.label);
    return {
      default_profile: this.str(config['default_profile']),
      profiles,
      ocr: this.ocrSettingsToDraft(config['ocr']),
    };
  }

  private documentProfileToDraft(raw: Record<string, unknown>): DocumentProfileDraft {
    return {
      key: this.str(raw['key']),
      label: this.str(raw['label']),
      description: this.str(raw['description']),
      synonyms_text: this.recordToMapText(raw['synonyms']),
      max_candidate_facts: this.num(raw['max_candidate_facts'], 5000),
      max_evidence_rows: this.num(raw['max_evidence_rows'], 24),
    };
  }

  private ocrSettingsToDraft(value: unknown): OcrSettingsDraft {
    const config = this.asRecord(value);
    const fallback = this.defaultDocumentIntelligenceDraft().ocr;
    const detail = this.str(config['openai_detail']);
    return {
      enabled: config['enabled'] !== false,
      provider_priority_text: this.listToCsv(config['provider_priority']) || this.str(config['provider_priority']) || fallback.provider_priority_text,
      languages_text: this.listToCsv(config['languages']) || this.str(config['languages']) || fallback.languages_text,
      required: config['required'] === true,
      force_ocr: config['force_ocr'] === true,
      scan_detection: config['scan_detection'] !== false,
      min_native_pdf_chars: this.num(config['min_text_chars_for_native_pdf'], this.num(config['min_native_pdf_chars'], 80)),
      min_confidence: this.num(config['min_confidence'], 0),
      timeout_seconds: this.num(config['timeout_seconds'], 30),
      retries: this.num(config['retries'], 2),
      ppocr_endpoint_url: this.str(config['ppocr_endpoint_url']),
      openai_vision_enabled: config['openai_vision_enabled'] === true,
      openai_model: this.str(config['openai_model']) || fallback.openai_model,
      openai_detail: detail === 'high' || detail === 'auto' ? detail : 'low',
      openai_max_image_bytes: this.num(config['openai_max_image_bytes'], fallback.openai_max_image_bytes),
      openai_enrich_min_chars: this.num(config['openai_enrich_min_chars'], fallback.openai_enrich_min_chars),
      openai_enrich_min_confidence: this.num(config['openai_enrich_min_confidence'], fallback.openai_enrich_min_confidence),
    };
  }

  addTableProfile(): void {
    const next = [...this.tableIntelligenceDraft.profiles];
    next.push({
      key: `table_profile_${next.length + 1}`,
      label: `Table profile ${next.length + 1}`,
      description: '',
      synonyms_text: '',
      metric_aliases_text: '',
      allow_mean: true,
      require_compatible_units: true,
      exclude_non_numeric: true,
      ambiguity_policy: 'ask_when_metric_unclear',
      require_cell_citations: true,
      show_excluded_values: true,
    });
    this.tableIntelligenceDraft = {
      ...this.tableIntelligenceDraft,
      profiles: next,
    };
  }

  removeTableProfile(index: number): void {
    const removed = this.tableIntelligenceDraft.profiles[index]?.key;
    const profiles = this.tableIntelligenceDraft.profiles.filter((_, i) => i !== index);
    this.tableIntelligenceDraft = {
      default_profile: this.tableIntelligenceDraft.default_profile === removed ? '' : this.tableIntelligenceDraft.default_profile,
      profiles,
    };
    this.scopes.set(this.scopes().map((scope) => scope.table_profile_key === removed ? { ...scope, table_profile_key: '' } : scope));
  }

  addDocumentProfile(): void {
    const next = [...this.documentIntelligenceDraft.profiles];
    next.push({
      key: `document_profile_${next.length + 1}`,
      label: `Document profile ${next.length + 1}`,
      description: '',
      synonyms_text: '',
      max_candidate_facts: 5000,
      max_evidence_rows: 24,
    });
    this.documentIntelligenceDraft = {
      ...this.documentIntelligenceDraft,
      profiles: next,
    };
  }

  removeDocumentProfile(index: number): void {
    const removed = this.documentIntelligenceDraft.profiles[index]?.key;
    const profiles = this.documentIntelligenceDraft.profiles.filter((_, i) => i !== index);
    this.documentIntelligenceDraft = {
      ...this.documentIntelligenceDraft,
      default_profile: this.documentIntelligenceDraft.default_profile === removed ? '' : this.documentIntelligenceDraft.default_profile,
      profiles,
    };
    this.scopes.set(this.scopes().map((scope) => scope.document_profile_key === removed ? { ...scope, document_profile_key: '' } : scope));
  }

  private actionSettingsToDraft(value: unknown): WorkspaceActionSettingsDraft {
    const config = this.asRecord(value);
    return {
      enabled_packs_text: this.listToCsv(config['enabled_packs']),
      hidden_packs_text: this.listToCsv(config['hidden_packs']),
      enabled_actions_text: this.listToCsv(config['enabled_actions']),
      hidden_actions_text: this.listToCsv(config['hidden_actions']),
    };
  }

  private defaultActionSettingsDraft(): WorkspaceActionSettingsDraft {
    return {
      enabled_packs_text: '',
      hidden_packs_text: '',
      enabled_actions_text: '',
      hidden_actions_text: '',
    };
  }

  private csvToList(value: string): string[] {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  private listToCsv(value: unknown): string {
    return Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean).join(', ') : '';
  }

  private recordToMapText(value: unknown): string {
    const record = this.asRecord(value);
    return Object.entries(record)
      .map(([key, raw]) => {
        const items = Array.isArray(raw) ? raw.map((item) => String(item).trim()).filter(Boolean) : [];
        return items.length ? `${key}: ${items.join(', ')}` : '';
      })
      .filter(Boolean)
      .join('\n');
  }

  private mapTextToRecord(value: string): Record<string, string[]> {
    const out: Record<string, string[]> = {};
    value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .forEach((line) => {
        const separator = line.indexOf(':');
        const key = (separator >= 0 ? line.slice(0, separator) : line).trim();
        if (!key) return;
        const rawItems = separator >= 0 ? line.slice(separator + 1) : '';
        const items = rawItems
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean);
        if (items.length) out[key] = items;
      });
    return out;
  }

  private num(value: unknown, fallback: number): number {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  private clampNumber(value: unknown, fallback: number, min: number, max: number): number {
    const n = this.num(value, fallback);
    return Math.min(max, Math.max(min, Math.round(n)));
  }

  private clampFloat(value: unknown, fallback: number, min: number, max: number): number {
    const n = this.num(value, fallback);
    return Math.min(max, Math.max(min, n));
  }

  private promptPackDraft(value: unknown): PromptCardDraft[] {
    if (!Array.isArray(value)) return [];
    return value.flatMap((item) => {
      const record = this.asRecord(item);
      const label = this.str(record['label']);
      const prompt = this.str(record['prompt']);
      if (!label || !prompt) return [];
      return [{
        icon: this.str(record['icon']) || 'sparkles',
        label,
        prompt,
        scope_key: this.str(record['scope_key'] || record['knowledge_scope'] || record['source_key']),
        context_mode: record['context_mode'] === 'replace' || record['context_mode'] === 'combine'
          ? record['context_mode'] as SessionPromptMode
          : 'any',
      }];
    });
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  }

  private str(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  private effectiveChatConfig(): Record<string, unknown> {
    const workspaceChat = this.workspaceChatDraftRecord();
    const profileChat = this.asRecord(this.activeAssistantProfile()?.chat);
    return { ...workspaceChat, ...profileChat };
  }

  private workspaceChatDraftRecord(): Record<string, unknown> {
    const chat: Record<string, unknown> = { ...this.asRecord(this.detail()?.settings?.['chat']) };
    this.setOrDelete(chat, 'title', this.chatDraft.title);
    this.setOrDelete(chat, 'subtitle', this.chatDraft.subtitle);
    this.setOrDelete(chat, 'placeholder', this.chatDraft.placeholder);
    const prompts = this.chatDraft.prompt_pack
      .map((prompt) => ({ ...prompt }))
      .filter((prompt) => prompt.label.trim() && prompt.prompt.trim());
    if (prompts.length) chat['prompt_pack'] = prompts;
    else delete chat['prompt_pack'];
    return chat;
  }

  private setOrDelete(target: Record<string, unknown>, key: string, value: string): void {
    const trimmed = value.trim();
    if (trimmed) target[key] = trimmed;
    else delete target[key];
  }

  private generatedKnowledgePrompts(sourceLabel: string): PromptCardDraft[] {
    const label = sourceLabel || 'contexte du workspace';
    return [
      {
        icon: 'search',
        label: 'Poser une question',
        prompt: `Que disent les documents ${label} sur [votre sujet] ? Cite les sources utilisées.`,
        scope_key: '',
        context_mode: 'any',
      },
      {
        icon: 'file-search',
        label: 'Retrouver un passage',
        prompt: `Retrouve dans ${label} le passage, la procédure ou la section qui explique [votre sujet].`,
        scope_key: '',
        context_mode: 'any',
      },
      {
        icon: 'split',
        label: 'Comparer',
        prompt: `Compare les informations disponibles dans ${label} sur [votre sujet].`,
        scope_key: '',
        context_mode: 'any',
      },
      {
        icon: 'list-checks',
        label: 'Résumer',
        prompt: `Résume les points clés trouvés dans ${label} sur [votre sujet], avec les sources utiles.`,
        scope_key: '',
        context_mode: 'any',
      },
    ];
  }

  private scopeLabel(scopeKey: string | null | undefined): string {
    if (!scopeKey) return 'workspace';
    const scope = this.scopes().find((item) => item.key === scopeKey);
    return this.cleanSourceLabel(scope?.label || scopeKey);
  }

  private cleanSourceLabel(label: string): string {
    const cleaned = label
      .replace(/\bknowledge\s+experiment\b/gi, '')
      .replace(/\bworkspace\s+Knowledge\b/g, 'contexte du workspace')
      .replace(/\s{2,}/g, ' ')
      .replace(/[\s·,:-]+$/g, '')
      .trim();
    return cleaned || label;
  }

  private collectionSlugs(scope: KnowledgeScopeDraft): string[] {
    return scope.collection_slugs_text
      .split(',')
      .map((slug) => slug.trim())
      .filter(Boolean);
  }
}
