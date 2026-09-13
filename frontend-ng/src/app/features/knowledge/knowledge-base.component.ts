import { HelpTooltipComponent } from '@app/shared/cockpit/help-tooltip.component';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { ProductTelemetryService } from '@app/core/product-telemetry.service';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { NavLinkDirective } from '@app/shared/cockpit';
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
  imports: [HelpTooltipComponent,
    FormsModule,
    IconComponent,
    CkObjectHeaderComponent,
    EmptyStateComponent,
    StatusPulseComponent,
    DrawerComponent,
    ConfirmDialogComponent,
    NavLinkDirective,
  ],
  template: `

    <ck-object-header
      [eyebrow]="i18n.t('knowledge.header.eyebrow')"
      [title]="i18n.t('knowledge.title')"
      [subtitle]="i18n.t('knowledge.header.subtitle')"
      [kpis]="headerKpis()"
    >
      <ck-help actions id="adoption.sources" />
      @if (totalDocs() > 0) {
        <a
          actions
          [navLink]="{ surface: 'chat' }"
          class="ck-btn-primary inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        >
          <app-icon name="message-circle" [size]="14" /> {{ i18n.t('knowledge.ask.cta') }}
        </a>
      }
      <button
        actions
        type="button"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        [attr.aria-expanded]="advancedOpen()"
        (click)="advancedOpen.set(!advancedOpen())"
      >
        <app-icon name="sliders" [size]="14" />
        {{ advancedOpen() ? i18n.t('knowledge.advanced.hide') : i18n.t('knowledge.advanced.show') }}
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
            {{ i18n.t('knowledge.dropzone.prefix') }}
            <span style="color:var(--ck-signal-cool);">{{ i18n.t('knowledge.dropzone.browse') }}</span>
            @if (advancedOpen()) {
              <span class="ml-2" style="color:var(--ck-fg-4);">{{ i18n.t('knowledge.dropzone.target') }} </span>
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
            }
          </div>
          <p class="text-xs mt-0.5" style="color:var(--ck-fg-4);">{{ i18n.t('knowledge.dropzone.formats') }}</p>
        </div>
      </div>

      @if (uploading()) {
        <div
          class="absolute inset-x-4 bottom-3 flex items-center gap-2 justify-center text-xs"
          style="color:var(--ck-signal-cool);"
        >
          <app-icon name="loader-2" [size]="14" class="animate-spin" />
          {{ i18n.t('knowledge.upload.progress', { count: uploadCount() }) }}
        </div>
      }
    </div>

    @if (uploadState() !== 'idle') {
      <section
        class="ck-surface rounded-md px-4 py-3 mb-6 flex flex-col sm:flex-row sm:items-center gap-3"
        aria-live="polite"
      >
        <app-status-pulse
          [tone]="uploadState() === 'ready' ? 'success' : uploadState() === 'uploading' ? 'accent' : 'warning'"
          [label]="i18n.t(uploadStatusKey(), { count: uploadCount() })"
        />
        <p class="text-sm flex-1" style="color:var(--ck-fg-3);">{{ i18n.t(uploadMessageKey()) }}</p>
        @if (uploadState() === 'ready' || uploadState() === 'partial') {
          <a
            [navLink]="{ surface: 'chat' }"
            class="ck-btn-primary inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
          >
            <app-icon name="message-circle" [size]="14" /> {{ i18n.t('knowledge.ask.cta') }}
          </a>
        } @else if (uploadState() === 'error') {
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
            (click)="openFilePicker(fileInput)"
          >
            <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('common.retry') }}
          </button>
        }
      </section>
    }

    @if (advancedOpen()) {
    <section
      class="ck-surface rounded-md p-5 mb-6"
      style="border-color:var(--ck-stroke-hot); background:linear-gradient(180deg, rgba(125, 211, 252, 0.05), transparent);"
    >
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <div class="ck-mono text-[10px] uppercase tracking-[0.14em]" style="color:var(--ck-signal-cool);">
            {{ i18n.t('capture.title') }}
          </div>
          <h2 class="text-base font-semibold" style="color:var(--ck-fg-1);">
            {{ i18n.t('capture.kb.pitch_title') }}
          </h2>
          <p class="text-sm max-w-3xl" style="color:var(--ck-fg-3);">
            {{ i18n.t('capture.kb.pitch_body') }}
          </p>
        </div>
        <a
          [navLink]="{ surface: 'knowledge-capture' }"
          class="ck-btn-primary shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
        >
          <app-icon name="arrow-right" [size]="14" /> {{ i18n.t('capture.kb.start_capture') }}
        </a>
      </div>
    </section>
    }

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
          [title]="i18n.t('knowledge.collections.error.title')"
          [description]="collectionsError()!"
        >
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
            (click)="loadCollections()"
          >
            <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('common.retry') }}
          </button>
        </app-empty-state>
      </div>
    } @else if (collections().length === 0) {
      <div class="ck-surface rounded-md">
        <app-empty-state
          icon="database"
          [title]="i18n.t('knowledge.collections.empty.title')"
          [description]="i18n.t('knowledge.collections.empty.description')"
        ><a class="ck-btn-soft" [navLink]="{leaf:'help-guide',params:{guideId:'sources'}}">{{i18n.t('experience.adoption.documents')}}</a></app-empty-state>
      </div>
    } @else if (!advancedOpen()) {
      <section class="ck-surface rounded-md p-5">
        <div class="flex flex-col sm:flex-row sm:items-center gap-4">
          <div
            class="w-10 h-10 rounded-md flex items-center justify-center shrink-0"
            style="background:var(--ck-bg-inset); border:1px solid var(--ck-stroke-hot); color:var(--ck-signal-cool);"
          >
            <app-icon name="file-text" [size]="18" />
          </div>
          <div class="flex-1 min-w-0">
            <h2 class="text-base font-semibold" style="color:var(--ck-fg-1);">
              {{ i18n.t('knowledge.library.title') }}
            </h2>
            <p class="text-sm mt-1" style="color:var(--ck-fg-3);">
              {{ i18n.t('knowledge.library.summary', { count: totalDocs() }) }}
            </p>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
              (click)="openBrowse(defaultCollectionSlug())"
            >
              <app-icon name="folder" [size]="14" /> {{ i18n.t('knowledge.library.review') }}
            </button>
            <a
              [navLink]="{ surface: 'chat' }"
              class="ck-btn-primary inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
            >
              <app-icon name="message-circle" [size]="14" /> {{ i18n.t('knowledge.ask.cta') }}
            </a>
          </div>
        </div>
      </section>
    } @else {
      <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p class="text-xs" style="color:var(--ck-fg-4);">{{ i18n.t('knowledge.advanced.description') }}</p>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
            (click)="openGlobalSearch()"
          >
            <app-icon name="search" [size]="14" /> {{ i18n.t('common.search') }}
          </button>
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
            (click)="openCreateCollection()"
          >
            <app-icon name="folder-plus" [size]="14" /> {{ i18n.t('knowledge.collections.new') }}
          </button>
        </div>
      </div>
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
                    {{ i18n.t('knowledge.collections.docs_count', { count: doc.docs }) }}
                  </span>
                  <span class="flex items-center gap-1">
                    <app-icon name="braces" [size]="11" />
                    {{ i18n.t('knowledge.collections.chunks_count', { count: doc.chunks }) }}
                  </span>
                </div>
              </div>
            </div>

            <div class="flex items-center justify-between">
              <app-status-pulse tone="success" [label]="i18n.t('knowledge.collections.indexed')" />
              <div class="flex items-center gap-1">
                <a
                  [navLink]="{ leaf: 'knowledge-doc', ref: doc.slug }"
                  class="ck-ghost-icon p-1.5 rounded inline-flex items-center"
                  [title]="i18n.t('knowledge.collections.open_detail')"
                >
                  <app-icon name="external-link" [size]="14" />
                </a>
                <button
                  class="ck-ghost-icon p-1.5 rounded"
                  [title]="i18n.t('knowledge.collections.browse')"
                  (click)="openBrowse(doc.slug)"
                >
                  <app-icon name="folder" [size]="14" />
                </button>
                <button
                  class="ck-ghost-icon p-1.5 rounded"
                  [title]="i18n.t('knowledge.collections.search_in')"
                  (click)="openSearchIn(doc.slug)"
                >
                  <app-icon name="search" [size]="14" />
                </button>
                <button
                  class="ck-ghost-icon ck-ghost-icon-danger p-1.5 rounded"
                  [title]="i18n.t('knowledge.collections.delete')"
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
      [title]="i18n.t('knowledge.search.title')"
      [subtitle]="searchCollection() || i18n.t('knowledge.search.all_collections')"
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
            <option value="">{{ i18n.t('common.all') }}</option>
            @for (c of collections(); track c.slug) {
              <option [value]="c.slug">{{ c.name }}</option>
            }
          </select>
          <input
            [(ngModel)]="searchQuery"
            name="sq"
            type="text"
            [placeholder]="i18n.t('knowledge.search.placeholder')"
            class="ck-field-input flex-1 rounded px-3 py-2 text-sm"
            autocomplete="off"
          />
          <button
            type="submit"
            class="ck-btn-primary rounded px-3 py-2 text-sm font-medium flex items-center gap-1.5"
            [disabled]="!searchQuery.trim() || searching()"
          >
            <app-icon [name]="searching() ? 'loader-2' : 'search'" [size]="14" [class.animate-spin]="searching()" />
            {{ i18n.t('common.search') }}
          </button>
        </div>
        <label class="flex items-center gap-2 text-xs mt-2 cursor-pointer" style="color:var(--ck-fg-3);">
          <input type="checkbox" [(ngModel)]="useHybrid" name="sh" style="accent-color:var(--ck-signal-cool);" />
          {{ i18n.t('knowledge.search.hybrid') }}
        </label>
      </form>

      @if (searchError() && !searching()) {
        <app-empty-state
          icon="circle-alert"
          [title]="i18n.t('knowledge.search.error.title')"
          [description]="searchError()!"
        ><button type="button" class="ck-btn-soft" (click)="runSearch()">{{i18n.t('common.retry')}}</button><a [navLink]="{leaf:'help-guide',params:{guideId:'sources'}}">{{i18n.t('experience.adoption.documents')}}</a></app-empty-state>
      } @else if (searchResults().length === 0 && !searching() && searchAttempted()) {
        <app-empty-state
          icon="search"
          [title]="i18n.t('knowledge.search.empty.title')"
          [description]="i18n.t('knowledge.search.empty.description')"
        ><a class="ck-btn-soft" [navLink]="{leaf:'help-guide',params:{guideId:'sources'}}">{{i18n.t('experience.adoption.documents')}}</a></app-empty-state>
      }

      <ul class="space-y-2">
        @for (r of searchResults(); track $index) {
          <li class="ck-inset rounded p-3">
            <div class="flex items-center justify-between mb-1">
              <div class="text-[11px] truncate flex items-center gap-1" style="color:var(--ck-fg-4);">
                <app-icon name="file-text" [size]="11" />
                {{ r.metadata?.filename ?? i18n.t('knowledge.search.unknown_file') }}
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
      [title]="i18n.t('knowledge.browse.title')"
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
          [title]="i18n.t('knowledge.browse.error.title')"
          [description]="browseError()!"
        >
          <button
            type="button"
            class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
            (click)="loadBrowsePage(browseOffset())"
          >
            <app-icon name="refresh-cw" [size]="14" /> {{ i18n.t('common.retry') }}
          </button>
        </app-empty-state>
      } @else if (browseDocs().length === 0) {
        <app-empty-state
          icon="file-text"
          [title]="i18n.t('knowledge.browse.empty.title')"
          [description]="i18n.t('knowledge.browse.empty.description')"
        ><a class="ck-btn-soft" [navLink]="{leaf:'help-guide',params:{guideId:'sources'}}">{{i18n.t('experience.adoption.documents')}}</a></app-empty-state>
      } @else {
        <div class="mb-3 flex items-center justify-between gap-2 text-xs" style="color:var(--ck-fg-3);">
          <span class="font-mono">
            {{ browseOffset() + 1 }}–{{ browseOffset() + browseDocs().length }} / {{ browseTotal() }}
          </span>
          <div class="flex items-center gap-1.5">
            <button
              type="button"
              [title]="i18n.t('knowledge.browse.prev_page')"
              [attr.aria-label]="i18n.t('knowledge.browse.prev_page')"
              class="ck-iconbtn h-7 w-7"
              [disabled]="browseLoading() || browseOffset() === 0"
              (click)="loadBrowsePage(browseOffset() > browsePageSize ? browseOffset() - browsePageSize : 0)"
            >
              <app-icon name="chevron-left" [size]="13" />
            </button>
            <button
              type="button"
              [title]="i18n.t('knowledge.browse.next_page')"
              [attr.aria-label]="i18n.t('knowledge.browse.next_page')"
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
                  {{ i18n.t('knowledge.collections.chunks_count', { count: d.chunk_count ?? 0 }) }}
                  @if (d.mime_type) {
                    <span class="mx-1">·</span>{{ d.mime_type }}
                  }
                </div>
              </div>
              <div class="flex items-center gap-0.5 shrink-0 opacity-70 group-hover:opacity-100">
                <button
                  class="ck-ghost-icon p-1.5 rounded"
                  [title]="i18n.t('knowledge.browse.preview')"
                  (click)="previewDoc(d)"
                >
                  <app-icon name="eye" [size]="13" />
                </button>
                <button
                  class="ck-ghost-icon ck-ghost-icon-danger p-1.5 rounded"
                  [title]="i18n.t('knowledge.browse.delete_doc')"
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
      [subtitle]="i18n.t('knowledge.preview.subtitle')"
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
          {{ i18n.t('knowledge.preview.binary') }}
        </div>
        <a
          [href]="previewDownloadUrl()!"
          target="_blank"
          rel="noreferrer"
          class="ck-btn-primary inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
        >
          <app-icon name="external-link" [size]="14" /> {{ i18n.t('knowledge.preview.open_file') }}
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
              <h2 class="text-base font-semibold mb-1" style="color:var(--ck-fg-1);">{{ i18n.t('knowledge.collections.new') }}</h2>
              <p class="text-sm" style="color:var(--ck-fg-3);">
                {{ i18n.t('knowledge.create.description') }}
              </p>
            </div>
          </div>
          <input
            type="text"
            [(ngModel)]="newCollectionDraftValue"
            [placeholder]="i18n.t('knowledge.create.placeholder')"
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
              {{ i18n.t('common.cancel') }}
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
              {{ i18n.t('common.create') }}
            </button>
          </div>
        </div>
      </div>
    }

    <app-confirm-dialog
      [open]="deleteCollectionTarget() !== null"
      [title]="i18n.t('knowledge.delete_collection.title', { name: deleteCollectionTarget() ?? '' })"
      [description]="i18n.t('knowledge.delete_collection.description')"
      [confirmPhrase]="deleteCollectionTarget() ?? ''"
      [confirmLabel]="i18n.t('knowledge.collections.delete')"
      [cancelLabel]="i18n.t('common.cancel')"
      tone="danger"
      (confirm)="confirmDeleteCollection()"
      (cancel)="deleteCollectionTarget.set(null)"
    />

    <app-confirm-dialog
      [open]="deleteDocTarget() !== null"
      [title]="i18n.t('knowledge.delete_document.title', { name: deleteDocTarget()?.filename ?? '' })"
      [description]="i18n.t('knowledge.delete_document.description')"
      [confirmLabel]="i18n.t('common.delete')"
      [cancelLabel]="i18n.t('common.cancel')"
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
  readonly i18n = inject(I18nService);
  private readonly http = inject(HttpClient);
  private readonly toast = inject(ToastrService);
  private readonly productTelemetry = inject(ProductTelemetryService);

  private readonly base = '/api/v1/documents';

  /**
   * An upload request failed outright and has not yet been followed by a clean
   * batch. `uploadState` cannot answer this at success time — the next attempt
   * has already moved it to `uploading` — so the intent is tracked explicitly.
   * The counter beside it is a local dedupe key and is never emitted.
   */
  private uploadRecoveryPending = false;
  private uploadFailureCount = 0;

  // Collections
  collections = signal<CollectionInfo[]>([]);
  loadingCollections = signal(false);
  collectionsError = signal<string | null>(null);
  vectorDbType = signal<string>('');

  uploading = signal(false);
  uploadCount = signal(0);
  dragging = signal(false);
  advancedOpen = signal(false);
  uploadState = signal<'idle' | 'uploading' | 'ready' | 'partial' | 'error'>('idle');
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
  readonly defaultCollectionSlug = computed(() =>
    this.collections().find((collection) => collection.slug === 'documents')?.slug
      || this.collections()[0]?.slug
      || 'documents',
  );
  readonly indexingLabel = computed(() =>
    this.loadingCollections() ? this.i18n.t('knowledge.kpi.indexing') : this.i18n.t('knowledge.kpi.ready'),
  );

  // `i18n.t` reads the locale signal, so this computed re-emits — and the
  // header re-renders — when the user flips languages.
  readonly headerKpis = computed<CkObjectKpi[]>(() => [
    {
      label: this.i18n.t('knowledge.kpi.collections'),
      value: String(this.collections().length),
      tone: 'cool',
      hint: this.i18n.t('knowledge.kpi.collections_hint'),
    },
    {
      label: this.i18n.t('knowledge.kpi.documents'),
      value: String(this.totalDocs()),
      tone: 'neutral',
      hint: this.i18n.t('knowledge.kpi.documents_hint'),
    },
    {
      label: this.i18n.t('knowledge.kpi.chunks'),
      value: String(this.totalChunks()),
      tone: 'neutral',
      hint: this.i18n.t('knowledge.kpi.chunks_hint'),
    },
    {
      label: this.i18n.t('knowledge.kpi.vector_db'),
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
            err?.error?.detail || this.i18n.t('knowledge.collections.error.description'),
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
      this.toast.error(this.i18n.t('knowledge.toast.retry_before_upload'), this.i18n.t('knowledge.title'));
      return;
    }
    this.uploading.set(true);
    this.uploadState.set('uploading');
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
        this.uploadState.set(res.failed > 0 ? 'partial' : 'ready');
        if (res.successful > 0) {
          // Authoritative: the batch endpoint confirmed at least one indexed
          // document. A dropped file that never reached the API is not
          // knowledge added.
          this.productTelemetry.recordOnce('knowledge_added');
          // Recovery means the user is out of the failure, so a batch that
          // still leaves documents failing keeps the intent armed.
          if (this.uploadRecoveryPending && res.failed === 0) {
            this.uploadRecoveryPending = false;
            this.productTelemetry.recordOccurrence('failure_recovered', {
              dedupeKey: `knowledge-upload-${this.uploadFailureCount}`,
              recoveryKind: 'knowledge_upload',
            });
          }
        }
        if (res.failed > 0) {
          this.toast.warning(
            this.i18n.t('knowledge.toast.upload_partial', {
              successful: res.successful,
              total: res.total,
              failed: res.failed,
            }),
            this.i18n.t('knowledge.toast.upload_partial_title'),
          );
        } else {
          this.toast.success(
            this.i18n.t('knowledge.toast.upload_success', { count: res.successful }),
            this.i18n.t('knowledge.toast.upload_complete_title'),
          );
        }
        this.loadCollections();
      },
      error: () => {
        this.uploading.set(false);
        this.uploadState.set('error');
        this.uploadFailureCount += 1;
        this.uploadRecoveryPending = true;
        this.toast.error(
          this.i18n.t('knowledge.toast.upload_failed'),
          this.i18n.t('knowledge.toast.upload_error_title'),
        );
      },
    });
  }

  uploadStatusKey(): string {
    switch (this.uploadState()) {
      case 'uploading': return 'knowledge.upload.status.processing';
      case 'ready': return 'knowledge.upload.status.ready';
      case 'partial': return 'knowledge.upload.status.partial';
      case 'error': return 'knowledge.upload.status.error';
      default: return 'knowledge.upload.status.processing';
    }
  }

  uploadMessageKey(): string {
    switch (this.uploadState()) {
      case 'ready': return 'knowledge.upload.message.ready';
      case 'partial': return 'knowledge.upload.message.partial';
      case 'error': return 'knowledge.upload.message.error';
      default: return 'knowledge.upload.message.processing';
    }
  }

  createCollection(): void {
    if (this.collectionsError()) {
      this.toast.error(this.i18n.t('knowledge.toast.retry_before_create'), this.i18n.t('knowledge.title'));
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
          this.toast.success(
            this.i18n.t('knowledge.toast.collection_created', { name }),
            this.i18n.t('knowledge.title'),
          );
          this.creating.set(false);
          this.createOpen.set(false);
          this.newCollectionDraftValue = '';
          this.loadCollections();
        },
        error: (err) => {
          this.toast.error(
            err?.error?.detail || this.i18n.t('knowledge.toast.create_failed'),
            this.i18n.t('knowledge.title'),
          );
          this.creating.set(false);
        },
      });
  }

  openCreateCollection(): void {
    if (this.collectionsError()) {
      this.toast.error(this.i18n.t('knowledge.toast.retry_before_create'), this.i18n.t('knowledge.title'));
      return;
    }
    this.newCollectionDraft.set('');
    this.createOpen.set(true);
  }

  openFilePicker(input: HTMLInputElement): void {
    if (this.collectionsError()) {
      this.toast.error(this.i18n.t('knowledge.toast.retry_before_upload'), this.i18n.t('knowledge.title'));
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
          this.toast.success(
            this.i18n.t('knowledge.toast.collection_deleted', { name }),
            this.i18n.t('knowledge.title'),
          );
          this.deleteCollectionTarget.set(null);
          this.loadCollections();
        },
        error: (err) => {
          this.toast.error(
            err?.error?.detail || this.i18n.t('knowledge.toast.delete_failed'),
            this.i18n.t('knowledge.title'),
          );
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
            err?.error?.detail || this.i18n.t('knowledge.browse.error.description'),
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
          this.previewError.set(err?.error?.detail ?? this.i18n.t('knowledge.preview.error'));
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
          this.toast.success(
            this.i18n.t('knowledge.toast.document_deleted', { name: d.filename }),
            this.i18n.t('knowledge.title'),
          );
          this.browseDocs.update((list) => list.filter((x) => x.document_id !== d.document_id));
          this.deleteDocTarget.set(null);
          this.loadCollections();
        },
        error: (err) => {
          this.toast.error(
            err?.error?.detail || this.i18n.t('knowledge.toast.delete_failed'),
            this.i18n.t('knowledge.title'),
          );
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
          const message = err?.error?.detail || this.i18n.t('knowledge.search.error.description');
          this.searchResults.set([]);
          this.searchError.set(message);
          this.toast.error(message, this.i18n.t('knowledge.title'));
          this.searching.set(false);
        },
      });
  }

  isNum(v: unknown): boolean {
    return typeof v === 'number' && !Number.isNaN(v);
  }
}
