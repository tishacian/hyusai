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
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ToastrService } from 'ngx-toastr';
import { WorkspaceService, type WorkspaceMemberDetail } from '@app/core/workspace.service';
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
import { collectionIndexPresentation } from './knowledge-facets';
import {
  ACCESS_ROLE_TEMPLATES,
  accessFormErrors,
  canGrant,
  formFromPolicy,
  isGranted,
  policyFromForm,
  samePolicy,
  setMode,
  togglePrincipal,
  type AccessAction,
  type AccessMode,
  type CollectionAccessForm,
  type CollectionAccessPolicy,
} from './collection-access-form';

interface CollectionInfo {
  id?: string;
  slug: string;
  name: string;
  chunks: number;
  docs: number;
  status?: string;
  loading?: boolean;
  access?: CollectionAccess | null;
  permissions?: CollectionPermissions;
}

interface CollectionItemPayload {
  id?: string;
  slug?: string;
  name?: string;
  document_count?: number;
  source_count?: number;
  chunk_count?: number;
  status?: string;
  access?: CollectionAccess | null;
  permissions?: CollectionPermissions;
}

type CollectionAccess = CollectionAccessPolicy;

interface CollectionPermissions {
  can_read?: boolean;
  can_write?: boolean;
  can_manage?: boolean;
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
      <button
        actions
        type="button"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        (click)="openGlobalSearch()"
      >
        <app-icon name="search" [size]="14" /> {{ i18n.t('common.search') }}
      </button>
      <a
        actions
        [navLink]="{ surface: 'knowledge-capture' }"
        class="ck-btn-soft inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        [title]="i18n.t('capture.kb.start_capture_title')"
      >
        <app-icon name="mic" [size]="14" /> {{ i18n.t('knowledge.header.capture') }}
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
        <app-icon name="folder-plus" [size]="14" /> {{ i18n.t('knowledge.collections.new') }}
      </button>
      @if (canUpload()) {
        <button
          actions
          type="button"
          (click)="openFilePicker(fileInput)"
          [class.opacity-50]="collectionsError()"
          [class.cursor-not-allowed]="collectionsError()"
          [disabled]="!!collectionsError()"
          class="ck-btn-primary inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium"
        >
          <app-icon name="cloud-upload" [size]="14" /> {{ i18n.t('knowledge.header.upload') }}
        </button>
      }
    </ck-object-header>

    <!-- Dropzone -->
    <input
      #fileInput
      type="file"
      multiple
      class="hidden"
      [disabled]="!!collectionsError()"
      (change)="onFileSelect($event)"
      accept=".pdf,.txt,.md,.docx,.csv,.json,.png,.jpg,.jpeg,.tif,.tiff,.webp"
    />
    @if (canUpload()) {
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
            <span class="ml-2" style="color:var(--ck-fg-4);">{{ i18n.t('knowledge.dropzone.target') }} </span>
            <select
              class="ck-field-select ck-field-select-inline ml-1"
              [(ngModel)]="uploadTarget"
              [disabled]="!!collectionsError()"
              (click)="$event.stopPropagation()"
            >
              @if (canUploadDefaultCollection()) {
                <option value="documents">documents</option>
              }
              @for (c of collections(); track c.slug) {
                @if (c.slug !== 'documents' && c.permissions?.can_write !== false) {
                  <option [value]="c.slug">{{ c.name }}</option>
                }
              }
            </select>
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
    }

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
                    {{ i18n.t('knowledge.collections.docs_count', { count: doc.docs }) }}
                  </span>
                  <span class="flex items-center gap-1">
                    <app-icon name="braces" [size]="11" />
                    {{ i18n.t('knowledge.collections.chunks_count', { count: doc.chunks }) }}
                  </span>
                  @if (doc.access) {
                    <span class="flex items-center gap-1">
                      <app-icon name="shield" [size]="11" />
                      {{ i18n.t('knowledge.collections.restricted') }}
                    </span>
                  }
                </div>
              </div>
            </div>

            <div class="flex items-center justify-between">
              <app-status-pulse
                [tone]="collectionPulse(doc).tone"
                [label]="i18n.t(collectionPulse(doc).labelKey)"
              />
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
                @if (doc.permissions?.can_manage) {
                  <button
                    type="button"
                    class="ck-ghost-icon p-1.5 rounded"
                    data-testid="collection-access-open"
                    [title]="i18n.t('knowledge.collections.access.manage')"
                    [attr.aria-label]="i18n.t('knowledge.collections.access.manage') + ' — ' + doc.name"
                    (click)="openAccess(doc)"
                  >
                    <app-icon name="shield-check" [size]="14" />
                  </button>
                }
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

    <!-- L35 · Accès: who reads the collection, who adds documents -->
    <app-drawer
      [open]="accessTarget() !== null"
      [title]="i18n.t('knowledge.collections.access.title')"
      [subtitle]="accessTarget()?.name || accessTarget()?.slug || ''"
      icon="shield-check"
      (close)="closeAccess()"
    >
      @if (accessTarget(); as target) {
        <form class="kb-access" data-testid="collection-access" (submit)="$event.preventDefault(); saveAccess(target)">
          <p class="kb-access-note">{{ i18n.t('knowledge.collections.access.admins_note') }}</p>
          @for (action of accessActions; track action) {
            <fieldset class="kb-access-set" [attr.data-testid]="'collection-access-' + action">
              <legend class="kb-access-legend">{{ i18n.t('knowledge.collections.access.' + action + '.legend') }}</legend>
              <label class="kb-access-choice">
                <input
                  type="radio"
                  [name]="'collection-access-' + action"
                  [checked]="accessForm()[action].mode === 'all'"
                  (change)="setAccessMode(action, 'all')"
                />
                <span>{{ i18n.t('knowledge.collections.access.all_members') }}</span>
              </label>
              <label class="kb-access-choice">
                <input
                  type="radio"
                  [name]="'collection-access-' + action"
                  [checked]="accessForm()[action].mode === 'selected'"
                  (change)="setAccessMode(action, 'selected')"
                />
                <span>{{ i18n.t('knowledge.collections.access.selected') }}</span>
              </label>
              @if (action === 'write') {
                <p class="kb-access-hint">{{ i18n.t('knowledge.collections.access.write.hint') }}</p>
              }
              @if (accessForm()[action].mode === 'selected') {
                <div class="kb-access-grants">
                  @if (accessForm()[action].principals.length === 0) {
                    <p class="kb-access-hint">{{ i18n.t('knowledge.collections.access.admins_only') }}</p>
                  }
                  <p class="kb-access-group-title" [id]="'access-roles-' + action">{{ i18n.t('knowledge.collections.access.roles') }}</p>
                  <ul class="kb-access-list" [attr.aria-labelledby]="'access-roles-' + action">
                    @for (role of accessRoles; track role) {
                      @if (canGrantAccess(action, 'role:' + role)) {
                        <li>
                          <label class="kb-access-choice">
                            <input
                              type="checkbox"
                              [checked]="accessGranted(action, 'role:' + role)"
                              (change)="toggleAccess(action, 'role:' + role, $event)"
                            />
                            <span>{{ accessPrincipalLabel('role:' + role) }}</span>
                          </label>
                        </li>
                      }
                    }
                  </ul>
                  @if (accessGroups().length) {
                    <p class="kb-access-group-title" [id]="'access-groups-' + action">{{ i18n.t('knowledge.collections.access.groups') }}</p>
                    <ul class="kb-access-list" [attr.aria-labelledby]="'access-groups-' + action">
                      @for (group of accessGroups(); track group) {
                        <li>
                          <label class="kb-access-choice">
                            <input
                              type="checkbox"
                              [checked]="accessGranted(action, 'group:' + group)"
                              (change)="toggleAccess(action, 'group:' + group, $event)"
                            />
                            <span>{{ group }}</span>
                          </label>
                        </li>
                      }
                    </ul>
                  }
                  @if (accessMembers().length) {
                    <p class="kb-access-group-title" [id]="'access-people-' + action">{{ i18n.t('knowledge.collections.access.people') }}</p>
                    <ul class="kb-access-list" [attr.aria-labelledby]="'access-people-' + action">
                      @for (member of accessMembers(); track member.user_id) {
                        <li>
                          <label class="kb-access-choice">
                            <input
                              type="checkbox"
                              [checked]="accessGranted(action, 'user:' + member.user_id)"
                              (change)="toggleAccess(action, 'user:' + member.user_id, $event)"
                            />
                            <span>{{ member.username || member.email || member.user_id }}</span>
                          </label>
                        </li>
                      }
                    </ul>
                  } @else if (accessLoading()) {
                    <p class="kb-access-hint">{{ i18n.t('knowledge.collections.access.loading_people') }}</p>
                  }
                </div>
              }
            </fieldset>
          }
          @for (error of accessErrors(); track error.code) {
            <p class="kb-access-error" role="alert" data-testid="collection-access-error">
              {{ i18n.t('knowledge.collections.access.error.' + error.code, { names: accessNames(error.principals) }) }}
            </p>
          }
          @if (accessSaveError()) {
            <p class="kb-access-error" role="alert">{{ accessSaveError() }}</p>
          }
          <div class="kb-access-actions">
            <button type="button" class="ck-btn-ghost px-4 py-2 text-sm rounded" (click)="closeAccess()">
              {{ i18n.t('common.cancel') }}
            </button>
            <button
              type="submit"
              class="ck-btn-primary px-4 py-2 text-sm font-medium rounded"
              [disabled]="savingAccess() || accessErrors().length > 0"
            >
              {{ i18n.t('common.save') }}
            </button>
          </div>
        </form>
      }
    </app-drawer>

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
    /* L35 · Accès — sober, token-driven form (Tokens v2). */
    .kb-access { display: flex; flex-direction: column; gap: 20px; font-size: 14px; color: var(--ck-fg-2); }
    .kb-access-note, .kb-access-hint { margin: 0; font-size: 13px; color: var(--ck-fg-3); }
    .kb-access-set { margin: 0; padding: 0; border: 0; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    .kb-access-legend { padding: 0; margin-bottom: 4px; font-weight: 600; color: var(--ck-fg-1); }
    .kb-access-choice { display: flex; align-items: center; gap: 8px; min-height: 28px; cursor: pointer; color: var(--ck-fg-1); }
    .kb-access-choice input { width: 16px; height: 16px; flex-shrink: 0; accent-color: var(--ck-signal-cool); }
    .kb-access-grants {
      display: flex; flex-direction: column; gap: 6px; margin-left: 24px; padding: 12px;
      border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-sm); background: var(--ck-bg-inset);
    }
    .kb-access-group-title { margin: 6px 0 0; font-size: 12px; font-weight: 600; color: var(--ck-fg-2); }
    .kb-access-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
    .kb-access-error { margin: 0; font-size: 13px; color: var(--ck-status-neg-fg); }
    .kb-access-actions { display: flex; justify-content: flex-end; gap: 8px; }
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
  private readonly workspaceService = inject(WorkspaceService);
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

  // L35 · Accès: per-collection read / add-documents policy
  accessTarget = signal<CollectionInfo | null>(null);
  accessForm = signal<CollectionAccessForm>(formFromPolicy(null));
  accessMembers = signal<WorkspaceMemberDetail[]>([]);
  accessLoading = signal(false);
  savingAccess = signal(false);
  accessSaveError = signal<string | null>(null);
  readonly accessActions: readonly AccessAction[] = ['read', 'write'];
  readonly accessRoles = ACCESS_ROLE_TEMPLATES;
  readonly accessErrors = computed(() => accessFormErrors(this.accessForm()));

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
      tone: 'cool',
      hint: this.indexingLabel(),
    },
  ]);

  collectionPulse(doc: CollectionInfo) {
    return collectionIndexPresentation(doc.status);
  }

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
                id: item.id,
                slug,
              name: item.name || slug,
              chunks: item.chunk_count ?? 0,
              docs: item.source_count ?? item.document_count ?? 0,
                status: item.status,
                access: item.access ?? null,
                permissions: item.permissions,
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
    if (!this.canUpload()) {
      this.toast.warning(
        this.i18n.t('knowledge.collections.access.upload_denied'),
        this.i18n.t('knowledge.title'),
      );
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
      error: (err) => {
        this.uploading.set(false);
        this.toast.error(
          err?.error?.detail || this.i18n.t('knowledge.toast.upload_failed'),
          this.i18n.t('knowledge.toast.upload_error_title'),
        );
      },
    });
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

  canUploadDefaultCollection(): boolean {
    const workspace = this.workspaceService.current();
    return workspace?.role !== 'viewer' && workspace?.role_template !== 'workspace_viewer';
  }

  canUpload(): boolean {
    if (!this.canUploadDefaultCollection()) return false;
    const selected = this.collections().find((collection) => collection.slug === this.uploadTarget);
    return selected?.permissions?.can_write !== false;
  }

  requestDeleteCollection(name: string): void {
    this.deleteCollectionTarget.set(name);
  }

  readonly accessGroups = computed(() =>
    Array.from(new Set(this.accessMembers().flatMap((member) => member.custom_labels ?? []))).sort(),
  );

  openAccess(collection: CollectionInfo): void {
    this.accessTarget.set(collection);
    this.accessForm.set(formFromPolicy(collection.access));
    this.accessSaveError.set(null);
    if (this.accessMembers().length > 0) return;
    const slug = this.workspaceService.currentSlug();
    if (!slug) return;
    this.accessLoading.set(true);
    this.workspaceService.listMembers(slug).subscribe({
      next: (members) => {
        this.accessMembers.set(members);
        this.accessLoading.set(false);
      },
      error: () => {
        this.accessMembers.set([]);
        this.accessLoading.set(false);
      },
    });
  }

  closeAccess(): void {
    this.accessTarget.set(null);
    this.accessSaveError.set(null);
  }

  setAccessMode(action: AccessAction, mode: AccessMode): void {
    this.accessForm.update((form) => setMode(form, action, mode));
  }

  toggleAccess(action: AccessAction, principal: string, event: Event): void {
    const granted = (event.target as HTMLInputElement).checked;
    this.accessForm.update((form) => togglePrincipal(form, action, principal, granted));
  }

  accessGranted(action: AccessAction, principal: string): boolean {
    return isGranted(this.accessForm(), action, principal);
  }

  canGrantAccess(action: AccessAction, principal: string): boolean {
    return canGrant(action, principal);
  }

  accessPrincipalLabel(principal: string): string {
    const [kind, value] = principal.split(':');
    if (kind === 'role') {
      const keys: Record<string, string> = {
        workspace_viewer: 'workspace.role.viewer',
        workspace_contributor: 'workspace.role.contributor',
        workspace_reviewer: 'workspace.role.reviewer',
        workspace_admin: 'workspace.role.admin',
        workspace_owner: 'workspace.role.owner',
      };
      return this.i18n.t(keys[value] || 'workspace.role.contributor');
    }
    if (kind === 'group') return value;
    const member = this.accessMembers().find((item) => item.user_id === value);
    return member?.username || member?.email || value;
  }

  accessNames(principals: string[]): string {
    return principals.map((principal) => this.accessPrincipalLabel(principal)).join(', ');
  }

  saveAccess(collection: CollectionInfo): void {
    if (this.savingAccess() || this.accessErrors().length > 0) return;
    const access = policyFromForm(this.accessForm());
    if (samePolicy(access, collection.access ?? null)) {
      this.closeAccess();
      return;
    }
    const id = collection.id || collection.slug;
    this.savingAccess.set(true);
    this.accessSaveError.set(null);
    this.http
      .patch<CollectionItemPayload>(`${this.base}/collections/${encodeURIComponent(id)}`, { access })
      .subscribe({
        next: () => {
          this.savingAccess.set(false);
          this.closeAccess();
          this.toast.success(
            this.i18n.t('knowledge.collections.access.saved', { name: collection.name }),
            this.i18n.t('knowledge.title'),
          );
          this.loadCollections();
        },
        error: () => {
          this.savingAccess.set(false);
          this.accessSaveError.set(this.i18n.t('knowledge.collections.access.save_failed'));
        },
      });
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
