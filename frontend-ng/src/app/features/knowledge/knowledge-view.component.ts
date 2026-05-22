import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { SlicePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { IconComponent } from '@app/shared/ui/icon.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { LensService } from '@app/core/lens';
import { CanonicalApiService, type System } from '@app/core/canonical-api.service';
import { ApiService, DocumentFactItem, KnowledgeGuide, TableFactItem } from '@app/core/api.service';
import { WorkspaceService } from '@app/core/workspace.service';

/**
 * `KnowledgeViewComponent` — detail page for a single Knowledge Base
 * (Qdrant collection). Uses the canonical `<ck-object-header>` +
 * `<ck-tabs>` pattern with **live** facets:
 *
 *   - **Overview**  — resolved counts, vector DB, last indexed
 *   - **Sources**   — table of ingested documents
 *   - **Chunks**    — distribution + sample (from stats endpoint)
 *   - **Bindings**  — Systems whose `flow_definition.collections`
 *                     references this KB (client-side filter, low
 *                     cardinality — acceptable tradeoff, see
 *                     vague-b-p1 plan §Commit 4)
 */
interface DocRow {
  document_id: string;
  filename: string;
  chunk_count?: number;
  chunks_count?: number;
  mime_type?: string;
  uploaded_at?: string;
  size?: number;
}

interface StatsPayload {
  collection_name?: string;
  total_chunks?: number;
  vector_dim?: number | null;
  cache_stats?: Record<string, unknown> | null;
}

interface CollectionsPayload {
  collections?: string[];
  vector_db_type?: string;
  default?: string | null;
}

interface KnowledgeScopeApi {
  key: string;
  label?: string | null;
  collection_slugs?: string[];
  table_profile_key?: string | null;
  document_profile_key?: string | null;
}

interface KnowledgeGuideRow {
  guide: KnowledgeGuide;
  binding_label: string;
  binding_kind: 'collection' | 'scope';
}

type KbTabId =
  | 'overview'
  | 'sources'
  | 'chunks'
  | 'structure'
  | 'facts'
  | 'ocr'
  | 'table-facts'
  | 'guides'
  | 'diagnostics'
  | 'bindings';

@Component({
  selector: 'app-knowledge-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    SlicePipe,
    IconComponent,
    EmptyStateComponent,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Knowledge · Collection"
      [title]="title()"
      subtitle="A knowledge base is a pool of context that one or more Systems can cite at run time."
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="bindingsPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="link" [size]="14" /> Bindings
      </button>
      <a
        actions
        routerLink="/knowledge"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        <app-icon name="arrow-left" [size]="14" /> Back
      </a>
    </ck-object-header>

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="Knowledge facets"
    >
      <ck-tab id="overview" label="Overview">
        <section class="t-card t-elevated rounded-md p-5 space-y-4">
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Documents</div>
              <div class="text-lg font-semibold text-white tabular-nums">{{ loading() ? '…' : docCount() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Chunks</div>
              <div class="text-lg font-semibold text-white tabular-nums">{{ loading() ? '…' : chunkCount() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Vector DB</div>
              <div class="text-lg font-semibold text-white">{{ vectorDbType() || '—' }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Embedding dim</div>
              <div class="text-lg font-semibold text-white tabular-nums">{{ vectorDim() ?? '—' }}</div>
            </div>
          </div>
          <div class="text-xs text-gray-400 leading-relaxed max-w-2xl border-t border-white/5 pt-4">
            The collection holds embedded chunks of source documents. Presets (RAG,
            CHAH, HAH) decide how it is consumed by a System at run time. Last
            ingestion time is tracked per document in the Sources tab.
          </div>
          <div class="flex items-center gap-2 flex-wrap text-xs pt-2">
            <p class="text-[11px] text-gray-500">
              Lens: <span class="font-mono text-brand-300">{{ lens() }}</span>
            </p>
          </div>
        </section>
      </ck-tab>

      <ck-tab id="sources" label="Sources">
        @if (loadingSources()) {
          <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
            <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
            Loading sources…
          </div>
        } @else if (sources().length === 0) {
          <app-empty-state
            icon="file-text"
            title="No sources yet"
            description="Upload documents to this collection from the Knowledge index."
          />
        } @else {
          <div class="t-card rounded-md overflow-hidden">
            <table class="w-full text-sm">
              <thead class="text-[10px] uppercase tracking-wider text-gray-500 bg-black/20">
                <tr>
                  <th class="text-left px-4 py-2 font-semibold">Filename</th>
                  <th class="text-right px-4 py-2 font-semibold">Chunks</th>
                  <th class="text-left px-4 py-2 font-semibold">Type</th>
                  <th class="text-left px-4 py-2 font-semibold">Uploaded</th>
                </tr>
              </thead>
              <tbody>
                @for (s of sources(); track s.document_id) {
                  <tr class="border-t border-white/5 hover:bg-white/5 transition">
                    <td class="px-4 py-2.5 text-white truncate max-w-xs">{{ s.filename }}</td>
                    <td class="px-4 py-2.5 text-right tabular-nums text-gray-300">{{ s.chunk_count ?? '—' }}</td>
                    <td class="px-4 py-2.5 text-gray-400 text-xs">{{ s.mime_type || '—' }}</td>
                    <td class="px-4 py-2.5 text-gray-400 text-xs">{{ s.uploaded_at ? (s.uploaded_at | slice:0:10) : '—' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </ck-tab>

      <ck-tab id="chunks" label="Chunks">
        <section class="t-card rounded-md p-5 space-y-4">
          <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Total chunks</div>
              <div class="text-xl font-semibold text-white tabular-nums">{{ loading() ? '…' : chunkCount() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Avg chunks / doc</div>
              <div class="text-xl font-semibold text-white tabular-nums">{{ avgChunksPerDoc() }}</div>
            </div>
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">Vector dim</div>
              <div class="text-xl font-semibold text-white tabular-nums">{{ vectorDim() ?? '—' }}</div>
            </div>
          </div>

          @if (sources().length > 0) {
            <div class="border-t border-white/5 pt-3">
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">
                Distribution by document
              </div>
              <div class="space-y-1.5">
                @for (s of topSources(); track s.document_id) {
                  <div class="flex items-center gap-3 text-xs">
                    <div class="flex-1 min-w-0 truncate text-gray-200">{{ s.filename }}</div>
                    <div class="w-48 bg-white/5 h-1.5 rounded overflow-hidden">
                      <div
                        class="h-full bg-brand-500"
                        [style.width.%]="distributionPct(s.chunk_count)"
                      ></div>
                    </div>
                    <div class="w-10 text-right text-gray-400 tabular-nums">{{ s.chunk_count ?? 0 }}</div>
                  </div>
                }
              </div>
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="structure" label="Structure">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Document intelligence
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Extracted document structure</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                Headings, procedures, warnings and tables are extracted from PDF, DOCX,
                Markdown and HTML manuals so retrieval can cite pages and sections, not only chunks.
              </p>
            </div>
            <button
              type="button"
              (click)="loadDocumentFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh
            </button>
          </div>

          @if (loadingDocumentFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading document structure…
            </div>
          } @else if (documentFacts().length === 0) {
            <app-empty-state
              icon="file-search"
              title="No document structure yet"
              description="Re-index PDF, DOCX, Markdown or HTML sources to populate structure and facts."
            />
          } @else {
            <div class="grid gap-4 p-5 lg:grid-cols-3">
              @for (group of documentStructureGroups(); track group.type) {
                <article class="rounded border border-white/10 bg-black/20 p-4">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ group.type }}</div>
                  <div class="mt-1 text-2xl font-semibold text-white tabular-nums">{{ group.count }}</div>
                  <p class="mt-2 text-xs text-gray-500">{{ group.hint }}</p>
                </article>
              }
            </div>
            <div class="divide-y divide-white/5 border-t border-white/5">
              @for (fact of structurePreviewFacts(); track documentFactKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'document_fact' }}
                    </span>
                    @if (fact.page) {
                      <span>Page {{ fact.page }}</span>
                    }
                    @if (fact.section_path) {
                      <span class="truncate">Section: <span class="text-gray-300">{{ fact.section_path }}</span></span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Document source' }}
                  </h4>
                  <p class="mt-2 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">{{ fact.content }}</p>
                </article>
              }
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="facts" label="Facts">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Generic fact layer
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Document facts</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                Browse extracted procedures, warnings, parameters, definitions and evidence locators.
                These facts complement table facts and vector chunks.
              </p>
            </div>
            <button
              type="button"
              (click)="loadDocumentFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh facts
            </button>
          </div>
          <div class="grid gap-3 border-b border-white/5 px-5 py-4 md:grid-cols-[minmax(0,1fr)_240px]">
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Search</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Procedure, warning, parameter, section…"
                [value]="documentFactQuery()"
                (input)="documentFactQuery.set($any($event.target).value)"
                (keydown.enter)="loadDocumentFacts()"
              />
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Type</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="documentFactType()"
                (change)="documentFactType.set($any($event.target).value); loadDocumentFacts()"
              >
                <option value="">All document facts</option>
                <option value="document_heading">Headings</option>
                <option value="document_procedure_step">Procedure steps</option>
                <option value="document_warning">Warnings</option>
                <option value="document_parameter">Parameters</option>
                <option value="document_definition">Definitions</option>
                <option value="document_table">Tables</option>
              </select>
            </label>
          </div>
          @if (loadingDocumentFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading document facts…
            </div>
          } @else if (documentFacts().length === 0) {
            <app-empty-state
              icon="file-search"
              title="No document facts found"
              description="Re-index manual/procedure sources with Document Intelligence enabled, then refresh this tab."
            />
          } @else {
            <div class="divide-y divide-white/5">
              @for (fact of documentFacts(); track documentFactKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'document_fact' }}
                    </span>
                    @if (fact.document_type) {
                      <span>{{ fact.document_type }}</span>
                    }
                    @if (fact.page) {
                      <span>Page {{ fact.page }}</span>
                    }
                    @if (fact.paragraph_index !== null && fact.paragraph_index !== undefined) {
                      <span>Paragraph {{ fact.paragraph_index }}</span>
                    }
                    @if (fact.table_index !== null && fact.table_index !== undefined) {
                      <span>Table {{ fact.table_index }}</span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Document source' }}
                  </h4>
                  @if (fact.section_path) {
                    <p class="mt-1 text-[11px] text-gray-500 truncate">{{ fact.section_path }}</p>
                  }
                  <div class="mt-2 flex flex-wrap gap-2 text-[11px]">
                    @if (fact.subject) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">subject: {{ fact.subject }}</span>
                    }
                    @if (fact.predicate) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">predicate: {{ fact.predicate }}</span>
                    }
                    @if (fact.value_raw) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">value: {{ fact.value_raw }}</span>
                    }
                    @if (fact.unit) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">unit: {{ fact.unit }}</span>
                    }
                  </div>
                  <p class="mt-3 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">{{ fact.content }}</p>
                </article>
              }
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="ocr" label="OCR">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Visual document intelligence
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">OCR / visual evidence</h3>
              <p class="mt-1 max-w-2xl text-xs leading-relaxed text-gray-400">
                Inspect text extracted from scanned PDFs and images. V1 stores OCR blocks as
                document facts, V1.5 exposes them here, and V2 can route/enrich through
                service providers such as PP-OCR, Tesseract or vision fallback.
              </p>
            </div>
            <button
              type="button"
              (click)="loadOcrFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh OCR
            </button>
          </div>
          <div class="grid gap-3 border-b border-white/5 px-5 py-4 md:grid-cols-[minmax(0,1fr)_220px]">
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Search OCR text</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Text, warning, label, OCR block…"
                [value]="ocrFactQuery()"
                (input)="ocrFactQuery.set($any($event.target).value)"
                (keydown.enter)="loadOcrFacts()"
              />
            </label>
            <label class="block">
              <span class="ck-mono mb-1 block text-[10px] uppercase tracking-wider text-gray-500">Visual type</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="ocrFactType()"
                (change)="ocrFactType.set($any($event.target).value); loadOcrFacts()"
              >
                <option value="">All OCR evidence</option>
                <option value="document_ocr_text">OCR pages</option>
                <option value="visual_text_block">Text blocks</option>
                <option value="visual_parameter">Visual parameters</option>
                <option value="visual_warning">Visual warnings</option>
              </select>
            </label>
          </div>
          @if (loadingOcrFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading OCR evidence…
            </div>
          } @else if (ocrFacts().length === 0) {
            <app-empty-state
              icon="scan-text"
              title="No OCR evidence found"
              description="Ingest scanned PDFs or image files with OCR enabled, then refresh this tab. Native text PDFs do not need OCR unless force OCR is enabled."
            />
          } @else {
            <div class="grid gap-4 p-5 md:grid-cols-4">
              @for (row of ocrSummaryRows(); track row.label) {
                <article class="rounded border border-white/10 bg-black/20 p-3">
                  <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ row.label }}</div>
                  <div class="mt-1 text-xl font-semibold text-white tabular-nums">{{ row.value }}</div>
                  <p class="mt-1 text-[11px] text-gray-500">{{ row.hint }}</p>
                </article>
              }
            </div>
            <div class="divide-y divide-white/5 border-t border-white/5">
              @for (fact of ocrFacts(); track ocrFactKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'ocr' }}
                    </span>
                    @if (fact.page) {
                      <span>Page {{ fact.page }}</span>
                    }
                    @if (ocrProviderLabel(fact)) {
                      <span>Provider: <span class="text-gray-300">{{ ocrProviderLabel(fact) }}</span></span>
                    }
                    @if (ocrConfidenceLabel(fact)) {
                      <span>Confidence: <span class="text-gray-300">{{ ocrConfidenceLabel(fact) }}</span></span>
                    }
                    @if (ocrBoxLabel(fact)) {
                      <span>Box: <span class="font-mono text-gray-300">{{ ocrBoxLabel(fact) }}</span></span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Visual source' }}
                  </h4>
                  @if (fact.section_path) {
                    <p class="mt-1 text-[11px] text-gray-500 truncate">{{ fact.section_path }}</p>
                  }
                  <p class="mt-3 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">{{ fact.content || fact.value_raw }}</p>
                  @if (ocrWarningLabel(fact)) {
                    <p class="mt-2 rounded border border-amber-400/20 bg-amber-400/10 px-2 py-1 text-[11px] text-amber-100">
                      {{ ocrWarningLabel(fact) }}
                    </p>
                  }
                </article>
              }
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="table-facts" label="Table facts">
        <section class="t-card rounded-md overflow-hidden">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Spreadsheet intelligence
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Structured table facts</h3>
              <p class="mt-1 text-xs text-gray-400 max-w-2xl">
                Browse the indexed workbook facts used by chat: schema, row chunks,
                cell facts, table facts and semantic sentences with sheet/cell metadata.
              </p>
            </div>
            <button
              type="button"
              (click)="loadTableFacts()"
              class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
            >
              <app-icon name="refresh-cw" [size]="13" /> Refresh facts
            </button>
          </div>
          <div class="px-5 py-4 border-b border-white/5 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_220px]">
            <label class="block">
              <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Search</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Sheet, label, cell, value…"
                [value]="tableFactQuery()"
                (input)="tableFactQuery.set($any($event.target).value)"
                (keydown.enter)="loadTableFacts()"
              />
            </label>
            <label class="block">
              <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Type</span>
              <select
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                [value]="tableFactType()"
                (change)="tableFactType.set($any($event.target).value); loadTableFacts()"
              >
                <option value="">All table views</option>
                <option value="spreadsheet_cell_fact">Cell facts</option>
                <option value="spreadsheet_table_fact">Table facts</option>
                <option value="spreadsheet_semantic_sentence">Semantic sentences</option>
                <option value="spreadsheet_schema">Schema</option>
                <option value="spreadsheet_row">Rows</option>
              </select>
            </label>
            <label class="block">
              <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Sheet</span>
              <input
                class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                type="search"
                placeholder="Def strips"
                [value]="tableFactSheet()"
                (input)="tableFactSheet.set($any($event.target).value)"
                (keydown.enter)="loadTableFacts()"
              />
            </label>
          </div>
          @if (loadingTableFacts()) {
            <div class="p-5 text-sm text-gray-400">
              <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
              Loading table facts…
            </div>
          } @else if (tableFacts().length === 0) {
            <app-empty-state
              icon="table"
              title="No table facts found"
              description="Re-index spreadsheet sources with Table Intelligence enabled, then refresh this tab."
            />
          } @else {
            <div class="divide-y divide-white/5">
              @for (fact of tableFacts(); track factKey(fact, $index)) {
                <article class="px-5 py-4 hover:bg-white/[0.03] transition">
                  <div class="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                    <span class="ck-mono rounded bg-brand-500/10 px-2 py-1 text-brand-300 ring-1 ring-brand-500/20">
                      {{ fact.semantic_type || 'spreadsheet' }}
                    </span>
                    @if (fact.sheet_name) {
                      <span>Sheet: <span class="text-gray-300">{{ fact.sheet_name }}</span></span>
                    }
                    @if (fact.cell_ref || fact.cell_range) {
                      <span>Cell: <span class="font-mono text-gray-300">{{ fact.cell_ref || fact.cell_range }}</span></span>
                    }
                    @if (fact.unit) {
                      <span>Unit: <span class="text-gray-300">{{ fact.unit }}</span></span>
                    }
                  </div>
                  <h4 class="mt-2 text-sm font-medium text-white truncate">
                    {{ fact.document_filename || 'Spreadsheet source' }}
                  </h4>
                  <div class="mt-2 flex flex-wrap gap-2 text-[11px]">
                    @if (fact.row_label) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">row: {{ fact.row_label }}</span>
                    }
                    @if (fact.column_header) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-300">column: {{ fact.column_header }}</span>
                    }
                    @if (fact.table_region_id) {
                      <span class="rounded bg-white/5 px-2 py-1 text-gray-500">region: {{ fact.table_region_id }}</span>
                    }
                  </div>
                  <p class="mt-3 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap">
                    {{ fact.content }}
                  </p>
                  @if (fact.interpretation_note) {
                    <p class="mt-2 text-[11px] text-amber-200/80">{{ fact.interpretation_note }}</p>
                  }
                </article>
              }
            </div>
          }
        </section>
      </ck-tab>

      <ck-tab id="guides" label="Guides">
        <section class="t-card rounded-md overflow-hidden mb-4">
          <div class="px-5 py-4 border-b border-white/5 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                Collection guide
              </div>
              <h3 class="mt-1 text-base font-semibold text-white">Markdown interpretation guide</h3>
              <p class="mt-1 text-xs text-gray-400 max-w-2xl">
                Explain how to read this collection. Guides help query expansion
                and prompting, but raw table/document facts remain the proof.
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                (click)="saveCollectionGuide('draft')"
                [disabled]="savingGuide()"
                class="inline-flex items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-50"
              >
                <app-icon name="save" [size]="13" /> Save draft
              </button>
              <button
                type="button"
                (click)="saveCollectionGuide('published')"
                [disabled]="savingGuide()"
                class="inline-flex items-center gap-1.5 rounded bg-brand-500 px-3 py-2 text-xs font-semibold text-black hover:bg-brand-400 disabled:opacity-50"
              >
                <app-icon name="check" [size]="13" /> Publish
              </button>
            </div>
          </div>
          <div class="grid gap-0 lg:grid-cols-2">
            <div class="p-5 border-b border-white/5 lg:border-b-0 lg:border-r">
              <label class="block">
                <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Title</span>
                <input
                  class="w-full rounded bg-black/25 border border-white/10 px-3 py-2 text-sm text-white outline-none focus:border-brand-400"
                  [value]="guideTitle()"
                  (input)="guideTitle.set($any($event.target).value)"
                />
              </label>
              <label class="block mt-3">
                <span class="ck-mono block text-[10px] uppercase tracking-wider text-gray-500 mb-1">Markdown</span>
                <textarea
                  class="min-h-[28rem] w-full rounded bg-black/25 border border-white/10 px-3 py-2 font-mono text-xs leading-relaxed text-gray-200 outline-none focus:border-brand-400"
                  [value]="guideMarkdown()"
                  (input)="guideMarkdown.set($any($event.target).value)"
                ></textarea>
              </label>
              @if (guideError()) {
                <p class="mt-2 text-xs text-red-300">{{ guideError() }}</p>
              }
            </div>
            <div class="p-5">
              <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">Preview</div>
              <pre class="min-h-[28rem] max-h-[36rem] overflow-auto whitespace-pre-wrap rounded bg-black/25 p-4 text-xs leading-relaxed text-gray-300">{{ guideMarkdown() || 'No Markdown yet.' }}</pre>
              <div class="mt-4">
                <div class="ck-mono text-[10px] uppercase tracking-wider text-gray-500 mb-2">Versions</div>
                @if (collectionGuideVersions().length === 0) {
                  <p class="text-xs text-gray-500">No saved versions yet.</p>
                } @else {
                  <div class="space-y-2">
                    @for (guide of collectionGuideVersions(); track guide.id) {
                      <button
                        type="button"
                        (click)="loadGuideIntoEditor(guide)"
                        class="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-left hover:bg-white/10"
                      >
                        <div class="flex items-center justify-between gap-2">
                          <span class="text-xs font-medium text-white">v{{ guide.version }} · {{ guide.status }}</span>
                          <span class="text-[11px] text-gray-500">{{ guide.created_at ? (guide.created_at | slice:0:10) : '—' }}</span>
                        </div>
                        <p class="mt-1 truncate text-[11px] text-gray-500">{{ guide.title }}</p>
                      </button>
                    }
                  </div>
                }
              </div>
            </div>
          </div>
        </section>

        @if (guideRows().length === 0) {
          <app-empty-state
            icon="book-open"
            title="No Knowledge Guide"
            description="Attach a Markdown guide from Workspace > Chat & Knowledge when this collection needs vocabulary, interpretation rules or query hints."
          />
        } @else {
          <section class="space-y-3">
            @for (row of guideRows(); track row.guide.id) {
              <article class="t-card rounded-md overflow-hidden">
                <div class="px-5 py-4 border-b border-white/5 flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">
                      {{ row.binding_kind === 'scope' ? 'Scope guide' : 'Collection guide' }} · {{ row.binding_label }}
                    </div>
                    <h3 class="mt-1 text-base font-semibold text-white truncate">{{ row.guide.title }}</h3>
                    <p class="mt-1 text-xs text-gray-500">
                      v{{ row.guide.version }} · {{ row.guide.status }} @if (row.guide.published_at) { · published {{ row.guide.published_at | slice:0:10 }} }
                    </p>
                  </div>
                  <a
                    [routerLink]="['/workspace', workspaceSlug(), 'chat-knowledge']"
                    class="inline-flex shrink-0 items-center gap-1.5 rounded bg-white/5 px-3 py-2 text-xs font-medium text-gray-200 ring-1 ring-white/10 hover:bg-white/10"
                  >
                    <app-icon name="pencil" [size]="13" /> Edit in settings
                  </a>
                </div>
                <pre class="max-h-[34rem] overflow-auto whitespace-pre-wrap bg-black/20 p-5 text-xs leading-relaxed text-gray-300">{{ row.guide.markdown || row.guide.snippet || 'No Markdown content.' }}</pre>
              </article>
            }
          </section>
        }
      </ck-tab>

      <ck-tab id="diagnostics" label="Diagnostics">
        <section class="grid gap-4 lg:grid-cols-2">
          <article class="t-card rounded-md p-5">
            <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Index health</div>
            <h3 class="mt-1 text-base font-semibold text-white">Collection diagnostics</h3>
            <dl class="mt-4 grid grid-cols-2 gap-3 text-sm">
              @for (row of diagnosticRows(); track row.label) {
                <div class="rounded border border-white/10 bg-black/20 p-3">
                  <dt class="ck-mono text-[10px] uppercase tracking-wider text-gray-500">{{ row.label }}</dt>
                  <dd class="mt-1 text-lg font-semibold text-white tabular-nums">{{ row.value }}</dd>
                  <p class="mt-1 text-[11px] text-gray-500">{{ row.hint }}</p>
                </div>
              }
            </dl>
          </article>
          <article class="t-card rounded-md p-5">
            <div class="ck-mono text-[10px] uppercase tracking-wider text-brand-300">Retrieval layers</div>
            <h3 class="mt-1 text-base font-semibold text-white">How this collection is queried</h3>
            <div class="mt-4 space-y-3 text-xs leading-relaxed text-gray-400">
              <p>
                Vector chunks remain the broad semantic locator. Table facts support
                cell-level lookup and calculations. Document facts support page,
                section, warning, procedure and parameter evidence.
              </p>
              <p>
                Knowledge Guides are injected as interpretation context and query hints,
                but raw document/table facts stay the proof layer for cited answers.
              </p>
              <p class="rounded border border-white/10 bg-black/20 p-3 font-mono text-[11px] text-gray-300">
                collection={{ kbId }} · vector={{ vectorDbType() || 'unknown' }} · docs={{ docCount() }} · chunks={{ chunkCount() }}
              </p>
            </div>
          </article>
        </section>
      </ck-tab>

      <ck-tab id="bindings" label="Bindings">
        @if (loadingBindings()) {
          <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
            <app-icon name="loader-2" [size]="14" class="animate-spin inline-block mr-2" />
            Scanning Systems…
          </div>
        } @else if (bindings().length === 0) {
          <app-empty-state
            icon="link"
            title="No Systems bound"
            description="No System references this collection in its flow yet."
          />
        } @else {
          <ul class="space-y-2">
            @for (sys of bindings(); track sys.id) {
              <li class="t-card rounded-md p-4 flex items-center gap-3">
                <div class="w-9 h-9 rounded bg-brand-500/15 text-brand-400 ring-1 ring-brand-500/30 flex items-center justify-center shrink-0">
                  <app-icon name="cube" [size]="16" />
                </div>
                <div class="flex-1 min-w-0">
                  <a
                    [routerLink]="['/systems', sys.id]"
                    class="text-sm font-medium text-white hover:text-brand-300 transition truncate block"
                  >
                    {{ sys.name }}
                  </a>
                  <div class="text-[11px] text-gray-500 truncate">{{ sys.objective || '—' }}</div>
                </div>
                <span
                  class="ck-mono text-[10px] uppercase tracking-wider px-2 py-1 rounded bg-white/5 text-gray-400"
                >
                  {{ sys.retrieval_mode_default || 'auto' }}
                </span>
              </li>
            }
          </ul>
        }
      </ck-tab>
    </ck-tabs>

    <ck-panel
      [open]="bindingsPanelOpen()"
      (openChange)="bindingsPanelOpen.set($event)"
      position="side"
      eyebrow="Knowledge · panel"
      title="Bindings overview"
      width="420px"
    >
      <p class="text-xs text-gray-400 mb-3">
        Systems whose <span class="font-mono text-brand-300">flow_definition.collections</span>
        references this collection.
      </p>
      @if (bindings().length === 0) {
        <div class="text-xs text-gray-500">No bindings yet.</div>
      } @else {
        <ul class="space-y-1.5">
          @for (sys of bindings(); track sys.id) {
            <li>
              <a
                [routerLink]="['/systems', sys.id]"
                class="text-xs text-brand-300 hover:text-brand-200 transition truncate block"
              >
                {{ sys.name }}
              </a>
            </li>
          }
        </ul>
      }
    </ck-panel>
  `,
})
export class KnowledgeViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly http = inject(HttpClient);
  private readonly canonical = inject(CanonicalApiService);
  private readonly api = inject(ApiService);
  private readonly workspace = inject(WorkspaceService);
  readonly lensService = inject(LensService);

  private readonly base = '/api/v1/documents';

  kbId = '';
  readonly title = signal('Knowledge base');
  readonly activeTab = signal<KbTabId>('overview');
  readonly bindingsPanelOpen = signal(false);

  readonly loading = signal(true);
  readonly loadingSources = signal(true);
  readonly loadingBindings = signal(true);
  readonly loadingTableFacts = signal(false);
  readonly loadingDocumentFacts = signal(false);
  readonly loadingOcrFacts = signal(false);
  readonly savingGuide = signal(false);
  readonly guideError = signal<string | null>(null);

  readonly docCount = signal(0);
  readonly chunkCount = signal(0);
  readonly vectorDim = signal<number | null>(null);
  readonly vectorDbType = signal<string>('');

  readonly sources = signal<DocRow[]>([]);
  readonly bindings = signal<System[]>([]);
  readonly knowledgeGuides = signal<KnowledgeGuide[]>([]);
  readonly knowledgeScopes = signal<KnowledgeScopeApi[]>([]);
  readonly tableFacts = signal<TableFactItem[]>([]);
  readonly documentFacts = signal<DocumentFactItem[]>([]);
  readonly ocrFacts = signal<DocumentFactItem[]>([]);
  readonly tableFactQuery = signal('');
  readonly tableFactType = signal('');
  readonly tableFactSheet = signal('');
  readonly documentFactQuery = signal('');
  readonly documentFactType = signal('');
  readonly ocrFactQuery = signal('');
  readonly ocrFactType = signal('');
  readonly guideTitle = signal('');
  readonly guideMarkdown = signal('');
  readonly editingGuideKey = signal<string | null>(null);

  readonly lens = this.lensService.lens;

  readonly kpis = computed<CkObjectKpi[]>(() => [
    {
      label: 'Docs',
      value: this.loading() ? '…' : String(this.docCount()),
      tone: 'cool',
      hint: 'Source documents ingested into this collection.',
    },
    {
      label: 'Chunks',
      value: this.loading() ? '…' : String(this.chunkCount()),
      tone: 'neutral',
      hint: 'Vector chunks currently indexed.',
    },
    {
      label: 'Bindings',
      value: this.loadingBindings() ? '…' : String(this.bindings().length),
      tone: this.bindings().length > 0 ? 'violet' : 'neutral',
      hint: 'Systems consuming this knowledge base.',
    },
    {
      label: 'Vector DB',
      value: this.vectorDbType() || '—',
      tone: 'neutral',
      hint: 'Underlying vector database type.',
    },
  ]);

  readonly avgChunksPerDoc = computed(() => {
    const docs = this.docCount();
    const chunks = this.chunkCount();
    if (!docs) return '—';
    return (chunks / docs).toFixed(1);
  });

  readonly topSources = computed(() => {
    const sorted = [...this.sources()].sort(
      (a, b) => (b.chunk_count ?? 0) - (a.chunk_count ?? 0),
    );
    return sorted.slice(0, 10);
  });

  readonly guideRows = computed<KnowledgeGuideRow[]>(() => {
    const scopeLabels = new Map(
      this.knowledgeScopes().map((scope) => [scope.key, scope.label || scope.key] as const),
    );
    const scopesForCollection = new Set(
      this.knowledgeScopes()
        .filter((scope) => (scope.collection_slugs || []).includes(this.kbId))
        .map((scope) => scope.key),
    );
    return this.knowledgeGuides()
      .filter((guide) => guide.is_current)
      .flatMap((guide): KnowledgeGuideRow[] => {
        if (guide.target_type === 'collection' && guide.target_ref === this.kbId) {
          return [{ guide, binding_kind: 'collection', binding_label: this.kbId }];
        }
        if (guide.target_type === 'scope' && scopesForCollection.has(guide.target_ref)) {
          return [{
            guide,
            binding_kind: 'scope',
            binding_label: scopeLabels.get(guide.target_ref) || guide.target_ref,
          }];
        }
        return [];
      })
      .sort((a, b) => a.binding_label.localeCompare(b.binding_label) || b.guide.version - a.guide.version);
  });

  readonly collectionGuideVersions = computed(() =>
    this.knowledgeGuides()
      .filter((guide) => guide.target_type === 'collection' && guide.target_ref === this.kbId)
      .sort((a, b) => b.version - a.version),
  );

  readonly documentStructureGroups = computed(() => {
    const facts = this.documentFacts();
    const count = (type: string) => facts.filter((fact) => fact.semantic_type === type).length;
    return [
      {
        type: 'Headings',
        count: count('document_heading'),
        hint: 'Section anchors used for page and section citations.',
      },
      {
        type: 'Procedures',
        count: count('document_procedure_step'),
        hint: 'Steps and procedural clauses extracted from manuals.',
      },
      {
        type: 'Warnings',
        count: count('document_warning'),
        hint: 'Safety, caution and warning statements.',
      },
      {
        type: 'Parameters',
        count: count('document_parameter'),
        hint: 'Explicit name/value or parameter statements.',
      },
      {
        type: 'Definitions',
        count: count('document_definition'),
        hint: 'Terminology and “is/means/refers to” statements.',
      },
      {
        type: 'Tables',
        count: count('document_table'),
        hint: 'Document tables extracted from DOCX/Markdown/HTML when available.',
      },
    ];
  });

  readonly structurePreviewFacts = computed(() => {
    const priority = new Set([
      'document_heading',
      'document_procedure_step',
      'document_warning',
      'document_parameter',
      'document_table',
    ]);
    return this.documentFacts()
      .filter((fact) => priority.has(fact.semantic_type || ''))
      .slice(0, 20);
  });

  readonly diagnosticRows = computed(() => [
    {
      label: 'Documents',
      value: this.loading() ? '…' : String(this.docCount()),
      hint: 'Source files tracked in this collection.',
    },
    {
      label: 'Chunks',
      value: this.loading() ? '…' : String(this.chunkCount()),
      hint: 'Semantic chunks available to vector retrieval.',
    },
    {
      label: 'Table facts',
      value: this.loadingTableFacts() ? '…' : String(this.tableFacts().length),
      hint: 'Loaded sample of structured spreadsheet facts.',
    },
    {
      label: 'Document facts',
      value: this.loadingDocumentFacts() ? '…' : String(this.documentFacts().length),
      hint: 'Loaded sample of structured manual/procedure facts.',
    },
    {
      label: 'OCR evidence',
      value: this.loadingOcrFacts() ? '…' : String(this.ocrFacts().length),
      hint: 'Loaded sample of visual text evidence from scanned PDFs or images.',
    },
    {
      label: 'Guides',
      value: String(this.guideRows().length),
      hint: 'Current collection or scope interpretation guides.',
    },
    {
      label: 'Bindings',
      value: this.loadingBindings() ? '…' : String(this.bindings().length),
      hint: 'Systems using this collection.',
    },
  ]);

  readonly ocrSummaryRows = computed(() => {
    const facts = this.ocrFacts();
    const confidenceValues = facts
      .map((fact) => this.ocrConfidenceValue(fact))
      .filter((value): value is number => value !== null);
    const avgConfidence = confidenceValues.length
      ? `${Math.round((confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length) * 100)}%`
      : '—';
    const providers = new Set(facts.map((fact) => this.ocrProviderLabel(fact)).filter(Boolean));
    return [
      {
        label: 'Evidence',
        value: String(facts.length),
        hint: 'OCR pages, blocks and visual facts currently loaded.',
      },
      {
        label: 'Pages',
        value: String(new Set(facts.map((fact) => `${fact.document_id || ''}:${fact.page ?? ''}`).filter(Boolean)).size),
        hint: 'Distinct document pages/images represented in this sample.',
      },
      {
        label: 'Providers',
        value: providers.size ? String(providers.size) : '—',
        hint: providers.size ? Array.from(providers).slice(0, 3).join(', ') : 'No provider metadata loaded.',
      },
      {
        label: 'Avg confidence',
        value: avgConfidence,
        hint: 'Average OCR confidence when provided by the extractor.',
      },
    ];
  });

  readonly workspaceSlug = computed(() => this.workspace.currentSlug() || this.workspace.current()?.slug || 'current');

  ngOnInit(): void {
    this.kbId = this.route.snapshot.paramMap.get('kbId') ?? '';
    this.title.set(this.kbId || 'Knowledge base');
    this.loadAll();
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as KbTabId);
    if (id === 'table-facts' && this.tableFacts().length === 0) {
      this.loadTableFacts();
    }
    if ((id === 'structure' || id === 'facts' || id === 'diagnostics') && this.documentFacts().length === 0) {
      this.loadDocumentFacts();
    }
    if (id === 'ocr' && this.ocrFacts().length === 0) {
      this.loadOcrFacts();
    }
    if (id === 'diagnostics' && this.tableFacts().length === 0) {
      this.loadTableFacts();
    }
    if (id === 'diagnostics' && this.ocrFacts().length === 0) {
      this.loadOcrFacts();
    }
  }

  distributionPct(n: number | undefined): number {
    const max = this.topSources()[0]?.chunk_count ?? 1;
    if (!n || max === 0) return 0;
    return Math.max(3, Math.min(100, (n / max) * 100));
  }

  private loadAll(): void {
    if (!this.kbId) {
      this.loading.set(false);
      this.loadingSources.set(false);
      this.loadingBindings.set(false);
      return;
    }
    const q = encodeURIComponent(this.kbId);

    forkJoin({
      stats: this.http
        .get<StatsPayload>(`${this.base}/stats?collection_name=${q}`)
        .pipe(catchError(() => of<StatsPayload>({}))),
      list: this.http
        .get<{ documents?: DocRow[]; total?: number }>(
          `${this.base}/list?collection_name=${q}`,
        )
        .pipe(catchError(() => of({ documents: [], total: 0 }))),
      meta: this.http
        .get<CollectionsPayload>(`${this.base}/collections`)
        .pipe(catchError(() => of<CollectionsPayload>({}))),
      guides: this.api
        .listKnowledgeGuides({ current_only: false })
        .pipe(catchError(() => of({ items: [] }))),
      scopes: this.api
        .get<{ scopes: KnowledgeScopeApi[] }>('/knowledge/scopes')
        .pipe(catchError(() => of({ scopes: [] }))),
    }).subscribe(({ stats, list, meta, guides, scopes }) => {
      this.chunkCount.set(stats.total_chunks ?? 0);
      this.vectorDim.set(stats.vector_dim ?? null);
      this.vectorDbType.set(meta.vector_db_type ?? '');
      const documents = (list.documents ?? []).map((doc) => ({
        ...doc,
        chunk_count: doc.chunk_count ?? doc.chunks_count ?? 0,
      }));
      this.sources.set(documents);
      this.docCount.set(list.total ?? (list.documents?.length ?? 0));
      this.loading.set(false);
      this.loadingSources.set(false);
      this.knowledgeGuides.set(guides.items || []);
      this.knowledgeScopes.set(scopes.scopes || []);
      this.hydrateGuideEditor();
    });

    this.canonical.listSystems().subscribe({
      next: (systems) => {
        const bound = (systems ?? []).filter((s) => {
          const flow = (s.flow_definition ?? {}) as Record<string, unknown>;
          const cols = flow['collections'];
          if (Array.isArray(cols)) return cols.includes(this.kbId);
          return false;
        });
        this.bindings.set(bound);
        this.loadingBindings.set(false);
      },
      error: () => {
        this.bindings.set([]);
        this.loadingBindings.set(false);
      },
    });
  }

  loadTableFacts(): void {
    if (!this.kbId) return;
    this.loadingTableFacts.set(true);
    this.api
      .listTableFacts({
        collection_name: this.kbId,
        semantic_type: this.tableFactType() || undefined,
        sheet_name: this.tableFactSheet() || undefined,
        q: this.tableFactQuery() || undefined,
        limit: 120,
      })
      .pipe(catchError(() => of({ items: [] } as any)))
      .subscribe((payload) => {
        this.tableFacts.set(payload.items || []);
        this.loadingTableFacts.set(false);
      });
  }

  loadDocumentFacts(): void {
    if (!this.kbId) return;
    this.loadingDocumentFacts.set(true);
    this.api
      .listDocumentFacts({
        collection_name: this.kbId,
        semantic_type: this.documentFactType() || undefined,
        q: this.documentFactQuery() || undefined,
        limit: 160,
      })
      .pipe(catchError(() => of({ items: [] } as any)))
      .subscribe((payload) => {
        this.documentFacts.set(payload.items || []);
        this.loadingDocumentFacts.set(false);
      });
  }

  loadOcrFacts(): void {
    if (!this.kbId) return;
    this.loadingOcrFacts.set(true);
    const type = this.ocrFactType();
    const query = this.ocrFactQuery() || undefined;
    const request = type
      ? this.api.listDocumentFacts({
          collection_name: this.kbId,
          semantic_type: type,
          q: query,
          limit: 200,
        })
      : forkJoin([
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'document_ocr_text',
            q: query,
            limit: 120,
          }),
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'visual_text_block',
            q: query,
            limit: 120,
          }),
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'visual_parameter',
            q: query,
            limit: 80,
          }),
          this.api.listDocumentFacts({
            collection_name: this.kbId,
            semantic_type: 'visual_warning',
            q: query,
            limit: 80,
          }),
        ]).pipe(
          map((payloads) => ({
            items: payloads.flatMap((payload) => payload.items || []),
          })),
        );

    request
      .pipe(catchError(() => of({ items: [] } as any)))
      .subscribe((payload) => {
        this.ocrFacts.set(this.dedupeOcrFacts(payload.items || []));
        this.loadingOcrFacts.set(false);
      });
  }

  factKey(fact: TableFactItem, index: number): string {
    return `${fact.document_id || 'doc'}:${fact.chunk_index ?? index}:${fact.cell_ref || fact.cell_range || index}`;
  }

  documentFactKey(fact: DocumentFactItem, index: number): string {
    return [
      fact.document_id || 'doc',
      fact.semantic_type || 'fact',
      fact.page ?? '',
      fact.paragraph_index ?? '',
      fact.table_index ?? '',
      fact.subject || '',
      index,
    ].join(':');
  }

  ocrFactKey(fact: DocumentFactItem, index: number): string {
    return [
      fact.document_id || 'doc',
      fact.semantic_type || 'ocr',
      fact.page ?? '',
      this.ocrBoxLabel(fact),
      fact.content || fact.value_raw || '',
      index,
    ].join(':');
  }

  ocrProviderLabel(fact: DocumentFactItem): string {
    const qualifiers = this.asRecord(fact.qualifiers);
    const locator = this.asRecord(fact.evidence_locator);
    return this.toDisplayString(qualifiers['provider'] || qualifiers['model'] || locator['provider'] || locator['model']);
  }

  ocrConfidenceLabel(fact: DocumentFactItem): string {
    const value = this.ocrConfidenceValue(fact);
    return value === null ? '' : `${Math.round(value * 100)}%`;
  }

  ocrBoxLabel(fact: DocumentFactItem): string {
    const qualifiers = this.asRecord(fact.qualifiers);
    const locator = this.asRecord(fact.evidence_locator);
    const bbox = qualifiers['bbox'] || qualifiers['box'] || locator['bbox'] || locator['box'];
    if (Array.isArray(bbox)) {
      return bbox.map((value) => String(value)).join(', ');
    }
    return this.toDisplayString(bbox);
  }

  ocrWarningLabel(fact: DocumentFactItem): string {
    const qualifiers = this.asRecord(fact.qualifiers);
    const warning = qualifiers['warning'] || qualifiers['warnings'] || qualifiers['ocr_warning'];
    if (Array.isArray(warning)) return warning.map((item) => String(item)).join(' · ');
    return this.toDisplayString(warning);
  }

  private ocrConfidenceValue(fact: DocumentFactItem): number | null {
    const qualifiers = this.asRecord(fact.qualifiers);
    const locator = this.asRecord(fact.evidence_locator);
    const raw = fact.confidence ?? qualifiers['confidence'] ?? qualifiers['ocr_confidence'] ?? locator['confidence'];
    const value = Number(raw);
    if (!Number.isFinite(value)) return null;
    return value > 1 ? Math.max(0, Math.min(1, value / 100)) : Math.max(0, Math.min(1, value));
  }

  private dedupeOcrFacts(items: DocumentFactItem[]): DocumentFactItem[] {
    const seen = new Set<string>();
    const out: DocumentFactItem[] = [];
    for (const fact of items) {
      const key = [
        fact.document_id || '',
        fact.semantic_type || '',
        fact.page ?? '',
        this.ocrBoxLabel(fact),
        (fact.content || fact.value_raw || '').slice(0, 120),
      ].join(':');
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(fact);
    }
    return out;
  }

  private asRecord(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
  }

  private toDisplayString(value: unknown): string {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    return '';
  }

  loadGuideIntoEditor(guide: KnowledgeGuide): void {
    this.editingGuideKey.set(guide.guide_key);
    this.guideTitle.set(guide.title || this.defaultGuideTitle());
    this.guideMarkdown.set(guide.markdown || guide.snippet || '');
    this.guideError.set(null);
  }

  saveCollectionGuide(status: 'draft' | 'published'): void {
    if (!this.kbId) return;
    const title = this.guideTitle().trim() || this.defaultGuideTitle();
    const markdown = this.guideMarkdown().trim();
    if (!markdown) {
      this.guideError.set('Markdown content is required before saving a guide.');
      return;
    }
    this.savingGuide.set(true);
    this.guideError.set(null);
    const existingKey = this.editingGuideKey() || this.collectionGuideVersions()[0]?.guide_key || null;
    const request = existingKey
      ? this.api.updateKnowledgeGuide(existingKey, {
          target_type: 'collection',
          target_ref: this.kbId,
          title,
          markdown,
          status,
        })
      : this.api.createKnowledgeGuide({
          target_type: 'collection',
          target_ref: this.kbId,
          title,
          markdown,
          status,
        });

    request.subscribe({
      next: (guide) => {
        this.savingGuide.set(false);
        this.editingGuideKey.set(guide.guide_key);
        this.api
          .listKnowledgeGuides({ current_only: false })
          .pipe(catchError(() => of({ items: this.knowledgeGuides() })))
          .subscribe((payload) => {
            this.knowledgeGuides.set(payload.items || []);
          });
      },
      error: () => {
        this.savingGuide.set(false);
        this.guideError.set('Unable to save this Knowledge Guide.');
      },
    });
  }

  private hydrateGuideEditor(): void {
    const current = this.collectionGuideVersions().find((guide) => guide.is_current);
    if (current) {
      this.loadGuideIntoEditor(current);
      return;
    }
    this.editingGuideKey.set(null);
    this.guideTitle.set(this.defaultGuideTitle());
    this.guideMarkdown.set('');
  }

  private defaultGuideTitle(): string {
    return `${this.kbId || 'Collection'} Knowledge Guide`;
  }
}
