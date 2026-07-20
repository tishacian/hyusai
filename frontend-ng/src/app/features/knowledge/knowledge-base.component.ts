import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { RouterLink } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';
import { DrawerComponent } from '@app/shared/ui/drawer.component';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';

interface CollectionInfo {
  slug: string;
  name: string;
  chunks: number;
  docs: number;
  loading?: boolean;
}

interface CollectionItemPayload {
  slug?: string;
  name?: string;
  document_count?: number;
  source_count?: number;
  chunk_count?: number;
}

interface CollectionsPayload {
  collections?: string[];
  items?: CollectionItemPayload[];
  default?: string | null;
  vector_db_type?: string;
}

interface DocItem {
  document_id: string;
  filename: string;
  chunk_count?: number;
  mime_type?: string;
  uploaded_at?: string;
  size?: number;
}

interface DocumentListPayload {
  documents?: DocItem[];
  total?: number;
  offset?: number;
  limit?: number;
  has_more?: boolean;
}

interface SearchResult {
  score?: number;
  content?: string;
  text?: string;
  metadata?: Record<string, unknown> & { filename?: string; document_id?: string };
}

@Component({
  selector: 'app-knowledge-base',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    IconComponent,
    CkObjectHeaderComponent,
    EmptyStateComponent,
    StatusPulseComponent,
    DrawerComponent,
    ConfirmDialogComponent,
    RouterLink,
  ],
  template: `
    <ck-object-header
      eyebrow="Build · Knowledge"
      title="Knowledge"
      subtitle="Ingest documents and give every system fresh context."
      [kpis]="headerKpis()"
    >
      <button
        actions
        type="button"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        (click)="openGlobalSearch()"
      >
        <app-icon name="search" [size]="14" /> Search
      </button>
      <a
        actions
        routerLink="/knowledge/capture"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        title="Lancer une capture de connaissances"
      >
        <app-icon name="mic" [size]="14" /> Capture
      </a>
      <button
        actions
        type="button"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        [class.opacity-50]="collectionsError()"
        [class.cursor-not-allowed]="collectionsError()"
        [disabled]="!!collectionsError()"
        (click)="openCreateCollection()"
      >
        <app-icon name="folder-plus" [size]="14" /> New collection
      </button>
      <button
        actions
        type="button"
        (click)="openFilePicker(fileInput)"
        [class.opacity-50]="collectionsError()"
        [class.cursor-not-allowed]="collectionsError()"
        [disabled]="!!collectionsError()"
        class="ck-btn-primary inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
      >
        <app-icon name="cloud-upload" [size]="14" /> Upload
      </button>
    </ck-object-header>

    <!-- Dropzone -->
    <div
      class="relative rounded-md p-8 text-center mb-6 transition-colors group"
      [class.border-2]="true"
      [class.border-dashed]="true"
      [class.ck-drop-idle]="!dragging()"
      [class.ck-drop-active]="dragging()"
      [class.cursor-pointer]="!collectionsError()"
      [class.cursor-not-allowed]="collectionsError()"
      [class.opacity-60]="collectionsError()"
      (dragover)="onDragOver($event)"
      (dragleave)="onDragLeave($event)"
      (drop)="onDrop($event)"
      (click)="openFilePicker(fileInput)"
    >
      <input
        #fileInput
        type="file"
        multiple
        class="hidden"
        [disabled]="!!collectionsError()"
        (change)="onFileSelect($event)"
        accept=".pdf,.txt,.md,.docx,.csv,.json,.png,.jpg,.jpeg,.tif,.tiff,.webp"
      />
      <div class="flex items-center justify-center gap-4">
        <div
          class="w-12 h-12 rounded-md flex items-center justify-center shrink-0"
          style="background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-hot); color:var(--ck-signal-cool);"
        >
          <app-icon name="cloud-upload" [size]="22" />
        </div>
        <div class="text-left">
          <div class="text-sm font-medium" style="color:var(--ck-fg-1);">
            Drop files here or
            <span style="color:var(--ck-signal-cool);">click to browse</span>
            <span class="ml-2" style="color:var(--ck-fg-4);">→ target: </span>
            <select
              class="ck-field-select ck-field-select-inline ml-1"
              [(ngModel)]="uploadTarget"
              [disabled]="!!collectionsError()"
              (click)="$event.stopPropagation()"
            >
              <option value="documents">documents</option>
              @for (c of collections(); track c.slug) {
                @if (c.slug !== 'documents') {
                  <option [value]="c.slug">{{ c.name }}</option>
                }
              }
            </select>
          </div>
          <p class="text-xs mt-0.5" style="color:var(--ck-fg-4);">PDF · TXT · MD · DOCX · CSV · JSON</p>
        </div>
      </div>

      @if (uploading()) {
        <div
          class="absolute inset-x-4 bottom-3 flex items-center gap-2 justify-center text-xs"
          style="color:var(--ck-signal-cool);"
        >
          <app-icon name="loader-2" [size]="14" class="animate-spin" />
          Ingesting {{ uploadCount() }} file(s)…
        </div>
      }
    </div>

    <section
      class="ck-surface rounded-md p-5 mb-6"
      style="border-color:var(--ck-stroke-hot); background:linear-gradient(180deg, rgba(125, 211, 252, 0.05), transparent);"
    >
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <div class="ck-mono text-[10px] uppercase tracking-[0.14em]" style="color:var(--ck-signal-cool);">
            Capture de connaissances
          </div>
          <h2 class="text-base font-semibold" style="color:var(--ck-fg-1);">
            Préparer un échange et produire un rapport relu.
          </h2>
          <p class="text-sm max-w-3xl" style="color:var(--ck-fg-3);">
            Lancez une session, rattachez une collection documentaire et publiez un rapport final
            après relecture.
          </p>
        </div>
        <a
          routerLink="/knowledge/capture"
          class="ck-btn-primary shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
        >
          <app-icon name="arrow-right" [size]="14" /> Démarrer une capture
        </a>
      </div>
    </section>

    <!-- Collections -->
    @if (loadingCollections()) {
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (_ of [0, 1, 2, 3, 4, 5]; track $index) {
          <div class="ck-surface rounded-md p-5 animate-pulse">
            <div class="h-4 w-32 rounded mb-2" style="background:var(--ck-bg-inset);"></div>
            <div class="h-3 w-20 rounded" style="background:var(--ck-bg-inset);"></div>
          </div>
        }
      </div>
    } @else if (collectionsError()) {
      <div class="ck-surface rounded-md">
        <app-empty-state
          icon="circle-alert"
          title="Unable to load collections"
          [description]="collectionsError()!"
        >
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
            (click)="loadCollections()"
          >
            <app-icon name="refresh-cw" [size]="14" /> Retry
          </button>
        </app-empty-state>
      </div>
    } @else if (collections().length === 0) {
      <div class="ck-surface rounded-md">
        <app-empty-state
          icon="database"
          title="No collections yet"
          description="Upload your first document or create a collection to get started."
        />
      </div>
    } @else {
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (doc of collections(); track doc.slug) {
          <div class="ck-surface rounded-md p-5 group">
            <div class="flex items-start gap-3 mb-4">
              <div
                class="w-10 h-10 rounded-md flex items-center justify-center shrink-0"
                style="background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-hot); color:var(--ck-signal-cool);"
              >
                <app-icon name="folder" [size]="18" />
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="font-semibold truncate" style="color:var(--ck-fg-1);">{{ doc.name }}</h3>
                <div class="text-xs mt-0.5 flex items-center gap-3" style="color:var(--ck-fg-4);">
                  <span class="flex items-center gap-1">
                    <app-icon name="file-text" [size]="11" />
                    {{ doc.docs }} docs
                  </span>
                  <span class="flex items-center gap-1">
                    <app-icon name="braces" [size]="11" />
                    {{ doc.chunks }} chunks
                  </span>
                </div>
              </div>
            </div>

            <div class="flex items-center justify-between">
              <app-status-pulse tone="success" label="Indexed" />
              <div class="flex items-center gap-1">
                <a
                  [routerLink]="['/knowledge', doc.slug]"
                  class="ck-ghost-icon p-1.5 rounded inline-flex items-center"
                  title="Open collection detail"
                >
                  <app-icon name="external-link" [size]="14" />
                </a>
                <button
                  class="ck-ghost-icon p-1.5 rounded"
                  title="Browse documents"
                  (click)="openBrowse(doc.slug)"
                >
                  <app-icon name="folder" [size]="14" />
                </button>
                <button
                  class="ck-ghost-icon p-1.5 rounded"
                  title="Search in this collection"
                  (click)="openSearchIn(doc.slug)"
                >
                  <app-icon name="search" [size]="14" />
                </button>
                <button
                  class="ck-ghost-icon ck-ghost-icon-danger p-1.5 rounded"
                  title="Delete collection"
                  (click)="requestDeleteCollection(doc.slug)"
                >
                  <app-icon name="trash-2" [size]="14" />
                </button>
              </div>
            </div>
          </div>
        }
      </div>
    }

    <!-- Search drawer -->
    <app-drawer
      [open]="searchOpen()"
      title="Search knowledge"
      [subtitle]="searchCollection() || 'All collections'"
      icon="search"
      (close)="closeSearch()"
    >
      <form class="mb-3" (ngSubmit)="runSearch()">
        <div class="flex items-center gap-2">
          <select
            [(ngModel)]="searchCollectionDraft"
            name="scoll"
            class="ck-field-select px-2.5 py-2 text-xs"
          >
            <option value="">All</option>
            @for (c of collections(); track c.slug) {
              <option [value]="c.slug">{{ c.name }}</option>
            }
          </select>
          <input
            [(ngModel)]="searchQuery"
            name="sq"
            type="text"
            placeholder="Ask semantic question…"
            class="ck-field-input flex-1 rounded px-3 py-2 text-sm"
            autocomplete="off"
          />
          <button
            type="submit"
            class="ck-btn-primary rounded px-3 py-2 text-sm font-medium flex items-center gap-1.5"
            [disabled]="!searchQuery.trim() || searching()"
          >
            <app-icon [name]="searching() ? 'loader-2' : 'search'" [size]="14" [class.animate-spin]="searching()" />
            Search
          </button>
        </div>
        <label class="flex items-center gap-2 text-xs mt-2 cursor-pointer" style="color:var(--ck-fg-3);">
          <input type="checkbox" [(ngModel)]="useHybrid" name="sh" style="accent-color:var(--ck-signal-cool);" />
          Use hybrid (sparse + vector)
        </label>
      </form>

      @if (searchError() && !searching()) {
        <app-empty-state
          icon="circle-alert"
          title="Unable to search knowledge"
          [description]="searchError()!"
        />
      } @else if (searchResults().length === 0 && !searching() && searchAttempted()) {
        <app-empty-state icon="search" title="No results" description="Try a different query or disable hybrid." />
      }

      <ul class="space-y-2">
        @for (r of searchResults(); track $index) {
          <li class="ck-inset rounded p-3">
            <div class="flex items-center justify-between mb-1">
              <div class="text-[11px] truncate flex items-center gap-1" style="color:var(--ck-fg-4);">
                <app-icon name="file-text" [size]="11" />
                {{ r.metadata?.filename ?? 'unknown' }}
              </div>
              @if (isNum(r.score)) {
                <span
                  class="text-[10px] font-mono px-1.5 py-0.5 rounded"
                  style="background:rgba(125, 211, 252, 0.12); color:var(--ck-signal-cool);"
                >
                  {{ r.score!.toFixed(3) }}
                </span>
              }
            </div>
            <div class="text-xs leading-relaxed line-clamp-5" style="color:var(--ck-fg-2);">
              {{ r.content || r.text }}
            </div>
          </li>
        }
      </ul>
    </app-drawer>

    <!-- Browse drawer -->
    <app-drawer
      [open]="browseOpen()"
      title="Documents"
      [subtitle]="browseCollection()"
      icon="folder"
      (close)="browseOpen.set(false)"
    >
      @if (browseLoading()) {
        <div class="space-y-2">
          @for (_ of [0, 1, 2, 3]; track $index) {
            <div class="h-10 rounded animate-pulse" style="background:var(--ck-bg-inset);"></div>
          }
        </div>
      } @else if (browseError()) {
        <app-empty-state
          icon="circle-alert"
          title="Unable to load documents"
          [description]="browseError()!"
        >
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
            (click)="loadBrowsePage(browseOffset())"
          >
            <app-icon name="refresh-cw" [size]="14" /> Retry
          </button>
        </app-empty-state>
      } @else if (browseDocs().length === 0) {
        <app-empty-state icon="file-text" title="Empty collection" description="Upload documents to this collection." />
      } @else {
        <div class="mb-3 flex items-center justify-between gap-2 text-xs" style="color:var(--ck-fg-3);">
          <span class="font-mono">
            {{ browseOffset() + 1 }}–{{ browseOffset() + browseDocs().length }} / {{ browseTotal() }}
          </span>
          <div class="flex items-center gap-1.5">
            <button
              type="button"
              title="Previous page"
              aria-label="Previous page"
              class="ck-iconbtn h-7 w-7"
              [disabled]="browseLoading() || browseOffset() === 0"
              (click)="loadBrowsePage(browseOffset() > browsePageSize ? browseOffset() - browsePageSize : 0)"
            >
              <app-icon name="chevron-left" [size]="13" />
            </button>
            <button
              type="button"
              title="Next page"
              aria-label="Next page"
              class="ck-iconbtn h-7 w-7"
              [disabled]="browseLoading() || !browseHasMore()"
              (click)="loadBrowsePage(browseOffset() + browsePageSize)"
            >
              <app-icon name="chevron-right" [size]="13" />
            </button>
          </div>
        </div>
        <ul class="space-y-2">
          @for (d of browseDocs(); track d.document_id) {
            <li
              class="ck-inset flex items-center justify-between gap-2 text-sm px-3 py-2 rounded group"
              style="color:var(--ck-fg-2);"
            >
              <div class="flex-1 min-w-0">
                <div class="truncate">{{ d.filename }}</div>
                <div class="text-[11px] font-mono" style="color:var(--ck-fg-4);">
                  {{ d.chunk_count ?? 0 }} chunks
                  @if (d.mime_type) {
                    <span class="mx-1">·</span>{{ d.mime_type }}
                  }
                </div>
              </div>
              <div class="flex items-center gap-0.5 shrink-0 opacity-70 group-hover:opacity-100">
                <button
                  class="ck-ghost-icon p-1.5 rounded"
                  title="Preview"
                  (click)="previewDoc(d)"
                >
                  <app-icon name="eye" [size]="13" />
                </button>
                <button
                  class="ck-ghost-icon ck-ghost-icon-danger p-1.5 rounded"
                  title="Delete document"
                  (click)="requestDeleteDoc(d)"
                >
                  <app-icon name="trash-2" [size]="13" />
                </button>
              </div>
            </li>
          }
        </ul>
      }
    </app-drawer>

    <!-- Preview drawer -->
    <app-drawer
      [open]="previewOpen()"
      [title]="previewDocItem()?.filename ?? ''"
      subtitle="Document preview"
      icon="eye"
      (close)="previewOpen.set(false)"
    >
      @if (previewLoading()) {
        <div class="space-y-2">
          @for (_ of [0, 1, 2, 3, 4, 5, 6]; track $index) {
            <div class="h-3 rounded animate-pulse" style="background:var(--ck-bg-inset);"></div>
          }
        </div>
      } @else if (previewError()) {
        <div class="text-sm" style="color:var(--ck-signal-neg);">{{ previewError() }}</div>
      } @else if (previewDownloadUrl()) {
        <div class="text-sm mb-3" style="color:var(--ck-fg-2);">
          This document is a binary file. Open or download it to view.
        </div>
        <a
          [href]="previewDownloadUrl()!"
          target="_blank"
          rel="noreferrer"
          class="ck-btn-primary inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
        >
          <app-icon name="external-link" [size]="14" /> Open file
        </a>
      } @else {
        <pre
          class="ck-scroll text-[11px] leading-relaxed whitespace-pre-wrap font-mono rounded p-3 max-h-[70vh] overflow-auto"
          style="background:var(--ck-bg-code); color:var(--ck-fg-2); border:1px solid var(--ck-stroke-2);"
        >{{ previewContent() }}</pre>
      }
    </app-drawer>

    <!-- Create collection dialog -->
    @if (createOpen()) {
      <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 backdrop-blur-sm" style="background:var(--ck-scrim);" (click)="createOpen.set(false)"></div>
        <div
          class="ck-surface-hi relative max-w-md w-full p-6"
          style="border-radius:var(--ck-radius-lg); box-shadow:var(--ck-shadow-panel);"
        >
          <div class="flex items-start gap-4 mb-4">
            <div
              class="w-10 h-10 rounded-md flex items-center justify-center shrink-0"
              style="background:rgba(125, 211, 252, 0.15); color:var(--ck-signal-cool);"
            >
              <app-icon name="folder-plus" [size]="20" />
            </div>
            <div class="flex-1">
              <h2 class="text-base font-semibold mb-1" style="color:var(--ck-fg-1);">New collection</h2>
              <p class="text-sm" style="color:var(--ck-fg-3);">
                Collections isolate your documents. Names are workspace-scoped.
              </p>
            </div>
          </div>
          <input
            type="text"
            [(ngModel)]="newCollectionDraftValue"
            placeholder="e.g. policies, research"
            class="ck-field-input w-full px-3 py-2 rounded text-sm"
            (keyup.enter)="createCollection()"
            autofocus
          />
          <div class="mt-6 flex justify-end gap-2">
            <button
              type="button"
              (click)="createOpen.set(false)"
              class="ck-btn-ghost px-4 py-2 text-sm rounded"
            >
              Cancel
            </button>
            <button
              type="button"
              (click)="createCollection()"
              [disabled]="!newCollectionDraftValue.trim() || creating()"
              class="ck-btn-primary px-4 py-2 text-sm font-medium rounded flex items-center gap-1.5"
            >
              <app-icon
                [name]="creating() ? 'loader-2' : 'plus'"
                [size]="14"
                [class.animate-spin]="creating()"
              />
              Create
            </button>
          </div>
        </div>
      </div>
    }

    <app-confirm-dialog
      [open]="deleteCollectionTarget() !== null"
      [title]="'Delete collection ' + (deleteCollectionTarget() ?? '')"
      description="All documents and chunks in this collection will be deleted. This cannot be undone."
      [confirmPhrase]="deleteCollectionTarget() ?? ''"
      confirmLabel="Delete collection"
      tone="danger"
      (confirm)="confirmDeleteCollection()"
      (cancel)="deleteCollectionTarget.set(null)"
    />

    <app-confirm-dialog
      [open]="deleteDocTarget() !== null"
      [title]="'Delete ' + (deleteDocTarget()?.filename ?? '')"
      description="This document and its chunks will be removed from the collection."
      confirmLabel="Delete"
      tone="danger"
      (confirm)="confirmDeleteDoc()"
      (cancel)="deleteDocTarget.set(null)"
    />
  `,
  styles: [`
    /* Cockpit DS-C — component-scoped helpers (token-driven; mirrors auth/exemplar pattern). */
    .ck-field-input,
    .ck-field-select,
    .ck-field-textarea {
      background: var(--ck-bg-inset);
      border: 1px solid var(--ck-stroke-2);
      border-radius: var(--ck-radius-sm);
      color: var(--ck-fg-1);
      font-family: var(--ck-font-sans);
      outline: none;
      transition:
        border-color var(--ck-dur-fast) var(--ck-ease-out),
        box-shadow var(--ck-dur-fast) var(--ck-ease-out),
        background var(--ck-dur-fast) var(--ck-ease-out);
    }
    .ck-field-input::placeholder,
    .ck-field-textarea::placeholder { color: var(--ck-fg-4); }
    .ck-field-input:focus,
    .ck-field-select:focus,
    .ck-field-textarea:focus {
      border-color: var(--ck-stroke-hot);
      background: var(--ck-bg-panel-hi);
      box-shadow: 0 0 0 1px var(--ck-signal-cool);
    }
    .ck-field-textarea { font-family: var(--ck-font-mono); }
    .ck-field-select {
      appearance: none;
      -webkit-appearance: none;
      padding-left: 0.625rem;
      padding-right: 1.75rem;
      background-image:
        linear-gradient(45deg, transparent 50%, var(--ck-fg-4) 50%),
        linear-gradient(135deg, var(--ck-fg-4) 50%, transparent 50%);
      background-position: calc(100% - 14px) 50%, calc(100% - 9px) 50%;
      background-size: 5px 5px, 5px 5px;
      background-repeat: no-repeat;
    }

    .ck-btn-soft,
    .ck-btn-primary {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.375rem;
      border-radius: var(--ck-radius-sm);
      cursor: pointer;
      transition:
        background var(--ck-dur-fast) var(--ck-ease-out),
        color var(--ck-dur-fast) var(--ck-ease-out),
        border-color var(--ck-dur-fast) var(--ck-ease-out);
    }
    .ck-btn-soft {
      background: var(--ck-bg-panel-hi);
      border: 1px solid var(--ck-stroke-2);
      color: var(--ck-fg-2);
    }
    .ck-btn-soft:hover:not(:disabled) {
      background: var(--ck-bg-inset);
      color: var(--ck-fg-1);
      border-color: var(--ck-stroke-3);
    }
    .ck-btn-soft:disabled { opacity: 0.4; cursor: not-allowed; }
    .ck-btn-primary {
      background: linear-gradient(180deg, rgba(125, 211, 252, 0.22), rgba(125, 211, 252, 0.12));
      border: 1px solid var(--ck-stroke-hot);
      color: var(--ck-fg-1);
      font-weight: 600;
    }
    .ck-btn-primary:hover:not(:disabled) {
      background: linear-gradient(180deg, rgba(125, 211, 252, 0.30), rgba(125, 211, 252, 0.18));
      border-color: rgba(125, 211, 252, 0.55);
    }
    .ck-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

    .ck-btn-ghost {
      background: transparent;
      border: 0;
      color: var(--ck-fg-3);
      border-radius: var(--ck-radius-sm);
      cursor: pointer;
      transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
    }
    .ck-btn-ghost:hover:not(:disabled) { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }

    .ck-iconbtn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--ck-radius-sm);
      background: var(--ck-bg-panel-hi);
      border: 1px solid var(--ck-stroke-2);
      color: var(--ck-fg-3);
      cursor: pointer;
      transition:
        background var(--ck-dur-fast) var(--ck-ease-out),
        color var(--ck-dur-fast) var(--ck-ease-out);
    }
    .ck-iconbtn:hover:not(:disabled) { background: var(--ck-bg-inset); color: var(--ck-fg-1); }
    .ck-iconbtn:disabled { opacity: 0.4; cursor: not-allowed; }
    .ck-iconbtn-danger:hover:not(:disabled) { color: var(--ck-signal-neg); }

    .ck-ghost-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--ck-fg-3);
      border-radius: var(--ck-radius-sm);
      cursor: pointer;
      transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
    }
    .ck-ghost-icon:hover { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }
    .ck-ghost-icon-danger:hover { color: var(--ck-signal-neg); }

    .ck-divide > * + * { border-top: 1px solid var(--ck-stroke-2); }
    .ck-rowi { transition: background var(--ck-dur-fast) var(--ck-ease-out); }
    .ck-rowi:hover { background: var(--ck-bg-panel-hi); }

    /* Knowledge index — dropzone + inline select. */
    .ck-drop-idle { border-color: var(--ck-stroke-2); background: transparent; }
    .ck-drop-active { border-color: var(--ck-stroke-hot); background: rgba(125, 211, 252, 0.06); }
    .ck-field-select-inline {
      min-height: 1.5rem;
      padding-top: 0.125rem;
      padding-bottom: 0.125rem;
      font-size: 0.6875rem;
    }
  `],
})
export class KnowledgeBaseComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly toast = inject(ToastrService);

  private readonly base = '/api/v1/documents';

  // Collections
  collections = signal<CollectionInfo[]>([]);
  loadingCollections = signal(false);
  collectionsError = signal<string | null>(null);
  vectorDbType = signal<string>('');

  uploading = signal(false);
  uploadCount = signal(0);
  dragging = signal(false);
  uploadTarget = 'documents';

  // Create collection
  createOpen = signal(false);
  newCollectionDraft = signal('');
  newCollectionDraftValue = '';
  creating = signal(false);

  // Delete collection
  deleteCollectionTarget = signal<string | null>(null);

  // Browse
  browseOpen = signal(false);
  browseCollection = signal<string>('');
  browseDocs = signal<DocItem[]>([]);
  browseLoading = signal(false);
  browseError = signal<string | null>(null);
  browseTotal = signal(0);
  browseOffset = signal(0);
  browseHasMore = signal(false);
  readonly browsePageSize = 100;

  // Preview
  previewOpen = signal(false);
  previewDocItem = signal<DocItem | null>(null);
  previewLoading = signal(false);
  previewContent = signal<string>('');
  previewDownloadUrl = signal<string | null>(null);
  previewError = signal<string | null>(null);

  // Delete doc
  deleteDocTarget = signal<DocItem | null>(null);

  // Search
  searchOpen = signal(false);
  searchCollection = signal<string>('');
  searchCollectionDraft = '';
  searchQuery = '';
  useHybrid = true;
  searching = signal(false);
  searchAttempted = signal(false);
  searchError = signal<string | null>(null);
  searchResults = signal<SearchResult[]>([]);

  readonly totalDocs = computed(() =>
    this.collections().reduce((acc, c) => acc + (c.docs || 0), 0),
  );
  readonly totalChunks = computed(() =>
    this.collections().reduce((acc, c) => acc + (c.chunks || 0), 0),
  );
  readonly indexingLabel = computed(() =>
    this.loadingCollections() ? 'indexing…' : 'ready',
  );

  readonly headerKpis = computed<CkObjectKpi[]>(() => [
    {
      label: 'Collections',
      value: String(this.collections().length),
      tone: 'cool',
      hint: 'Total number of collections in this workspace.',
    },
    {
      label: 'Documents',
      value: String(this.totalDocs()),
      tone: 'neutral',
      hint: 'Aggregate document count across all collections.',
    },
    {
      label: 'Chunks',
      value: String(this.totalChunks()),
      tone: 'neutral',
      hint: 'Aggregate chunk count — the indexing unit.',
    },
    {
      label: 'Vector DB',
      value: this.vectorDbType() || '—',
      tone: 'violet',
      hint: this.indexingLabel(),
    },
  ]);

  ngOnInit(): void {
    this.loadCollections();
  }

  loadCollections(): void {
    this.loadingCollections.set(true);
    this.http
      .get<CollectionsPayload>(
        `${this.base}/collections`,
      )
      .subscribe({
        next: (res) => {
          this.collectionsError.set(null);
          const names = res?.collections ?? [];
          this.vectorDbType.set(res?.vector_db_type ?? '');
          const items = res?.items ?? [];
          if (names.length === 0 && items.length === 0) {
            this.collections.set([]);
            this.loadingCollections.set(false);
            return;
          }
          const bySlug = new Map(items.map((item) => [item.slug || item.name || '', item]));
          const displayItems = names.length ? names.map((name) => bySlug.get(name) ?? { slug: name }) : items;
          const infos: CollectionInfo[] = displayItems.map((item) => {
            const slug = item.slug || item.name || '';
            return {
              slug,
              name: item.name || slug,
              chunks: item.chunk_count ?? 0,
              docs: item.source_count ?? item.document_count ?? 0,
              loading: false,
            };
          }).filter((item) => !!item.slug);
          this.collections.set(infos);
          this.loadingCollections.set(false);
        },
        error: (err) => {
          this.collections.set([]);
          this.vectorDbType.set('');
          this.collectionsError.set(
            err?.error?.detail || 'Collections could not be loaded. Retry before creating, deleting or uploading documents.',
          );
          this.loadingCollections.set(false);
        },
      });
  }

  onDragOver(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(true);
  }

  onDragLeave(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
  }

  onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    const files = e.dataTransfer?.files;
    if (files && files.length) this.uploadFiles(files);
  }

  onFileSelect(e: Event): void {
    const input = e.target as HTMLInputElement;
    if (input.files && input.files.length) this.uploadFiles(input.files);
    input.value = '';
  }

  private uploadFiles(files: FileList): void {
    if (this.collectionsError()) {
      this.toast.error('Retry loading collections before uploading documents.', 'Knowledge');
      return;
    }
    this.uploading.set(true);
    this.uploadCount.set(files.length);
    const formData = new FormData();
    Array.from(files).forEach((f) => formData.append('files', f));
    formData.append('collection_name', this.uploadTarget || 'documents');

    this.http.post<{ total: number; successful: number; failed: number }>(
      `${this.base}/upload-batch`,
      formData,
    ).subscribe({
      next: (res) => {
        this.uploading.set(false);
        if (res.failed > 0) {
          this.toast.warning(
            `${res.successful}/${res.total} ingested · ${res.failed} failed`,
            'Upload partial',
          );
        } else {
          this.toast.success(`${res.successful} file(s) ingested`, 'Upload complete');
        }
        this.loadCollections();
      },
      error: (err) => {
        this.uploading.set(false);
        this.toast.error(err?.error?.detail || 'Failed to upload', 'Upload error');
      },
    });
  }

  createCollection(): void {
    if (this.collectionsError()) {
      this.toast.error('Retry loading collections before creating a collection.', 'Knowledge');
      return;
    }
    const name = this.newCollectionDraftValue.trim();
    if (!name) return;
    this.creating.set(true);
    this.http
      .post<{ status: string }>(
        `${this.base}/collections?collection_name=${encodeURIComponent(name)}`,
        {},
      )
      .subscribe({
        next: () => {
          this.toast.success(`Collection "${name}" created`, 'Knowledge');
          this.creating.set(false);
          this.createOpen.set(false);
          this.newCollectionDraftValue = '';
          this.loadCollections();
        },
        error: (err) => {
          this.toast.error(err?.error?.detail || 'Failed to create', 'Knowledge');
          this.creating.set(false);
        },
      });
  }

  openCreateCollection(): void {
    if (this.collectionsError()) {
      this.toast.error('Retry loading collections before creating a collection.', 'Knowledge');
      return;
    }
    this.newCollectionDraft.set('');
    this.createOpen.set(true);
  }

  openFilePicker(input: HTMLInputElement): void {
    if (this.collectionsError()) {
      this.toast.error('Retry loading collections before uploading documents.', 'Knowledge');
      return;
    }
    input.click();
  }

  requestDeleteCollection(name: string): void {
    this.deleteCollectionTarget.set(name);
  }

  confirmDeleteCollection(): void {
    const name = this.deleteCollectionTarget();
    if (!name) return;
    this.http
      .delete<{ status: string }>(`${this.base}/collections/${encodeURIComponent(name)}`)
      .subscribe({
        next: () => {
          this.toast.success(`Collection "${name}" deleted`, 'Knowledge');
          this.deleteCollectionTarget.set(null);
          this.loadCollections();
        },
        error: (err) => {
          this.toast.error(err?.error?.detail || 'Failed to delete', 'Knowledge');
          this.deleteCollectionTarget.set(null);
        },
      });
  }

  openBrowse(name: string): void {
    this.browseCollection.set(name);
    this.browseOpen.set(true);
    this.browseDocs.set([]);
    this.browseError.set(null);
    this.browseTotal.set(0);
    this.browseOffset.set(0);
    this.browseHasMore.set(false);
    this.loadBrowsePage(0);
  }

  loadBrowsePage(offset: number): void {
    const name = this.browseCollection();
    if (!name) return;
    const safeOffset = Math.max(0, offset);
    this.browseLoading.set(true);
    this.browseError.set(null);
    this.http
      .get<DocumentListPayload>(
        `${this.base}/list?collection_name=${encodeURIComponent(name)}&limit=${this.browsePageSize}&offset=${safeOffset}`,
      )
      .subscribe({
        next: (res) => {
          this.browseError.set(null);
          this.browseDocs.set(res?.documents ?? []);
          this.browseTotal.set(res?.total ?? 0);
          this.browseOffset.set(res?.offset ?? safeOffset);
          this.browseHasMore.set(!!res?.has_more);
          this.browseLoading.set(false);
        },
        error: (err) => {
          this.browseDocs.set([]);
          this.browseTotal.set(0);
          this.browseOffset.set(safeOffset);
          this.browseHasMore.set(false);
          this.browseError.set(
            err?.error?.detail || 'Documents could not be loaded. Retry before previewing or deleting files.',
          );
          this.browseLoading.set(false);
        },
      });
  }

  previewDoc(d: DocItem): void {
    this.previewDocItem.set(d);
    this.previewOpen.set(true);
    this.previewLoading.set(true);
    this.previewContent.set('');
    this.previewDownloadUrl.set(null);
    this.previewError.set(null);
    const col = this.browseCollection();
    this.http
      .get<{ content?: string; download_url?: string; content_type?: string }>(
        `${this.base}/preview/${encodeURIComponent(d.document_id)}?collection_name=${encodeURIComponent(col)}`,
      )
      .subscribe({
        next: (res) => {
          if (res.download_url) this.previewDownloadUrl.set(res.download_url);
          else this.previewContent.set(res.content ?? '');
          this.previewLoading.set(false);
        },
        error: (err) => {
          this.previewError.set(err?.error?.detail ?? 'Could not load preview');
          this.previewLoading.set(false);
        },
      });
  }

  requestDeleteDoc(d: DocItem): void {
    this.deleteDocTarget.set(d);
  }

  confirmDeleteDoc(): void {
    const d = this.deleteDocTarget();
    if (!d) return;
    const col = this.browseCollection();
    this.http
      .delete<unknown>(
        `${this.base}/${encodeURIComponent(d.document_id)}?collection_name=${encodeURIComponent(col)}`,
      )
      .subscribe({
        next: () => {
          this.toast.success(`"${d.filename}" deleted`, 'Knowledge');
          this.browseDocs.update((list) => list.filter((x) => x.document_id !== d.document_id));
          this.deleteDocTarget.set(null);
          this.loadCollections();
        },
        error: (err) => {
          this.toast.error(err?.error?.detail || 'Failed to delete', 'Knowledge');
          this.deleteDocTarget.set(null);
        },
      });
  }

  openSearchIn(name: string): void {
    this.resetSearchState();
    this.searchCollection.set(name);
    this.searchCollectionDraft = name;
    this.searchOpen.set(true);
  }

  openGlobalSearch(): void {
    this.resetSearchState();
    this.searchCollection.set('');
    this.searchCollectionDraft = '';
    this.searchOpen.set(true);
  }

  closeSearch(): void {
    this.searchOpen.set(false);
    this.searchCollection.set('');
    this.searchCollectionDraft = '';
  }

  private resetSearchState(): void {
    this.searchQuery = '';
    this.searching.set(false);
    this.searchAttempted.set(false);
    this.searchError.set(null);
    this.searchResults.set([]);
  }

  runSearch(): void {
    const q = this.searchQuery.trim();
    if (!q) return;
    this.searching.set(true);
    this.searchAttempted.set(true);
    this.searchError.set(null);
    this.searchResults.set([]);
    const col = this.searchCollectionDraft || this.searchCollection() || 'documents';
    this.http
      .post<{ results: SearchResult[] }>(`${this.base}/search`, {
        query: q,
        top_k: 10,
        collection_name: col,
        use_hybrid: this.useHybrid,
      })
      .subscribe({
        next: (res) => {
          this.searchError.set(null);
          this.searchResults.set(res?.results ?? []);
          this.searching.set(false);
        },
        error: (err) => {
          const message = err?.error?.detail || 'Search failed. Retry before using results.';
          this.searchResults.set([]);
          this.searchError.set(message);
          this.toast.error(message, 'Knowledge');
          this.searching.set(false);
        },
      });
  }

  isNum(v: unknown): boolean {
    return typeof v === 'number' && !Number.isNaN(v);
  }
}
