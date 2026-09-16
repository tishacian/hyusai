import { BrandAppearanceEditorComponent } from '@app/shared/brand-appearance-editor.component';
import { brandAppearance, type BrandAppearance } from '@app/core/brand-appearance';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { HelpTooltipComponent } from '@app/shared/cockpit';
import { ConfirmDialogComponent } from '@app/shared/ui/confirm-dialog.component';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { navigationSurfaceUrl } from '@app/core/navigation.catalog';
import { canEditExperienceStudio, canReleaseExperienceStudio } from '../experience-access';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { workPageHref } from '../work/work-catalog';
import { acceptAssistantPatch, proposeAssistantPatch, type AssistantProposal } from './studio-assistant';
import {
  apiCode,
  studioError,
  StudioApiService,
  type StudioBinding,
  type StudioDetail,
  type StudioDeployment,
  type StudioDraft,
  type StudioDraftRevision,
  type StudioDrift,
  type StudioIngressList,
  type StudioRelease,
} from './studio-api.service';
import {
  applyPatch,
  applyPatchOnStack,
  emptyStack,
  findNode,
  hydrateDocument,
  cloneDocument,
  newNodeId,
  newPageId,
  nodeIndex,
  pagesPayload,
  pushRevision,
  redoRevision,
  undoRevision,
  type RevisionStack,
} from './studio-document';
import {
  ADDABLE_TYPES,
  ACCESS_ROLES,
  CONFIRMATION_POLICIES,
  UNAVAILABLE_POLICIES,
  bindingSharedWith,
  experienceAccessPolicy,
  inventoryState,
  schemaSelectorOptions,
  simulatedExperienceAccess,
  type StudioExperience,
} from './studio-model';
import type { ReadyCheck } from './studio-publish';
import { ExperiencePublishDialogComponent } from './publish-dialog.component';
import type {
  CertifiedType,
  ExperienceDocument,
  ExperienceNode,
  ExperiencePage,
  LocalizedText,
  RuntimeDataBinding,
  RuntimeField,
} from '../runtime/model';
import {
  CHART_PALETTES,
  chartPalette,
  fieldsFromSchema,
  formSchemaSupported,
  humanizeIdentifier,
  localizeDocument,
  runtimeDataBinding,
  textFallback,
  valuesToPayload,
} from '../runtime/model';
import {
  NODE_SPANS,
  a11yOf,
  a11yPayload,
  a11yValue,
  accentContrastWarning,
  appearanceOf,
  needsEmptyText,
  pageAppearance,
  supportsAccent,
  supportsHeading,
  supportsSpan,
  themeOf,
  type NodeA11y,
} from '../runtime/style';

const READY_DEBOUNCE_MS = 1500;

const RUN_OUTPUT_TARGETS = new Set<string>([
  'result',
  'table',
  'queue',
  'approval_card',
  'runtime_status',
  'evidence',
  'history',
  'kpi',
  'map_panel',
  'agenda_panel',
  'intelligence_feed',
  'decision_queue',
]);
const QUERY_TARGETS = new Set<string>([
  'table',
  'queue',
  'approval_card',
  'history',
  'kpi',
  'map_panel',
  'agenda_panel',
  'intelligence_feed',
  'decision_queue',
]);

type Tab = 'content' | 'action' | 'appearance' | 'a11y';
type LeftTab = 'pages' | 'components';
type Viewport = 'desktop' | 'tablet' | 'mobile';
type BottomTab = 'data' | 'actions' | 'access' | 'tests' | 'journal';
type Selection = { kind: 'page'; pageId: string } | { kind: 'node'; pageId: string; nodeId: string };

function documentBindingKeys(document: ExperienceDocument): string[] {
  const seen = new Set<string>();
  for (const page of document.pages) {
    for (const node of page.components) {
      const direct = node.props?.['bindingKey'];
      const query = node.props?.['queryBinding'];
      const queried = query && typeof query === 'object' && !Array.isArray(query)
        ? (query as Record<string, unknown>)['bindingKey']
        : null;
      for (const raw of [direct, queried]) {
        if (typeof raw === 'string' && raw.trim()) seen.add(raw.trim());
      }
    }
  }
  return [...seen];
}

@Component({
  selector: 'app-experience-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BrandAppearanceEditorComponent,
    RouterLink,
    HelpTooltipComponent,
    ExperienceRuntimeHostComponent,
    ExperiencePublishDialogComponent,
    ConfirmDialogComponent,
  ],
  styleUrl: './studio.scss',
  template: `
    <div
      class="xp-ed"
      [class.is-readonly]="readOnly()"
      [attr.inert]="draftHistoryBusy() ? '' : null"
      [attr.aria-busy]="draftHistoryBusy()"
    >
      <header class="xp-ed-chrome">
        <div class="xp-ed-id">
          <a [routerLink]="backHref()" class="xp-btn">
            {{ i18n.t(returnTo() ? 'experience.editor.back_to_work' : 'experience.editor.back') }}
          </a>
          <div class="xp-ed-heading">
            <span class="xp-ed-workspace">
              <span class="xp-ed-workspace-prefix">{{ i18n.t('titlebar.workspace') }} · </span>{{ workspace.current()?.name || i18n.t('titlebar.workspace') }}
            </span>
            <h1 id="experience-editor-title" tabindex="-1">{{ name() }}</h1>
          </div>
          <span class="xp-tag">{{ stateLabel() }}</span>
          @if (readOnly()) { <span class="xp-tag">{{ i18n.t('experience.editor.review_mode') }}</span> }
          @if (originReleaseId(); as releaseId) {
            <span
              class="xp-tag xp-tag-origin"
              [title]="i18n.t('experience.editor.origin_release.hint') + ' · ' + releaseId"
            >
              {{ i18n.t('experience.editor.origin_release', { n: originReleaseNumber() ?? '—', id: releaseId }) }}
            </span>
          }
          @if (readyLabel(); as label) {
            <span class="xp-tag" [class.xp-tag-ok]="readyTone() === 'ok'" [class.xp-tag-warn]="readyTone() === 'warn'">
              {{ label }}
            </span>
          }
        </div>
        <div class="xp-ed-tools">
          <button type="button" class="xp-btn" (click)="openVisualIdentity()">{{ i18n.t('experience.brand.title') }}</button>
          @if (!readOnly()) {
          <div class="xp-ed-group">
            <button
              type="button"
              class="xp-btn"
              [disabled]="stack().past.length === 0"
              (click)="undo()"
            >
              {{ i18n.t('experience.editor.undo') }}
            </button>
            <button
              type="button"
              class="xp-btn"
              [disabled]="stack().future.length === 0"
              (click)="redo()"
            >
              {{ i18n.t('experience.editor.redo') }}
            </button>
          </div>
          <div class="xp-ed-group">
            <button type="button" class="xp-btn" [disabled]="saving() || saved()" (click)="flushSave()">
              {{ saving()
                ? i18n.t('experience.editor.saving')
                : i18n.t(saved() ? 'experience.editor.saved' : 'experience.editor.save') }}
            </button>
          </div>
          }
          @if (viewSlug(); as slug) {
            <div class="xp-ed-group">
              <a class="xp-btn" [routerLink]="workLink(slug)">{{ i18n.t('experience.editor.view') }}</a>
            </div>
          }
          <div class="xp-ed-group">
            @if (canRelease()) {
            <button
              type="button"
              class="xp-btn xp-btn-primary"
              [disabled]="saving() || metadataDirty() || metadataBusy() || !metadataValid()"
              (click)="preparePublish($event)"
            >
              {{ i18n.t('experience.editor.publish') }}
            </button>
            <ck-help id="concept.release" />
            } @else {
              <span class="xp-hint">{{ i18n.t('experience.editor.review_required') }}</span>
            }
          </div>
        </div>
      </header>

      <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {{ saving()
          ? i18n.t('experience.editor.saving')
          : (saved() ? i18n.t('experience.editor.saved') : (readyLabel() || '')) }}
      </p>

      @if (error(); as err) {
        <p class="xp-error" role="alert">{{ err }}</p>
      }
      @if (catalogLoading()) {
        <p class="sr-only" role="status">{{ i18n.t('experience.editor.catalog.loading') }}</p>
      }
      @if (catalogFailed()) {
        <div class="xp-error xp-catalog-error" role="alert">
          <span>{{ i18n.t('experience.editor.catalog.error') }}</span>
          <button type="button" class="xp-btn" (click)="loadCatalogs()">
            {{ i18n.t('experience.wizard.retry') }}
          </button>
        </div>
      }

      <div class="xp-ed-grid">
        <aside class="xp-ed-col xp-ed-left" [attr.aria-label]="i18n.t('experience.editor.tree')">
          <div class="xp-tabs xp-left-tabs" role="tablist" [attr.aria-label]="i18n.t('experience.editor.tree')">
            @for (tab of leftTabs; track tab; let index = $index) {
              <button
                type="button"
                role="tab"
                [id]="'xp-left-' + tab"
                [attr.aria-controls]="'xp-left-panel-' + tab"
                [attr.aria-selected]="leftTab() === tab"
                [tabIndex]="leftTab() === tab ? 0 : -1"
                [class.is-on]="leftTab() === tab"
                (click)="leftTab.set(tab)"
                (keydown)="onLeftTabKey($event, index)"
              >
                {{ i18n.t('experience.editor.left.' + tab) }}
              </button>
            }
          </div>
          @if (leftTab() === 'pages') {
          <div id="xp-left-panel-pages" role="tabpanel" aria-labelledby="xp-left-pages">
          <div class="xp-ed-col-head">
            <strong>{{ i18n.t('experience.editor.tree') }}</strong>
            <button
              type="button"
              class="xp-btn xp-btn-icon"
              [disabled]="readOnly()"
              [attr.aria-label]="i18n.t('experience.editor.page.add')"
              [title]="i18n.t('experience.editor.page.add')"
              (click)="addPage()"
            >
              +
            </button>
          </div>
          <ul class="xp-tree">
            @for (page of doc().pages; track page.id) {
              <li class="xp-tree-page">
                <button
                  type="button"
                  [class.is-on]="isPageSelected(page.id)"
                  [attr.aria-current]="isPageSelected(page.id) ? 'page' : null"
                  (click)="selectPage(page.id)"
                >
                  {{ pageTitle(page) }}
                </button>
                <ul class="xp-tree">
                  @for (node of page.components; track node.id ?? $index) {
                    <li>
                      <button
                        type="button"
                        class="is-child"
                        [class.is-on]="isNodeSelected(node.id)"
                        [attr.aria-pressed]="isNodeSelected(node.id)"
                        (click)="selectNode(page.id, node.id)"
                        (keydown)="onOutlineKey($event, page.id, node.id)"
                        aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
                      >
                        {{ typeLabel(node.type) }}
                      </button>
                    </li>
                  } @empty {
                    <li><p class="xp-hint is-child">{{ i18n.t('experience.editor.page.empty') }}</p></li>
                  }
                </ul>
              </li>
            }
          </ul>
          </div>
          } @else {
            <div id="xp-left-panel-components" role="tabpanel" aria-labelledby="xp-left-components">
              <p class="xp-hint">{{ i18n.t('experience.editor.add.hint') }}</p>
              <div class="xp-component-palette">
                @for (type of addable; track type) {
                  <button type="button" [disabled]="readOnly()" (click)="addComponentType(type)">
                    <span aria-hidden="true">＋</span>{{ typeLabel(type) }}
                  </button>
                }
              </div>
            </div>
          }
        </aside>

        <section class="xp-ed-col xp-ed-canvas" [attr.aria-label]="i18n.t('experience.editor.preview')">
          <div class="xp-canvas-tools">
            <div class="xp-segment" role="radiogroup" [attr.aria-label]="i18n.t('experience.editor.viewport')">
              @for (size of viewports; track size; let index = $index) {
                <button
                  type="button"
                  role="radio"
                  [attr.aria-checked]="viewport() === size"
                  [tabIndex]="viewport() === size ? 0 : -1"
                  [class.is-on]="viewport() === size"
                  (click)="viewport.set(size)"
                  (keydown)="onViewportKey($event, index)"
                >{{ i18n.t('experience.editor.viewport.' + size) }}</button>
              }
            </div>
            <span class="xp-hint">{{ i18n.t('experience.editor.preview.safe') }}</span>
          </div>
          <div class="xp-preview-access" [attr.aria-label]="i18n.t('experience.editor.preview_as')">
            <strong>{{ i18n.t('experience.editor.preview_as') }}</strong>
            <label>
              <span class="sr-only">{{ i18n.t('experience.editor.preview_as.role') }}</span>
              <select [value]="previewRole()" (change)="previewRole.set(selectValue($event))">
                @for (role of accessRolesList; track role) {
                  <option [value]="role">{{ i18n.t('governance.access.role.' + role) }}</option>
                }
              </select>
            </label>
            @if (accessGroups().length > 0) {
              <label>
                <span class="sr-only">{{ i18n.t('experience.editor.preview_as.group') }}</span>
                <select [value]="previewGroup()" (change)="previewGroup.set(selectValue($event))">
                  <option value="">{{ i18n.t('experience.editor.preview_as.no_group') }}</option>
                  @for (group of accessGroups(); track group) { <option [value]="group">{{ group }}</option> }
                </select>
              </label>
            }
            <span
              class="xp-tag"
              [class.xp-tag-ok]="previewAllowed()"
              [class.xp-tag-warn]="!previewAllowed()"
              role="status"
              aria-live="polite"
            >{{ i18n.t(previewAllowed() ? 'experience.editor.preview_as.allowed' : 'experience.editor.preview_as.denied') }}</span>
            <span class="xp-hint">{{ i18n.t('experience.editor.preview_as.local_only') }}</span>
          </div>
          <div class="xp-canvas-stage" [class]="'is-' + viewport()">
            @if (previewAllowed()) {
              <div class="xp-canvas-preview" inert>
                <app-experience-runtime-host [document]="previewDoc()" [pageId]="pageId()" />
              </div>
            } @else {
              <div class="xp-canvas-preview xp-preview-denied" role="status">
                <strong>{{ i18n.t('experience.editor.preview_as.denied.title') }}</strong>
                <p>{{ i18n.t('experience.editor.preview_as.denied.body') }}</p>
              </div>
            }
          </div>
          @if (!readOnly()) {
          <form class="xp-assist" (submit)="$event.preventDefault(); propose()">
            <div class="xp-assist-bar">
              <input
                type="text"
                [value]="prompt()"
                [placeholder]="i18n.t('experience.assistant.placeholder')"
                [attr.aria-label]="i18n.t('experience.assistant.label')"
                (input)="prompt.set(inputValue($event))"
              />
              <button type="submit" class="xp-btn">{{ i18n.t('experience.assistant.submit') }}</button>
            </div>
            @if (proposal(); as item) {
              <p class="xp-hint">{{ proposalSummary(item) }}</p>
              <div class="xp-row">
                <button type="button" class="xp-btn xp-btn-primary" (click)="applyProposal()">
                  {{ i18n.t('experience.assistant.apply') }}
                </button>
                <button type="button" class="xp-btn" (click)="proposal.set(null)">
                  {{ i18n.t('common.cancel') }}
                </button>
              </div>
            } @else if (assistantMiss()) {
              <p class="xp-hint">{{ i18n.t('experience.assistant.unknown') }}</p>
            } @else {
              <p class="xp-hint">{{ i18n.t('experience.assistant.hint') }}</p>
            }
          </form>
          }
        </section>

        <aside class="xp-ed-col xp-ed-inspector" [attr.aria-label]="i18n.t('experience.editor.inspector')">
          @if (selectedNode(); as node) {
            <div class="xp-node-bar">
              <strong>{{ typeLabel(node.type) }}</strong>
              <div>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="readOnly() || !canMove(-1)"
                  [attr.aria-label]="i18n.t('experience.editor.move_up')"
                  [title]="i18n.t('experience.editor.move_up')"
                  (click)="moveSelected(-1)"
                >
                  ↑
                </button>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="readOnly() || !canMove(1)"
                  [attr.aria-label]="i18n.t('experience.editor.move_down')"
                  [title]="i18n.t('experience.editor.move_down')"
                  (click)="moveSelected(1)"
                >
                  ↓
                </button>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="readOnly()"
                  [attr.aria-label]="i18n.t('experience.editor.delete')"
                  [title]="i18n.t('experience.editor.delete')"
                  (click)="removeSelected()"
                >
                  ✕
                </button>
              </div>
            </div>
          } @else if (selectedPage(); as page) {
            <div class="xp-node-bar">
              <strong>{{ pageTitle(page) }}</strong>
              <div>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="readOnly() || doc().pages.length <= 1"
                  [attr.aria-label]="i18n.t('experience.editor.page.delete')"
                  [title]="i18n.t('experience.editor.page.delete')"
                  (click)="removePage(page.id)"
                >
                  ✕
                </button>
              </div>
            </div>
          }

          <div class="xp-tabs" role="tablist" [attr.aria-label]="i18n.t('experience.editor.inspector')">
            @for (tab of tabs; track tab; let index = $index) {
              <button
                type="button"
                role="tab"
                [id]="'xp-inspector-' + tab"
                [attr.aria-controls]="'xp-inspector-panel-' + tab"
                [class.is-on]="inspectorTab() === tab"
                [attr.aria-selected]="inspectorTab() === tab"
                [tabIndex]="inspectorTab() === tab ? 0 : -1"
                (click)="inspectorTab.set(tab)"
                (keydown)="onInspectorTabKey($event, index)"
              >
                {{ i18n.t('experience.editor.tab.' + tab) }}
              </button>
            }
          </div>

          <fieldset class="xp-inspector-fields" [disabled]="readOnly()">
          @if (inspectorTab() === 'content') {
            <div id="xp-inspector-panel-content" role="tabpanel" aria-labelledby="xp-inspector-content">
            <div class="xp-field">
              <span>{{ i18n.t('experience.editor.locale') }}</span>
              <div class="xp-segment" role="radiogroup" [attr.aria-label]="i18n.t('experience.editor.locale')">
                @for (locale of editableLocales(); track locale; let index = $index) {
                  <button
                    type="button"
                    role="radio"
                    [attr.aria-checked]="contentLocale() === locale"
                    [tabIndex]="contentLocale() === locale ? 0 : -1"
                    [class.is-on]="contentLocale() === locale"
                    (click)="contentLocale.set(locale)"
                    (keydown)="onLocaleKey($event, index)"
                  >{{ locale.toUpperCase() }}</button>
                }
              </div>
            </div>
            @if (selectedPage(); as page) {
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.title') }}</span>
                <input [value]="localizedValue(page.title)" (input)="setLocalizedPageTitle(page, inputValue($event))" />
              </label>
              <p class="xp-hint">{{ i18n.t('experience.editor.locale.fallback') }} · {{ pageFallback(page) }}</p>
            }
            @if (selectedNode(); as node) {
              @if (hasProp(node, 'title')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.title') }}</span>
                  <input [value]="localizedProp(node, 'title')" (input)="setLocalizedProp(node, 'title', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'subtitle')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.subtitle') }}</span>
                  <input [value]="localizedProp(node, 'subtitle')" (input)="setLocalizedProp(node, 'subtitle', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'body')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.body') }}</span>
                  <textarea [value]="localizedProp(node, 'body')" (input)="setLocalizedProp(node, 'body', inputValue($event))"></textarea>
                </label>
              }
              @if (hasProp(node, 'label')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.label') }}</span>
                  <input [value]="localizedProp(node, 'label')" (input)="setLocalizedProp(node, 'label', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'caption')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.caption') }}</span>
                  <input [value]="localizedProp(node, 'caption')" (input)="setLocalizedProp(node, 'caption', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'value')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.value') }}</span>
                  <input [value]="str(node, 'value')" (input)="setProp(node, 'value', inputValue($event))" />
                </label>
              }
              @if (node.type === 'form') {
                <section class="xp-inspector-section xp-form-copy">
                  <h3>{{ i18n.t('experience.editor.form_copy.title') }}</h3>
                  <p class="xp-hint">{{ i18n.t('experience.editor.form_copy.hint') }}</p>
                  @for (field of formFields(node); track field.name) {
                    <fieldset class="xp-form-copy-field">
                      <legend>{{ field.name }}</legend>
                      <label class="xp-field">
                        <span>{{ i18n.t('experience.editor.form_copy.label') }}</span>
                        <input
                          [value]="formCopyValue(node, field, 'label')"
                          (input)="setLocalizedFormCopy(node, field, 'label', inputValue($event))"
                        />
                      </label>
                      @if (formCopyNeedsTranslation(node, field, 'label')) {
                        <p class="xp-warn">
                          {{ i18n.t('experience.editor.form_copy.translation_needed', { locale: contentLocale().toUpperCase() }) }}
                          <button type="button" class="xp-btn" (click)="setLocalizedFormCopy(node, field, 'label', formCopyValue(node, field, 'label'))">
                            {{ i18n.t('experience.editor.form_copy.use_fallback') }}
                          </button>
                        </p>
                      }
                      <label class="xp-field">
                        <span>{{ i18n.t('experience.editor.form_copy.description') }}</span>
                        <textarea
                          [value]="formCopyValue(node, field, 'description')"
                          (input)="setLocalizedFormCopy(node, field, 'description', inputValue($event))"
                        ></textarea>
                      </label>
                      @if (formCopyNeedsTranslation(node, field, 'description')) {
                        <p class="xp-warn">
                          {{ i18n.t('experience.editor.form_copy.translation_needed', { locale: contentLocale().toUpperCase() }) }}
                          <button type="button" class="xp-btn" (click)="setLocalizedFormCopy(node, field, 'description', formCopyValue(node, field, 'description'))">
                            {{ i18n.t('experience.editor.form_copy.use_fallback') }}
                          </button>
                        </p>
                      }
                      @for (option of field.options; track option; let optionIndex = $index) {
                        <label class="xp-field">
                          <span>{{ i18n.t('experience.editor.form_copy.option', { value: option }) }}</span>
                          <input
                            [value]="formCopyValue(node, field, 'option', option)"
                            (input)="setLocalizedFormCopy(node, field, 'option', inputValue($event), option, optionIndex)"
                          />
                        </label>
                        @if (formCopyNeedsTranslation(node, field, 'option', option)) {
                          <p class="xp-warn">
                            {{ i18n.t('experience.editor.form_copy.translation_needed', { locale: contentLocale().toUpperCase() }) }}
                            <button type="button" class="xp-btn" (click)="setLocalizedFormCopy(node, field, 'option', formCopyValue(node, field, 'option', option), option, optionIndex)">
                              {{ i18n.t('experience.editor.form_copy.use_fallback') }}
                            </button>
                          </p>
                        }
                      }
                    </fieldset>
                  } @empty {
                    <p class="xp-hint">{{ i18n.t('experience.editor.action.inputs.empty') }}</p>
                  }
                </section>
              }
            }
            </div>
          }

          @if (inspectorTab() === 'action') {
            @if (actionNode(); as node) {
              <div class="xp-field">
                <span class="xp-lbl">
                  {{ i18n.t('experience.editor.action.calls') }}
                  <ck-help id="concept.binding" />
                </span>
                <select
                  [value]="str(node, 'bindingKey')"
                  [attr.aria-label]="i18n.t('experience.editor.action.calls')"
                  (change)="setActionBinding(node, selectValue($event))"
                >
                  <option value="" [selected]="!str(node, 'bindingKey')">
                    {{ i18n.t('experience.editor.action.none_option') }}
                  </option>
                  @if (ownBindings().length > 0) {
                    <optgroup [label]="i18n.t('experience.editor.action.group.app')">
                      @for (row of ownBindings(); track row.binding_key) {
                        <option
                          [value]="row.binding_key"
                          [selected]="str(node, 'bindingKey') === row.binding_key"
                        >{{ bindingLabel(row) }}</option>
                      }
                    </optgroup>
                  }
                  @if (otherBindings().length > 0) {
                    <optgroup [label]="i18n.t('experience.editor.action.group.other')">
                      @for (row of otherBindings(); track row.binding_key) {
                        <option
                          [value]="row.binding_key"
                          [selected]="str(node, 'bindingKey') === row.binding_key"
                        >{{ bindingLabel(row) }}</option>
                      }
                    </optgroup>
                  }
                </select>
              </div>
              @if (bound(node); as row) {
                <p class="xp-meta">
                  <span>{{ bindingLabel(row) }}</span>
                </p>
                <p class="xp-hint">
                  <strong>{{ i18n.t('experience.editor.action.inputs') }}</strong>
                  @if (inputNames(node).length === 0) {
                    {{ i18n.t('experience.editor.action.inputs.empty') }}
                  } @else {
                    {{ inputNames(node).join(', ') }}
                  }
                </p>
                @if (sharedWith(row.binding_key); as others) {
                  @if (others.length > 0) {
                    <p class="xp-warn" role="status">
                      {{ i18n.t('experience.editor.action.shared', { apps: others.join(', ') }) }}
                    </p>
                  }
                }
                <div class="xp-field">
                  <span class="xp-lbl">
                    {{ i18n.t('experience.editor.action.confirmation') }}
                    <ck-help id="concept.human-approval" />
                  </span>
                  <select
                    [attr.aria-label]="i18n.t('experience.editor.action.confirmation')"
                    [disabled]="appsState() !== 'ready'"
                    [value]="row.confirmation_policy"
                    (change)="patchBinding(row.binding_key, { confirmation_policy: selectValue($event) })"
                  >
                    @for (policy of confirms; track policy) {
                      <option [value]="policy">{{ i18n.t('experience.editor.confirm.' + policy) }}</option>
                    }
                  </select>
                </div>
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.action.after') }}</span>
                  <select [value]="str(node, 'afterSuccess') || 'stay'" (change)="setProp(node, 'afterSuccess', selectValue($event))">
                    <option value="stay">{{ i18n.t('experience.editor.action.after.stay') }}</option>
                    <option value="result">{{ i18n.t('experience.editor.action.after.result') }}</option>
                    @if (node.type === 'form') {
                      <option value="reset">{{ i18n.t('experience.editor.action.after.reset') }}</option>
                    }
                    @for (page of doc().pages; track page.id) {
                      @if (page.id !== pageId()) {
                        <option [value]="'page:' + page.id">{{ i18n.t('experience.editor.action.after.page', { page: pageTitle(page) }) }}</option>
                      }
                    }
                  </select>
                </label>
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.action.unavailable') }}</span>
                  <select
                    [disabled]="appsState() !== 'ready'"
                    [value]="row.on_unavailable"
                    (change)="patchBinding(row.binding_key, { on_unavailable: selectValue($event) })"
                  >
                    @for (policy of unavailable; track policy) {
                      <option [value]="policy">{{ i18n.t('experience.editor.unavailable.' + policy) }}</option>
                    }
                  </select>
                </label>
                <details>
                  <summary>{{ i18n.t('experience.editor.action.advanced') }}</summary>
                  <p class="xp-hint">{{ i18n.t('experience.editor.action.key') }} · {{ row.binding_key }}</p>
                  <p class="xp-hint">{{ i18n.t('experience.editor.action.version') }} · {{ row.published_flow_version_id }}</p>
                  <p class="xp-hint">
                    {{ i18n.t('experience.editor.action.fingerprints') }}
                    · {{ row.input_schema_sha256 || '—' }}
                  </p>
                </details>
              } @else {
                <p class="xp-hint">{{ i18n.t('experience.editor.action.pick') }}</p>
              }
            } @else {
              <p class="xp-hint">{{ i18n.t('experience.editor.action.none') }}</p>
            }
            @if (selectedNode(); as node) {
              <div class="xp-inspector-section">
                <h3>{{ i18n.t('experience.editor.data.title') }}</h3>
                <p class="xp-hint">{{ i18n.t('experience.editor.data.hint') }}</p>
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.data.source') }}</span>
                  <select [value]="dataSource(node)" (change)="setDataSource(node, selectValue($event))">
                    <option value="none">{{ i18n.t('experience.editor.data.none') }}</option>
                    @if (supportsRunOutput(node)) {
                      <option value="run-output">{{ i18n.t('experience.editor.data.run') }}</option>
                    }
                    @if (supportsQuery(node)) {
                      <option value="system-binding">{{ i18n.t('experience.editor.data.query') }}</option>
                    }
                  </select>
                </label>
                @if (!supportsRunOutput(node) && !supportsQuery(node)) {
                  <p class="xp-hint">{{ i18n.t('experience.editor.data.unsupported') }}</p>
                }
                @if (dataSource(node) === 'run-output') {
                  <label class="xp-field">
                    <span>{{ i18n.t('experience.editor.data.component') }}</span>
                    <select [value]="dataBinding(node)?.componentId ?? ''" (change)="setDataField(node, 'componentId', selectValue($event))">
                      <option value="">{{ i18n.t('experience.editor.data.choose_component') }}</option>
                      @for (source of sourceNodes(node); track source.id) {
                        <option [value]="source.id">{{ typeLabel(source.type) }} · {{ source.id }}</option>
                      }
                    </select>
                  </label>
                } @else if (dataSource(node) === 'system-binding') {
                  <label class="xp-field">
                    <span>{{ i18n.t('experience.editor.data.binding') }}</span>
                    <select [value]="dataBinding(node)?.bindingKey ?? ''" (change)="setDataField(node, 'bindingKey', selectValue($event))">
                      <option value="">{{ i18n.t('experience.editor.action.none_option') }}</option>
                      @for (row of bindings(); track row.binding_key) {
                        <option [value]="row.binding_key">{{ bindingLabel(row) }}</option>
                      }
                    </select>
                  </label>
                  @if (dataContractState(node) === 'loading') {
                    <p class="xp-hint" role="status">{{ i18n.t('experience.editor.data.contract_loading') }}</p>
                  } @else if (dataContractState(node) === 'error') {
                    <p class="xp-error" role="alert">{{ i18n.t('experience.editor.data.contract_error') }}</p>
                    <button type="button" class="xp-btn" (click)="retryDataContract(node)">
                      {{ i18n.t('experience.wizard.retry') }}
                    </button>
                  } @else if (querySchemaSupported(node)) {
                    <fieldset class="xp-data-fields">
                      <legend>{{ i18n.t('experience.editor.data.parameters') }}</legend>
                      @for (field of queryFields(node); track field.name) {
                        <label class="xp-field">
                          <span>
                            {{ field.label }}
                            @if (field.required) { <span aria-hidden="true"> *</span> }
                          </span>
                          @if (field.kind === 'boolean') {
                            <input
                              type="checkbox"
                              [checked]="queryFieldChecked(node, field)"
                              (change)="setQueryField(node, field, $event)"
                            />
                          } @else if (field.kind === 'enum') {
                            <select [value]="queryFieldValue(node, field)" (change)="setQueryField(node, field, $event)">
                              <option value="">{{ i18n.t('experience.editor.data.choose_value') }}</option>
                              @for (option of field.options; track option; let optionIndex = $index) {
                                <option [value]="option">{{ field.optionLabels[optionIndex] || option }}</option>
                              }
                            </select>
                          } @else if (field.kind !== 'file') {
                            <input
                              [type]="queryFieldInputType(field)"
                              [value]="queryFieldValue(node, field)"
                              [attr.required]="field.required ? '' : null"
                              [attr.aria-describedby]="field.description ? 'xp-query-help-' + field.name : null"
                              (input)="setQueryField(node, field, $event)"
                            />
                          }
                          @if (field.description) {
                            <small [id]="'xp-query-help-' + field.name">{{ field.description }}</small>
                          }
                        </label>
                      } @empty {
                        <p class="xp-hint">{{ i18n.t('experience.editor.data.no_parameters') }}</p>
                      }
                    </fieldset>
                  } @else if (dataBinding(node)?.bindingKey) {
                    <p class="xp-warn">{{ i18n.t('experience.editor.data.parameters_advanced') }}</p>
                  }
                  @if (dataError(); as dataErr) { <p class="xp-error" role="alert">{{ dataErr }}</p> }
                }
                @if (dataSource(node) !== 'none') {
                  <label class="xp-field">
                    <span>{{ i18n.t('experience.editor.data.path') }}</span>
                    <select [value]="dataBinding(node)?.selector ?? ''" (change)="setDataField(node, 'selector', selectValue($event))">
                      @for (option of dataSelectorOptions(node); track option.value) {
                        <option [value]="option.value">
                          {{ option.value ? option.label : i18n.t('experience.editor.data.whole_result') }}
                        </option>
                      }
                    </select>
                  </label>
                  <p class="xp-hint">{{ i18n.t('experience.editor.data.explicit') }}</p>
                  <details>
                    <summary>{{ i18n.t('experience.editor.action.advanced') }}</summary>
                    @if (dataSource(node) === 'system-binding') {
                      <label class="xp-field">
                        <span>{{ i18n.t('experience.editor.data.input') }}</span>
                        <textarea [value]="queryInput(node)" (change)="setQueryInput(node, inputValue($event))"></textarea>
                      </label>
                    }
                    <label class="xp-field">
                      <span>{{ i18n.t('experience.editor.data.selector') }}</span>
                      <input [value]="dataBinding(node)?.selector ?? ''" (input)="setDataField(node, 'selector', inputValue($event))" />
                    </label>
                  </details>
                }
              </div>
            }
          }

          @if (inspectorTab() === 'appearance') {
            @if (selectedNode(); as node) {
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.density') }}</span>
                <select [value]="densityValue(node.props)" (change)="setProp(node, 'density', selectValue($event))">
                  <option value="comfortable">{{ i18n.t('experience.editor.density.comfortable') }}</option>
                  <option value="compact">{{ i18n.t('experience.editor.density.compact') }}</option>
                </select>
              </label>
              @if (supportsSpan(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.span') }}</span>
                  <select [value]="spanValue(node)" (change)="setProp(node, 'span', selectValue($event))">
                    @for (span of spans; track span) {
                      <option [value]="span">{{ i18n.t('experience.editor.span.' + span) }}</option>
                    }
                  </select>
                </label>
              }
              @if (node.type === 'chart') {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.palette') }}</span>
                  <select
                    [value]="paletteValue(node)"
                    (change)="setProp(node, 'palette', selectValue($event))"
                  >
                    @for (palette of palettes; track palette) {
                      <option [value]="palette">
                        {{ i18n.t('experience.editor.palette.' + palette) }}
                      </option>
                    }
                  </select>
                  <small>{{ i18n.t('experience.editor.palette.hint') }}</small>
                </label>
              }
              @if (supportsAccent(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.accent') }}</span>
                  <input type="color" [value]="accentValue(node)" (input)="setProp(node, 'accent', inputValue($event))" />
                </label>
              }
            } @else if (selectedPage(); as page) {
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.density') }}</span>
                <select
                  [value]="densityValue(page.props)"
                  (change)="setPageProp(page.id, 'density', selectValue($event))"
                >
                  <option value="comfortable">{{ i18n.t('experience.editor.density.comfortable') }}</option>
                  <option value="compact">{{ i18n.t('experience.editor.density.compact') }}</option>
                </select>
              </label>
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.theme') }}</span>
                <select
                  [value]="themeValue(page)"
                  (change)="setPageProp(page.id, 'theme', selectValue($event))"
                >
                  <option value="inherit">{{ i18n.t('experience.editor.theme.inherit') }}</option>
                  <option value="light">{{ i18n.t('experience.editor.theme.light') }}</option>
                  <option value="dark">{{ i18n.t('experience.editor.theme.dark') }}</option>
                </select>
              </label>
            } @else {
              <p class="xp-hint">{{ i18n.t('experience.editor.appearance.none') }}</p>
            }
            <p class="xp-hint">{{ i18n.t('experience.editor.appearance.note') }}</p>
          }

          @if (inspectorTab() === 'a11y') {
            @if (selectedNode(); as node) {
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.a11y.label') }}</span>
                <input [value]="localizedA11y(node, 'ariaLabel')" (input)="setLocalizedA11y(node, 'ariaLabel', inputValue($event))" />
              </label>
              @if (supportsHeading(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.a11y.heading') }}</span>
                  <select [value]="headingValue(node)" (change)="setA11y(node, 'headingLevel', headingNumber(selectValue($event)))">
                    <option value="2">{{ i18n.t('experience.editor.a11y.heading.2') }}</option>
                    <option value="3">{{ i18n.t('experience.editor.a11y.heading.3') }}</option>
                    <option value="4">{{ i18n.t('experience.editor.a11y.heading.4') }}</option>
                  </select>
                </label>
              }
              @if (needsEmptyText(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.a11y.empty') }}</span>
                  <textarea
                    [value]="localizedA11y(node, 'emptyText')"
                    (input)="setLocalizedA11y(node, 'emptyText', inputValue($event))"
                  ></textarea>
                </label>
                @if (!localizedA11y(node, 'emptyText')) {
                  <p class="xp-error" role="status">{{ i18n.t('experience.editor.a11y.empty.required') }}</p>
                }
              }
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.a11y.keyboard') }}</span>
                <textarea
                  [value]="localizedA11y(node, 'keyboardHint')"
                  (input)="setLocalizedA11y(node, 'keyboardHint', inputValue($event))"
                ></textarea>
              </label>
              @if (contrastWarn(node)) {
                <p class="xp-error" role="status">{{ i18n.t('experience.editor.a11y.contrast') }}</p>
              }
            } @else {
              <p class="xp-hint">{{ i18n.t('experience.editor.a11y.none') }}</p>
            }
          }
          </fieldset>
        </aside>
      </div>

      <div class="xp-bottom" [class.is-open]="bottomOpen()" [class.is-identity]="bottomTab() === 'access'">
        <div class="xp-bottom-bar">
          <div class="xp-bottom-tabs" role="tablist" [attr.aria-label]="i18n.t('experience.editor.bottom.label')">
            @for (tab of bottomTabs; track tab; let index = $index) {
              <button
                type="button"
                role="tab"
                [id]="'xp-bottom-' + tab"
                aria-controls="xp-bottom-panel"
                [attr.aria-selected]="bottomTab() === tab"
                [attr.aria-expanded]="bottomTab() === tab && bottomOpen()"
                [tabIndex]="bottomTab() === tab ? 0 : -1"
                [class.is-on]="bottomTab() === tab && bottomOpen()"
                (click)="toggleBottom(tab)"
                (keydown)="onBottomTabKey($event, index)"
              >{{ i18n.t('experience.editor.bottom.' + tab) }}</button>
            }
          </div>
          <button type="button" class="xp-ready-link" (click)="openTests()">{{ readyLabel() }}</button>
        </div>
        @if (bottomOpen()) {
          <section
            id="xp-bottom-panel"
            class="xp-bottom-panel"
            role="tabpanel"
            [attr.aria-labelledby]="'xp-bottom-' + bottomTab()"
          >
            @switch (bottomTab()) {
              @case ('data') {
                @if (selectedNode(); as node) {
                  @if (dataBinding(node); as source) {
                    <strong>{{ i18n.t('experience.editor.data.title') }}</strong>
                    <code>{{ source.source }} · {{ source.bindingKey || source.componentId }} · {{ source.selector || 'data' }}</code>
                  } @else { <p class="xp-hint">{{ i18n.t('experience.editor.data.empty') }}</p> }
                } @else { <p class="xp-hint">{{ i18n.t('experience.editor.data.empty') }}</p> }
              }
              @case ('actions') {
                <div class="xp-bottom-list">
                  @for (row of ownBindings(); track row.binding_key) {
                    <span><strong>{{ row.binding_key }}</strong>{{ row.confirmation_policy }} · {{ row.on_unavailable }}</span>
                  } @empty { <p class="xp-hint">{{ i18n.t('experience.editor.action.none') }}</p> }
                </div>
              }
              @case ('access') {
                <div class="xp-journal-grid">
                  <label class="xp-field" for="xp-editor-description">
                    <span>{{ i18n.t('experience.identity.description') }}</span>
                    <textarea
                      id="xp-editor-description"
                      rows="2"
                      maxlength="500"
                      [value]="metadataDescription()"
                      [disabled]="readOnly() || metadataBusy()"
                      (input)="setMetadataDescription($event)"
                    ></textarea>
                    <small class="xp-hint">{{ i18n.t('experience.identity.description.hint') }}</small>
                  </label>
                  <label class="xp-field" for="xp-editor-emblem">
                    <span>{{ i18n.t('experience.identity.emblem') }}</span>
                    <select
                      id="xp-editor-emblem"
                      [value]="metadataEmblem()"
                      [disabled]="readOnly() || metadataBusy()"
                      (change)="setMetadataEmblem($event)"
                    >
                      @if (metadataEmblem() && !knownEmblem(metadataEmblem())) {
                        <option [value]="metadataEmblem()">{{ metadataEmblem() }}</option>
                      }
                      @for (option of emblemOptions; track option.value) {
                        <option [value]="option.value">{{ option.value }} · {{ i18n.t(option.label) }}</option>
                      }
                    </select>
                  </label>
                  <fieldset>
                    <legend>{{ i18n.t('experience.wizard.access.languages') }}</legend>
                    @for (locale of ['fr', 'en']; track locale) {
                      <label>
                        <input
                          type="checkbox"
                          [checked]="metadataLanguages().includes(locale)"
                          [disabled]="readOnly() || metadataBusy()"
                          (change)="toggleMetadataLanguage(locale)"
                        />
                        {{ locale.toUpperCase() }}
                      </label>
                    }
                  </fieldset>
                  <fieldset>
                    <legend>{{ i18n.t('experience.wizard.access.who') }}</legend>
                    <label>
                      <input
                        type="checkbox"
                        [checked]="accessWhole()"
                        [disabled]="readOnly() || metadataBusy()"
                        (change)="toggleMetadataWhole()"
                      />
                      {{ i18n.t('experience.wizard.access.whole_workspace') }}
                    </label>
                    @for (role of accessRolesList; track role) {
                      <label>
                        <input
                          type="checkbox"
                          [checked]="accessRoles().includes(role)"
                          [disabled]="readOnly() || metadataBusy() || accessWhole()"
                          (change)="toggleMetadataRole(role)"
                        />
                        {{ i18n.t('governance.access.role.' + role) }}
                      </label>
                    }
                    <label class="xp-field" for="xp-editor-access-groups">
                      <span>{{ i18n.t('experience.wizard.access.groups') }}</span>
                      <input
                        id="xp-editor-access-groups"
                        type="text"
                        [value]="accessGroups().join(', ')"
                        [disabled]="readOnly() || metadataBusy() || accessWhole()"
                        (input)="setMetadataGroups($event)"
                      />
                    </label>
                  </fieldset>
                  <label class="xp-field" for="xp-editor-theme">
                    <span>{{ i18n.t('experience.wizard.access.theme') }}</span>
                    <select
                      id="xp-editor-theme"
                      [value]="metadataTheme()"
                      [disabled]="readOnly() || metadataBusy()"
                      (change)="setMetadataTheme($event)"
                    >
                      @for (mode of ['default', 'light', 'dark']; track mode) {
                        <option [value]="mode" [selected]="metadataTheme() === mode">{{ i18n.t('experience.wizard.access.theme.' + mode) }}</option>
                      }
                    </select>
                  </label>
                  @if (!detail()?.theme?.['live_href']) {
                    <app-brand-appearance-editor [name]="detail()?.name || ''" [appearance]="metadataAppearance()" [disabled]="readOnly() || metadataBusy()" (changed)="setMetadataAppearance($event)" />
                    <p class="xp-hint">{{ i18n.t('experience.brand.publish_hint') }}</p>
                  } @else { <p class="xp-hint">{{ i18n.t('experience.brand.native_preserved') }}</p> }
                  @if (!readOnly()) {
                    <button
                      type="button"
                      class="xp-btn xp-btn-primary"
                      [disabled]="metadataBusy() || !metadataDirty() || !metadataValid()"
                      (click)="saveMetadata()"
                    >
                      {{ i18n.t(metadataBusy() ? 'experience.wizard.saving' : 'common.save') }}
                    </button>
                  }
                </div>
              }
              @case ('tests') {
                @if (ready(); as check) {
                  <div class="xp-bottom-list">
                    @for (item of check.blockers; track item.code ?? item.message) { <span class="xp-error">{{ item.message || item.code }}</span> }
                    @for (item of check.warnings; track item.code ?? item.message) { <span class="xp-warn">{{ item.message || item.code }}</span> }
                    @if (check.blockers.length === 0 && check.warnings.length === 0) { <span>{{ i18n.t('experience.editor.ready.ok') }}</span> }
                  </div>
                } @else if (readyState() === 'error') {
                  <p class="xp-error" role="alert">{{ i18n.t('experience.editor.ready.error') }}</p>
                  <button type="button" class="xp-btn" (click)="retryReady()">{{ i18n.t('experience.wizard.retry') }}</button>
                } @else { <p class="xp-hint">{{ i18n.t('experience.publish.loading') }}</p> }
              }
              @case ('journal') {
                <div class="xp-journal-grid">
                  <section
                    class="xp-journal-history"
                    aria-labelledby="xp-draft-history-title"
                    [attr.aria-busy]="draftHistoryState() === 'loading' || draftHistoryBusy()"
                  >
                    <h3 id="xp-draft-history-title" tabindex="-1">
                      {{ i18n.t('experience.editor.history.title') }}
                    </h3>
                    <p class="xp-hint">{{ i18n.t('experience.editor.history.help') }}</p>
                    @if (draftHistoryState() === 'loading' && draftHistory().length === 0) {
                      <p class="xp-hint" role="status">{{ i18n.t('experience.editor.history.loading') }}</p>
                    }
                    @if (draftHistoryState() === 'error') {
                      <div class="xp-row xp-error" role="alert">
                        <span>{{ i18n.t('experience.editor.history.error') }}</span>
                        <button type="button" class="xp-btn" (click)="retryDraftHistory()">
                          {{ i18n.t('experience.wizard.retry') }}
                        </button>
                      </div>
                    }
                    <ol class="xp-history-list">
                      @for (revision of draftHistory(); track revision.id) {
                        <li class="xp-journal-row xp-history-row">
                          <div class="xp-history-meta">
                            <div class="xp-history-heading">
                              <strong>{{ i18n.t('experience.editor.history.revision', { n: revision.revision }) }}</strong>
                              @if (revision.revision === detail()?.draft?.revision) {
                                <span class="xp-tag">{{ i18n.t('experience.editor.history.current') }}</span>
                              }
                            </div>
                            <span>{{ i18n.t('experience.editor.history.saved_by', { name: revision.saved_by || i18n.t('experience.editor.history.unknown_author') }) }}</span>
                            <time [attr.datetime]="revision.created_at || null">{{ historyDate(revision.created_at) }}</time>
                            <code
                              [title]="revision.content_sha256"
                              [attr.aria-label]="i18n.t('experience.editor.history.hash', { hash: revision.content_sha256 })"
                            >{{ shortHash(revision.content_sha256) }}</code>
                          </div>
                          @if (!readOnly() && revision.revision !== detail()?.draft?.revision) {
                            <button
                              type="button"
                              class="xp-btn"
                              [disabled]="!canRestoreRevision(revision)"
                              [attr.title]="restoreDisabledHint(revision)"
                              (click)="requestDraftRestore(revision)"
                            >
                              {{ i18n.t('experience.editor.history.restore') }}
                            </button>
                          }
                        </li>
                      } @empty {
                        @if (draftHistoryState() === 'ready') {
                          <li class="xp-hint">{{ i18n.t('experience.editor.history.empty') }}</li>
                        }
                      }
                    </ol>
                  </section>
                  <section>
                    <h3>{{ i18n.t('experience.editor.lifecycle.releases') }}</h3>
                    @for (release of releases(); track release.id) {
                      <div class="xp-journal-row">
                        <span>R{{ release.release_number }} · {{ release.created_at || '—' }}</span>
                        @if (canRelease()) {
                          <button type="button" class="xp-btn" [disabled]="lifecycleBusy()" (click)="openDeployment(release, $event)">
                            {{ i18n.t('experience.editor.lifecycle.deploy') }}
                          </button>
                        }
                      </div>
                    } @empty { <p class="xp-hint">{{ i18n.t('experience.publish.recap.none') }}</p> }
                  </section>
                  <section>
                    <h3>{{ i18n.t('experience.editor.lifecycle.deployments') }}</h3>
                    @for (deployment of detail()?.deployments ?? []; track deployment.id ?? deployment.channel) {
                      <div class="xp-journal-row">
                        <span>{{ deployment.channel }} · {{ deployment.release_id }}</span>
                        @if (canRelease()) {
                          <button
                            type="button"
                            class="xp-btn"
                            [disabled]="lifecycleBusy() || !deployment.previous_release_id || !deployment.updated_at"
                            (click)="rollback(deployment)"
                          >{{ i18n.t('experience.editor.lifecycle.rollback') }}</button>
                        }
                      </div>
                    }
                  </section>
                  <section>
                    <h3>{{ i18n.t('experience.editor.lifecycle.drift') }}</h3>
                    @for (drift of relevantDrifts(); track drift.binding.binding_key) {
                      <div class="xp-journal-row">
                        <span>{{ drift.binding.binding_key }} · {{ drift.reasons.join(', ') }}</span>
                        @if (!readOnly()) {
                          <button type="button" class="xp-btn" [disabled]="lifecycleBusy()" (click)="repairDrift(drift)">{{ i18n.t('experience.editor.lifecycle.repair') }}</button>
                        }
                      </div>
                    } @empty { <p class="xp-hint">{{ i18n.t('experience.editor.lifecycle.no_drift') }}</p> }
                  </section>
                </div>
              }
            }
          </section>
        }
      </div>
    </div>

    <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {{ draftHistoryStatus() }}
    </p>

    <app-confirm-dialog
      [open]="restoreCandidate() !== null"
      [title]="i18n.t('experience.editor.history.confirm.title', { n: restoreCandidate()?.revision ?? '—' })"
      [description]="i18n.t('experience.editor.history.confirm.body', { current: detail()?.draft?.revision ?? '—', target: restoreCandidate()?.revision ?? '—' })"
      [confirmLabel]="i18n.t('experience.editor.history.confirm.action')"
      [cancelLabel]="i18n.t('common.cancel')"
      tone="brand"
      icon="history"
      (confirm)="restoreDraftRevision()"
      (cancel)="cancelDraftRestore()"
    />

    @if (id(); as experienceId) {
      @if (lockedDraft(); as draft) {
      <app-experience-publish-dialog
        [experienceId]="experienceId"
        [draft]="draft"
        [experienceUpdatedAt]="detail()?.updated_at ?? ''"
        [deployments]="detail()?.deployments ?? []"
        [audience]="audience()"
        [summary]="summary()"
        [initialRelease]="deploymentRelease()"
        [open]="publishOpen()"
        [returnFocus]="publishTrigger"
        (closed)="closePublish()"
        (released)="reloadLifecycle()"
        (deployed)="reload()"
        (refreshRequested)="reloadDeployments()"
      />
      }
    }
  `,
})
export class ExperienceEditorComponent implements OnDestroy {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StudioApiService);
  private readonly route = inject(ActivatedRoute);
  protected readonly workspace = inject(WorkspaceService);
  readonly addable = ADDABLE_TYPES;
  readonly confirms = CONFIRMATION_POLICIES;
  readonly unavailable = UNAVAILABLE_POLICIES;
  readonly tabs: Tab[] = ['content', 'action', 'appearance', 'a11y'];
  readonly leftTabs: LeftTab[] = ['pages', 'components'];
  readonly viewports: Viewport[] = ['desktop', 'tablet', 'mobile'];
  readonly bottomTabs: BottomTab[] = ['data', 'actions', 'access', 'tests', 'journal'];
  readonly accessRolesList = ACCESS_ROLES;
  readonly emblemOptions = [
    { value: '◇', label: 'experience.identity.emblem.diamond' },
    { value: '✦', label: 'experience.identity.emblem.sparkle' },
    { value: '✓', label: 'experience.identity.emblem.check' },
    { value: '▦', label: 'experience.identity.emblem.grid' },
    { value: '◆', label: 'experience.identity.emblem.shield' },
    { value: '⚑', label: 'experience.identity.emblem.flag' },
  ] as const;
  readonly spans = NODE_SPANS;
  readonly palettes = CHART_PALETTES;
  readonly supportsAccent = supportsAccent;
  readonly supportsHeading = supportsHeading;
  readonly supportsSpan = supportsSpan;
  readonly needsEmptyText = needsEmptyText;

  readonly id = signal<string | null>(null);
  readonly name = signal('');
  readonly slug = signal('');
  readonly detail = signal<StudioDetail | null>(null);
  readonly stack = signal<RevisionStack>(emptyStack({ pages: [] }));
  readonly selection = signal<Selection | null>(null);
  readonly inspectorTab = signal<Tab>('content');
  readonly leftTab = signal<LeftTab>('pages');
  readonly viewport = signal<Viewport>('desktop');
  readonly previewRole = signal('workspace_viewer');
  readonly previewGroup = signal('');
  readonly bottomTab = signal<BottomTab>('data');
  readonly bottomOpen = signal(false);
  readonly contentLocale = signal('fr');
  readonly bindings = signal<StudioBinding[]>([]);
  readonly saving = signal(false);
  readonly saved = signal(false);
  readonly error = signal<string | null>(null);
  readonly publishOpen = signal(false);
  readonly prompt = signal('');
  readonly proposal = signal<AssistantProposal | null>(null);
  readonly assistantMiss = signal(false);
  readonly bindingKeys = signal<string[]>([]);
  readonly ready = signal<ReadyCheck | null>(null);
  readonly readyState = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  readonly apps = signal<StudioExperience[]>([]);
  readonly lockedDraft = signal<StudioDraft | null>(null);
  readonly releases = signal<StudioRelease[]>([]);
  readonly draftHistory = signal<StudioDraftRevision[]>([]);
  readonly draftHistoryState = signal<'idle' | 'loading' | 'ready' | 'error'>('idle');
  readonly draftHistoryBusy = signal(false);
  readonly draftHistoryStatus = signal('');
  readonly restoreCandidate = signal<StudioDraftRevision | null>(null);
  readonly deploymentRelease = signal<StudioRelease | null>(null);
  readonly drifts = signal<StudioDrift[]>([]);
  readonly publishedVersions = signal<Record<string, string>>({});
  readonly lifecycleBusy = signal(false);
  readonly dataError = signal<string | null>(null);
  readonly dataContracts = signal<Record<string, StudioIngressList>>({});
  readonly dataContractStates = signal<Record<string, 'loading' | 'ready' | 'error'>>({});
  readonly requestedPageId = signal<string | null>(null);
  readonly returnTo = signal<string | null>(null);
  readonly originReleaseId = signal<string | null>(null);
  readonly originReleaseNumber = signal<number | null>(null);
  readonly backHref = computed(() => this.returnTo() ?? navigationSurfaceUrl('create-apps'));
  readonly accessRoles = signal<string[]>([]);
  readonly accessGroups = signal<string[]>([]);
  readonly accessWhole = signal(false);
  readonly metadataLanguages = signal<string[]>([]);
  readonly metadataTheme = signal('default');
  readonly metadataAppearance = signal<BrandAppearance>({});
  private appearanceEdited = false;
  readonly metadataDescription = signal('');
  readonly metadataEmblem = signal('◇');
  readonly metadataBusy = signal(false);
  readonly metadataDirty = signal(false);
  readonly bindingsState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly appsState = signal<'loading' | 'ready' | 'error'>('loading');
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private readyTimer: ReturnType<typeof setTimeout> | null = null;
  private editGeneration = 0;
  private saveQueued = false;
  private publishRequested = false;
  private loadGeneration = 0;
  private readyGeneration = 0;
  private routeScope = new Subscription();
  private readonly routeSubscription: Subscription;
  private readonly querySubscription: Subscription;
  private readonly actionBindingRequests = new Map<string, Subscription>();

  readonly doc = computed(() => this.stack().present);
  readonly readOnly = computed(() => !canEditExperienceStudio(
    this.workspace.current()?.role_template,
    this.workspace.current()?.role,
    this.workspace.isAdmin(),
  ));
  readonly canRelease = computed(() => canReleaseExperienceStudio(
    this.workspace.current()?.role_template,
    this.workspace.current()?.role,
    this.workspace.isAdmin(),
  ));
  readonly previewDoc = computed(() => localizeDocument(this.doc(), this.contentLocale()));
  readonly editableLocales = computed(() => {
    const configured = [...new Set(
      this.detail()?.languages
        ?.map((locale) => locale.toLowerCase().slice(0, 2))
        .filter((locale) => locale === 'fr' || locale === 'en') ?? [],
    )];
    return configured.length > 0 ? configured : ['fr', 'en'];
  });
  readonly pageId = computed(() => {
    const sel = this.selection();
    return sel?.pageId ?? this.doc().pages[0]?.id ?? null;
  });
  readonly viewSlug = computed(() => {
    const row = this.detail();
    if (!row) return null;
    return inventoryState(row.deployments) === 'draft' ? null : row.slug;
  });
  readonly audience = computed<Record<string, unknown>>(() => experienceAccessPolicy(this.detail()));
  readonly previewAccessPolicy = computed<Record<string, unknown>>(() => this.detail() ? {
    roles: this.accessWhole() ? [] : this.accessRoles(),
    groups: this.accessWhole() ? [] : this.accessGroups(),
  } : {});
  readonly previewAllowed = computed(() => simulatedExperienceAccess(
    this.previewAccessPolicy(),
    this.previewRole(),
    this.previewGroup(),
  ));
  readonly catalogLoading = computed(() => this.bindingsState() === 'loading' || this.appsState() === 'loading');
  readonly catalogFailed = computed(() => this.bindingsState() === 'error' || this.appsState() === 'error');

  readonly relevantDrifts = computed(() => {
    const keys = new Set(this.bindingKeys());
    return this.drifts().filter((row) => keys.has(row.binding.binding_key));
  });

  /** Bindings this app already uses come first; the rest stay reachable. */
  readonly ownBindings = computed(() => {
    const keys = new Set(this.bindingKeys());
    return this.bindings().filter((row) => keys.has(row.binding_key));
  });

  readonly otherBindings = computed(() => {
    const keys = new Set(this.bindingKeys());
    return this.bindings().filter((row) => !keys.has(row.binding_key));
  });

  readonly stateLabel = computed(() => {
    const row = this.detail();
    const state = this.i18n.t(`experience.apps.state.${inventoryState(row?.deployments)}`);
    const n = row?.latest_release_number;
    return n ? `${state} · ${this.i18n.t('experience.apps.release.n', { n })}` : state;
  });

  readonly readyTone = computed<'ok' | 'warn' | null>(() => {
    const check = this.ready();
    if (!check) return null;
    if (check.blockers.length > 0) return 'warn';
    return check.warnings.length > 0 ? 'warn' : 'ok';
  });

  readonly readyLabel = computed(() => {
    const check = this.ready();
    if (!check) {
      return this.readyState() === 'error'
        ? this.i18n.t('experience.editor.ready.error')
        : this.i18n.t('experience.publish.loading');
    }
    if (check.blockers.length > 0) {
      return this.i18n.t('experience.editor.ready.block', { n: check.blockers.length });
    }
    if (check.warnings.length > 0) {
      return this.i18n.t('experience.editor.ready.warn', { n: check.warnings.length });
    }
    return this.i18n.t('experience.editor.ready.ok');
  });

  readonly summary = computed(() => ({
    pages: this.doc().pages.length,
    components: this.doc().pages.reduce((total, page) => total + page.components.length, 0),
    bindingKeys: this.bindingKeys(),
    languages: this.detail()?.languages ?? [],
  }));

  constructor() {
    this.routeSubscription = this.route.paramMap.subscribe((params) => this.openRoute(params.get('id')));
    this.querySubscription = this.route.queryParamMap.subscribe((params) => {
      const pageId = params.get('pageId');
      this.requestedPageId.set(pageId && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(pageId) ? pageId : null);
      const back = params.get('returnTo');
      this.returnTo.set(back && /^\/work(?:\/|$)/.test(back) && !back.includes('\\') ? back : null);
      const releaseId = params.get('releaseId');
      this.originReleaseId.set(
        releaseId && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(releaseId) ? releaseId : null,
      );
      const releaseNumber = Number(params.get('releaseNumber'));
      this.originReleaseNumber.set(
        Number.isSafeInteger(releaseNumber) && releaseNumber > 0 ? releaseNumber : null,
      );
      this.selectRequestedPage();
    });
    this.loadCatalogs();
  }

  ngOnDestroy(): void {
    this.routeSubscription.unsubscribe();
    this.querySubscription.unsubscribe();
    this.cancelRouteWork();
  }

  confirmDiscardChanges(): boolean {
    return !this.hasPendingChanges()
      || globalThis.confirm(this.i18n.t('experience.editor.discard_confirm'));
  }

  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: BeforeUnloadEvent): void {
    if (!this.hasPendingChanges()) return;
    event.preventDefault();
    event.returnValue = '';
  }

  private hasPendingChanges(): boolean {
    return !!this.detail()
      && (!this.saved() || this.saving() || this.saveQueued || this.metadataDirty() || this.metadataBusy());
  }

  @HostListener('document:keydown', ['$event'])
  onKey(event: KeyboardEvent): void {
    if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z') return;
    const target = event.target as HTMLElement | null;
    if (target?.closest('input, textarea, select')) return;
    event.preventDefault();
    if (event.shiftKey) this.redo();
    else this.undo();
  }

  isPageSelected(pageId: string): boolean {
    const sel = this.selection();
    return sel?.kind === 'page' && sel.pageId === pageId;
  }

  isNodeSelected(nodeId: string | undefined): boolean {
    const sel = this.selection();
    return !!nodeId && sel?.kind === 'node' && sel.nodeId === nodeId;
  }

  selectPage(pageId: string): void {
    this.selection.set({ kind: 'page', pageId });
  }

  selectNode(pageId: string, nodeId: string | undefined): void {
    if (!nodeId) return;
    this.selection.set({ kind: 'node', pageId, nodeId });
    const node = findNode(this.doc(), nodeId)?.node;
    if (node) this.ensureNodeDataContract(node);
  }

  onLeftTabKey(event: KeyboardEvent, index: number): void {
    const next = this.tabIndex(event, index, this.leftTabs.length);
    if (next === null) return;
    this.leftTab.set(this.leftTabs[next]!);
    this.focusSiblingTab(event, next);
  }

  onInspectorTabKey(event: KeyboardEvent, index: number): void {
    const next = this.tabIndex(event, index, this.tabs.length);
    if (next === null) return;
    this.inspectorTab.set(this.tabs[next]!);
    this.focusSiblingTab(event, next);
  }

  onBottomTabKey(event: KeyboardEvent, index: number): void {
    const next = this.tabIndex(event, index, this.bottomTabs.length);
    if (next === null) return;
    this.bottomTab.set(this.bottomTabs[next]!);
    this.bottomOpen.set(true);
    this.focusSiblingTab(event, next);
  }

  onViewportKey(event: KeyboardEvent, index: number): void {
    const next = this.tabIndex(event, index, this.viewports.length);
    if (next === null) return;
    this.viewport.set(this.viewports[next]!);
    this.focusSiblingRadio(event, next);
  }

  onLocaleKey(event: KeyboardEvent, index: number): void {
    const locales = this.editableLocales();
    const next = this.tabIndex(event, index, locales.length);
    if (next === null) return;
    this.contentLocale.set(locales[next]!);
    this.focusSiblingRadio(event, next);
  }

  onOutlineKey(event: KeyboardEvent, pageId: string, nodeId: string | undefined): void {
    if (this.readOnly()) return;
    if (!event.altKey || !nodeId || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
    const node = findNode(this.doc(), nodeId)?.node;
    if (!node) return;
    const delta = event.key === 'ArrowUp' ? -1 : 1;
    const { index, total } = nodeIndex(this.doc(), nodeId);
    if (index + delta < 0 || index + delta >= total) return;
    event.preventDefault();
    this.selectNode(pageId, nodeId);
    this.moveSelected(delta);
  }

  private tabIndex(event: KeyboardEvent, index: number, total: number): number | null {
    let next: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % total;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + total) % total;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = total - 1;
    if (next !== null) event.preventDefault();
    return next;
  }

  private focusSiblingTab(event: KeyboardEvent, index: number): void {
    const tabs = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role="tab"]');
    queueMicrotask(() => tabs?.[index]?.focus());
  }

  private focusSiblingRadio(event: KeyboardEvent, index: number): void {
    const radios = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role="radio"]');
    queueMicrotask(() => radios?.[index]?.focus());
  }

  selectedPage() {
    const sel = this.selection();
    if (!sel) return null;
    return this.doc().pages.find((page) => page.id === sel.pageId) ?? null;
  }

  selectedNode(): ExperienceNode | null {
    const sel = this.selection();
    if (sel?.kind !== 'node') return null;
    return findNode(this.doc(), sel.nodeId)?.node ?? null;
  }

  actionNode(): ExperienceNode | null {
    const node = this.selectedNode();
    if (node && (node.type === 'form' || node.type === 'action_button' || node.props?.['bindingKey'])) {
      return node;
    }
    return null;
  }

  hasProp(node: ExperienceNode, key: string): boolean {
    const map: Record<string, string[]> = {
      header: ['title', 'subtitle'],
      approval_card: ['title', 'body'],
      callout: ['body'],
      action_button: ['label'],
      kpi: ['label', 'value'],
      section: ['title'],
      table: ['caption'],
      map_panel: ['title'],
      agenda_panel: ['title'],
      intelligence_feed: ['title'],
      decision_queue: ['title'],
    };
    return (map[node.type] ?? Object.keys(node.props ?? {})).includes(key);
  }

  str(node: ExperienceNode, key: string): string {
    const value = node.props?.[key];
    return typeof value === 'string' ? value : this.isLocalized(value) ? value.fallback : '';
  }

  pageTitle(page: ExperiencePage): string {
    return textFallback(page.title);
  }

  workLink(slug: string): string {
    return workPageHref(slug, this.pageId());
  }

  pageFallback(page: ExperiencePage): string {
    return textFallback(page.title);
  }

  localizedValue(value: unknown): string {
    if (typeof value === 'string') return value;
    if (!this.isLocalized(value)) return '';
    return this.doc().i18n?.[this.contentLocale()]?.[value.$i18n] ?? value.fallback;
  }

  localizedProp(node: ExperienceNode, key: string): string {
    return this.localizedValue(node.props?.[key]);
  }

  formFields(node: ExperienceNode): RuntimeField[] {
    return node.type === 'form' ? fieldsFromSchema(node.props?.['schema']) : [];
  }

  formCopyValue(
    node: ExperienceNode,
    field: RuntimeField,
    kind: 'label' | 'description' | 'option',
    option: string | null = null,
  ): string {
    const value = this.formCopyRef(node, field.name, kind, option);
    return this.localizedValue(value) || this.formCopyFallback(field, kind, option);
  }

  formCopyNeedsTranslation(
    node: ExperienceNode,
    field: RuntimeField,
    kind: 'label' | 'description' | 'option',
    option: string | null = null,
  ): boolean {
    if ((this.detail()?.languages?.length ?? 0) < 2) return false;
    const value = this.formCopyRef(node, field.name, kind, option);
    if (kind === 'description' && !field.description && !value) return false;
    if (!this.isLocalized(value)) return true;
    return !this.doc().i18n?.[this.contentLocale()]?.[value.$i18n]?.trim();
  }

  setLocalizedFormCopy(
    node: ExperienceNode,
    field: RuntimeField,
    kind: 'label' | 'description' | 'option',
    value: string,
    option: string | null = null,
    optionIndex = 0,
  ): void {
    if (this.readOnly() || !node.id) return;
    const next = cloneDocument(this.doc());
    const target = findNode(next, node.id)?.node;
    if (!target) return;
    const presentation = this.record(target.props?.['fieldPresentation']) ?? {};
    const fieldCopy = this.record(presentation[field.name]) ?? {};
    const options = this.record(fieldCopy['options']) ?? {};
    const current = kind === 'option' && option !== null ? options[option] : fieldCopy[kind];
    if (kind === 'description' && !current && !field.description && !value.trim()) return;
    const suffix = kind === 'option' ? `option.${optionIndex}` : kind;
    const key = this.isLocalized(current)
      ? current.$i18n
      : `component.${node.id}.field.${encodeURIComponent(field.name)}.${suffix}`;
    const contractFallback = this.formCopyFallback(field, kind, option);
    const fallback = typeof current === 'string'
      ? current
      : this.isLocalized(current)
        ? contractFallback ? current.fallback : value.trim() || current.fallback
        : contractFallback || value.trim();
    const localized = { $i18n: key, fallback };
    const nextFieldCopy = kind === 'option' && option !== null
      ? { ...fieldCopy, options: { ...options, [option]: localized } }
      : { ...fieldCopy, [kind]: localized };
    target.props = {
      ...(target.props ?? {}),
      fieldPresentation: { ...presentation, [field.name]: nextFieldCopy },
    };
    this.setDictionaryValue(next, key, value);
    this.commit(next);
  }

  private formCopyRef(
    node: ExperienceNode,
    field: string,
    kind: 'label' | 'description' | 'option',
    option: string | null,
  ): unknown {
    const presentation = this.record(node.props?.['fieldPresentation']);
    const fieldCopy = this.record(presentation?.[field]);
    return kind === 'option' && option !== null
      ? this.record(fieldCopy?.['options'])?.[option]
      : fieldCopy?.[kind];
  }

  private formCopyFallback(
    field: RuntimeField,
    kind: 'label' | 'description' | 'option',
    option: string | null,
  ): string {
    return kind === 'label' ? field.label : kind === 'description' ? field.description : option ?? '';
  }

  setLocalizedPageTitle(page: ExperiencePage, value: string): void {
    if (this.readOnly()) return;
    const next = cloneDocument(this.doc());
    const target = next.pages.find((row) => row.id === page.id);
    if (!target) return;
    const key = this.isLocalized(target.title) ? target.title.$i18n : `page.${page.id}.title`;
    const fallback = textFallback(target.title);
    target.title = { $i18n: key, fallback };
    this.setDictionaryValue(next, key, value);
    this.commit(next);
  }

  setLocalizedProp(node: ExperienceNode, keyName: string, value: string): void {
    if (this.readOnly()) return;
    const next = cloneDocument(this.doc());
    const target = findNode(next, node.id ?? null)?.node;
    if (!target || !node.id) return;
    const current = target.props?.[keyName];
    const key = this.isLocalized(current) ? current.$i18n : `component.${node.id}.${keyName}`;
    const fallback = typeof current === 'string' ? current : this.isLocalized(current) ? current.fallback : '';
    target.props = { ...(target.props ?? {}), [keyName]: { $i18n: key, fallback } };
    this.setDictionaryValue(next, key, value);
    this.commit(next);
  }

  private setDictionaryValue(doc: ExperienceDocument, key: string, value: string): void {
    const locale = this.contentLocale();
    doc.i18n = { ...(doc.i18n ?? {}), [locale]: { ...(doc.i18n?.[locale] ?? {}), [key]: value } };
  }

  private isLocalized(value: unknown): value is LocalizedText {
    return !!value && typeof value === 'object'
      && typeof (value as LocalizedText).$i18n === 'string'
      && typeof (value as LocalizedText).fallback === 'string';
  }

  typeLabel(type: string): string {
    const key = `experience.editor.type.${type}`;
    const label = this.i18n.t(key);
    return label === key ? type : label;
  }

  bound(node: ExperienceNode): StudioBinding | null {
    const key = this.str(node, 'bindingKey');
    return this.bindings().find((row) => row.binding_key === key) ?? null;
  }

  bindingLabel(row: StudioBinding): string {
    const action = humanizeIdentifier(row.ingress_id);
    const binding = humanizeIdentifier(row.binding_key);
    return action && action !== binding ? `${action} · ${binding}` : action || binding;
  }

  /** Other applications this binding serves — editing its rules changes theirs too. */
  sharedWith(key: string): string[] {
    return bindingSharedWith(this.apps(), key, this.id());
  }

  inputNames(node: ExperienceNode): string[] {
    return fieldsFromSchema(node.props?.['schema']).map((field) => field.label || field.name);
  }

  setActionBinding(node: ExperienceNode, key: string): void {
    if (this.readOnly() || !node.id) return;
    this.actionBindingRequests.get(node.id)?.unsubscribe();
    this.actionBindingRequests.delete(node.id);
    const binding = this.bindings().find((row) => row.binding_key === key);
    if (!key) {
      this.setProp(node, 'bindingKey', key);
      return;
    }
    if (!binding) {
      this.error.set(this.i18n.t('experience.editor.catalog.error'));
      return;
    }
    const routeId = this.id();
    const nodeId = node.id;
    const request = this.api.listIngresses(binding.system_id).subscribe({
      next: (body) => {
        if (this.id() !== routeId || this.actionBindingRequests.get(nodeId) !== request) return;
        const ingress = body?.ingresses.find((row) => row.ingress_id === binding.ingress_id);
        const current = findNode(this.doc(), nodeId)?.node;
        if (!ingress || !current) {
          this.error.set(this.i18n.t('experience.editor.catalog.error'));
          return;
        }
        const schema = ingress.input_schema ?? { type: 'object', properties: {} };
        if (current.type === 'action_button' && fieldsFromSchema(schema).length > 0) {
          this.error.set(this.i18n.t('experience.editor.action.requires_form'));
          return;
        }
        this.setProps(current, current.type === 'form'
          ? { bindingKey: key, schema }
          : { bindingKey: key, input: {} });
        if (!this.bindingKeys().includes(key)) this.bindingKeys.update((keys) => [...keys, key]);
      },
      error: () => {
        if (this.id() === routeId && this.actionBindingRequests.get(nodeId) === request) {
          this.error.set(this.i18n.t('experience.editor.catalog.error'));
        }
      },
    });
    this.actionBindingRequests.set(nodeId, request);
    this.trackRoute(request);
  }

  dataSource(node: ExperienceNode): 'none' | RuntimeDataBinding['source'] {
    if (this.record(node.props?.['queryBinding'])) return 'system-binding';
    if (this.record(node.props?.['dataBinding'])) return 'run-output';
    return 'none';
  }

  dataBinding(node: ExperienceNode): RuntimeDataBinding | null {
    const resolved = runtimeDataBinding(node);
    if (resolved) return resolved;
    const source = this.dataSource(node);
    if (source === 'none') return null;
    const raw = this.record(source === 'system-binding' ? node.props?.['queryBinding'] : node.props?.['dataBinding']);
    return {
      source,
      componentId: typeof raw?.['componentId'] === 'string' ? raw['componentId'] : undefined,
      bindingKey: typeof raw?.['bindingKey'] === 'string' ? raw['bindingKey'] : undefined,
      selector: typeof raw?.['selector'] === 'string' ? raw['selector'] : '',
      input: this.record(raw?.['input']) ?? {},
    };
  }

  sourceNodes(node: ExperienceNode): ExperienceNode[] {
    return this.selectedPage()?.components.filter(
      (item) => item.id && item.id !== node.id && this.executableSource(item),
    ) ?? [];
  }

  supportsRunOutput(node: ExperienceNode): boolean {
    return RUN_OUTPUT_TARGETS.has(node.type);
  }

  supportsQuery(node: ExperienceNode): boolean {
    return QUERY_TARGETS.has(node.type);
  }

  private executableSource(node: ExperienceNode): boolean {
    if (node.type === 'form' || node.type === 'action_button') {
      return !!this.str(node, 'bindingKey');
    }
    const query = this.record(node.props?.['queryBinding']);
    return this.supportsQuery(node)
      && query?.['source'] === 'system-binding'
      && typeof query['bindingKey'] === 'string'
      && !!query['bindingKey'].trim();
  }

  setDataSource(node: ExperienceNode, source: string): void {
    if (this.readOnly()) return;
    this.dataError.set(null);
    this.dataContracts.set({});
    this.dataContractStates.set({});
    if (source === 'run-output' && this.supportsRunOutput(node)) {
      this.setProps(node, {
        dataBinding: { source, componentId: '', selector: '' },
        queryBinding: undefined,
      });
    } else if (source === 'system-binding' && this.supportsQuery(node)) {
      this.setProps(node, {
        queryBinding: { source, bindingKey: '', input: {}, selector: '' },
        dataBinding: undefined,
      });
    } else {
      this.setProps(node, { dataBinding: undefined, queryBinding: undefined });
    }
  }

  setDataField(node: ExperienceNode, key: 'componentId' | 'bindingKey' | 'selector', value: string): void {
    if (this.readOnly()) return;
    const source = this.dataSource(node);
    if (source === 'none') return;
    const prop = source === 'system-binding' ? 'queryBinding' : 'dataBinding';
    const current = this.record(node.props?.[prop]) ?? {};
    this.setProp(node, prop, { ...current, source, [key]: value });
    if (key === 'bindingKey' && value && !this.bindingKeys().includes(value)) {
      this.bindingKeys.update((keys) => [...keys, value]);
    }
    if (key === 'bindingKey' && value) this.loadDataContract(value);
    if (key === 'componentId' && value) {
      const sourceNode = this.selectedPage()?.components.find((item) => item.id === value);
      const sourceKey = sourceNode ? this.nodeBindingKey(sourceNode) : '';
      if (sourceKey) this.loadDataContract(sourceKey);
    }
  }

  dataContractState(node: ExperienceNode): 'idle' | 'loading' | 'ready' | 'error' {
    const key = this.dataContractKey(node);
    return key ? this.dataContractStates()[key] ?? 'idle' : 'idle';
  }

  retryDataContract(node: ExperienceNode): void {
    const key = this.dataContractKey(node);
    if (key) this.loadDataContract(key, true);
  }

  queryFields(node: ExperienceNode): RuntimeField[] {
    const ingress = this.queryIngress(node);
    if (!ingress || !formSchemaSupported(ingress.input_schema)) return [];
    const fields = fieldsFromSchema(ingress.input_schema);
    return fields.some((field) => field.kind === 'file') ? [] : fields;
  }

  querySchemaSupported(node: ExperienceNode): boolean {
    const ingress = this.queryIngress(node);
    return !!ingress
      && formSchemaSupported(ingress.input_schema)
      && !fieldsFromSchema(ingress.input_schema).some((field) => field.kind === 'file');
  }

  queryFieldValue(node: ExperienceNode, field: RuntimeField): string {
    const value = this.dataBinding(node)?.input[field.name];
    return value === undefined || value === null ? '' : String(value);
  }

  queryFieldChecked(node: ExperienceNode, field: RuntimeField): boolean {
    return this.dataBinding(node)?.input[field.name] === true;
  }

  queryFieldInputType(field: RuntimeField): 'text' | 'number' | 'date' {
    if (field.kind === 'number' || field.kind === 'integer') return 'number';
    return field.kind === 'date' ? 'date' : 'text';
  }

  setQueryField(node: ExperienceNode, field: RuntimeField, event: Event): void {
    if (this.readOnly()) return;
    const target = event.target as HTMLInputElement | HTMLSelectElement;
    const raw: unknown = field.kind === 'boolean' && target instanceof HTMLInputElement
      ? target.checked
      : target.value;
    const converted = valuesToPayload([field], { [field.name]: raw });
    const current = this.dataBinding(node)?.input ?? {};
    const input = { ...current };
    if (Object.prototype.hasOwnProperty.call(converted, field.name)) input[field.name] = converted[field.name];
    else delete input[field.name];
    const query = this.record(node.props?.['queryBinding']) ?? {};
    this.setProp(node, 'queryBinding', { ...query, source: 'system-binding', input });
    this.dataError.set(null);
  }

  dataSelectorOptions(node: ExperienceNode): Array<{ value: string; label: string }> {
    const key = this.dataContractKey(node);
    const schema = key ? this.dataContracts()[key]?.output_schema : null;
    const options = schemaSelectorOptions(schema, node.type);
    const current = this.dataBinding(node)?.selector ?? '';
    if (current && !options.some((option) => option.value === current)) {
      options.push({ value: current, label: humanizeIdentifier(current) || current });
    }
    return options.length > 0 ? options : [{ value: '', label: '' }];
  }

  queryInput(node: ExperienceNode): string {
    return JSON.stringify(this.dataBinding(node)?.input ?? {}, null, 2);
  }

  setQueryInput(node: ExperienceNode, value: string): void {
    if (this.readOnly()) return;
    try {
      const parsed: unknown = JSON.parse(value || '{}');
      if (!this.record(parsed)) throw new Error('object');
      const current = this.record(node.props?.['queryBinding']) ?? {};
      this.setProp(node, 'queryBinding', { ...current, source: 'system-binding', input: parsed });
      this.dataError.set(null);
    } catch {
      this.dataError.set(this.i18n.t('experience.editor.data.json_error'));
    }
  }

  private queryIngress(node: ExperienceNode) {
    const key = this.dataBinding(node)?.bindingKey;
    if (!key) return null;
    const binding = this.bindings().find((row) => row.binding_key === key);
    const contract = this.dataContracts()[key];
    return binding && contract
      ? contract.ingresses.find((row) => row.ingress_id === binding.ingress_id) ?? null
      : null;
  }

  private nodeBindingKey(node: ExperienceNode): string {
    const direct = this.str(node, 'bindingKey');
    if (direct) return direct;
    const query = this.record(node.props?.['queryBinding']);
    return typeof query?.['bindingKey'] === 'string' ? query['bindingKey'] : '';
  }

  private dataContractKey(node: ExperienceNode): string {
    const binding = this.dataBinding(node);
    if (!binding) return '';
    if (binding.source === 'system-binding') return binding.bindingKey ?? '';
    const sourceNode = this.selectedPage()?.components.find((item) => item.id === binding.componentId);
    return sourceNode ? this.nodeBindingKey(sourceNode) : '';
  }

  private ensureNodeDataContract(node: ExperienceNode): void {
    const key = this.dataContractKey(node);
    if (key) this.loadDataContract(key);
  }

  private loadDataContract(key: string, force = false): void {
    const state = this.dataContractStates()[key];
    if (!force && (state === 'loading' || state === 'ready')) return;
    const binding = this.bindings().find((row) => row.binding_key === key);
    if (!binding) {
      this.dataContractStates.update((states) => ({ ...states, [key]: 'error' }));
      return;
    }
    this.dataContractStates.update((states) => ({ ...states, [key]: 'loading' }));
    const request = this.api.listIngresses(binding.system_id).subscribe({
      next: (contract) => {
        if (contract.published_flow_version_id !== binding.published_flow_version_id) {
          this.dataContractStates.update((states) => ({ ...states, [key]: 'error' }));
          return;
        }
        this.dataContracts.update((contracts) => ({ ...contracts, [key]: contract }));
        this.dataContractStates.update((states) => ({ ...states, [key]: 'ready' }));
      },
      error: () => this.dataContractStates.update((states) => ({ ...states, [key]: 'error' })),
    });
    this.trackRoute(request);
  }

  private setProps(node: ExperienceNode, props: Record<string, unknown>): void {
    const found = findNode(this.doc(), node.id ?? null);
    if (!found || !node.id) return;
    this.commit(applyPatch(this.doc(), { kind: 'update_node', pageId: found.pageId, nodeId: node.id, props }));
  }

  private record(value: unknown): Record<string, unknown> | null {
    return !!value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : null;
  }

  addComponent(event: Event): void {
    const type = this.selectValue(event) as CertifiedType;
    (event.target as HTMLSelectElement).value = '';
    this.addComponentType(type);
  }

  addComponentType(type: CertifiedType): void {
    if (this.readOnly()) return;
    if (!type) return;
    const pageId = this.pageId();
    if (!pageId) return;
    this.commit(
      applyPatch(this.doc(), {
        kind: 'add_component',
        pageId,
        node: { type, id: newNodeId(type), props: {} },
      }),
    );
  }

  removeSelected(): void {
    if (this.readOnly()) return;
    const sel = this.selection();
    if (sel?.kind !== 'node') return;
    this.commit(applyPatch(this.doc(), { kind: 'remove_component', pageId: sel.pageId, nodeId: sel.nodeId }));
    this.selection.set({ kind: 'page', pageId: sel.pageId });
  }

  canMove(delta: number): boolean {
    const { index, total } = nodeIndex(this.doc(), this.selectedNode()?.id ?? null);
    if (index < 0) return false;
    const to = index + delta;
    return to >= 0 && to < total;
  }

  moveSelected(delta: number): void {
    if (this.readOnly()) return;
    const sel = this.selection();
    if (sel?.kind !== 'node') return;
    this.commit(
      applyPatch(this.doc(), { kind: 'move_component', pageId: sel.pageId, nodeId: sel.nodeId, delta }),
    );
  }

  addPage(): void {
    if (this.readOnly()) return;
    const doc = this.doc();
    const title = this.i18n.t('experience.editor.page.new', { n: doc.pages.length + 1 });
    const pageId = newPageId(doc, title);
    this.commit(applyPatch(doc, { kind: 'add_page', pageId, title }));
    this.selection.set({ kind: 'page', pageId });
  }

  removePage(pageId: string): void {
    if (this.readOnly()) return;
    const doc = this.doc();
    if (doc.pages.length <= 1) return;
    const next = applyPatch(doc, { kind: 'remove_page', pageId });
    this.commit(next);
    const first = next.pages[0]?.id;
    this.selection.set(first ? { kind: 'page', pageId: first } : null);
  }

  renamePage(pageId: string, title: string): void {
    if (this.readOnly()) return;
    this.commit(applyPatch(this.doc(), { kind: 'rename_page', pageId, title }));
  }

  setProp(node: ExperienceNode, key: string, value: unknown): void {
    if (this.readOnly()) return;
    const found = findNode(this.doc(), node.id ?? null);
    if (!found || !node.id) return;
    this.commit(
      applyPatch(this.doc(), {
        kind: 'update_node',
        pageId: found.pageId,
        nodeId: node.id,
        props: { [key]: value },
      }),
    );
    if (key === 'bindingKey' && typeof value === 'string' && value && !this.bindingKeys().includes(value)) {
      this.bindingKeys.update((keys) => [...keys, value]);
    }
  }

  setPageProp(pageId: string, key: string, value: unknown): void {
    if (this.readOnly()) return;
    this.commit(applyPatch(this.doc(), { kind: 'update_page', pageId, props: { [key]: value } }));
  }

  pageStr(page: ExperiencePage, key: string): string {
    const value = page.props?.[key];
    return typeof value === 'string' ? value : '';
  }

  densityValue(props: Record<string, unknown> | undefined): string {
    return props?.['density'] === 'compact' ? 'compact' : 'comfortable';
  }

  themeValue(page: ExperiencePage): string {
    return themeOf(page.props);
  }

  accentValue(node: ExperienceNode): string {
    return appearanceOf(node).accent || '#7dd3fc';
  }

  spanValue(node: ExperienceNode): string {
    return appearanceOf(node).span;
  }

  paletteValue(node: ExperienceNode): string {
    return chartPalette(node.props?.['palette']);
  }

  localizedA11y(node: ExperienceNode, key: 'ariaLabel' | 'emptyText' | 'keyboardHint'): string {
    return this.localizedValue(a11yValue(node, key));
  }

  headingValue(node: ExperienceNode): string {
    return String(a11yOf(node).headingLevel ?? 3);
  }

  headingNumber(value: string): number {
    const n = Number(value);
    return n === 2 || n === 4 ? n : 3;
  }

  setA11y(node: ExperienceNode, key: keyof NodeA11y, value: unknown): void {
    this.setProp(node, 'a11y', a11yPayload(node, key, value));
  }

  setLocalizedA11y(
    node: ExperienceNode,
    keyName: 'ariaLabel' | 'emptyText' | 'keyboardHint',
    value: string,
  ): void {
    if (this.readOnly() || !node.id) return;
    const next = cloneDocument(this.doc());
    const target = findNode(next, node.id)?.node;
    if (!target) return;
    const current = a11yValue(target, keyName);
    const key = this.isLocalized(current) ? current.$i18n : `component.${node.id}.a11y.${keyName}`;
    const fallback = typeof current === 'string' ? current : this.isLocalized(current) ? current.fallback : '';
    target.props = {
      ...(target.props ?? {}),
      a11y: a11yPayload(target, keyName, { $i18n: key, fallback }),
    };
    this.setDictionaryValue(next, key, value);
    this.commit(next);
  }

  contrastWarn(node: ExperienceNode): boolean {
    const accent = appearanceOf(node).accent;
    if (!accent || !supportsAccent(node.type)) return false;
    const page = this.selectedPage();
    return accentContrastWarning(accent, page ? pageAppearance(page).theme : 'inherit');
  }

  patchBinding(key: string, body: Partial<{ confirmation_policy: string; on_unavailable: string }>): void {
    if (this.readOnly() || !this.confirmBindingChange(key)) return;
    const request = this.api.patchBinding(key, body).subscribe({
      next: (row) => {
        this.bindings.update((list) => list.map((item) => (item.binding_key === row.binding_key ? row : item)));
      },
      error: (err) => this.error.set(studioError(this.i18n, err, 'experience.editor.save_error')),
    });
    this.trackRoute(request);
  }

  undo(): void {
    if (this.readOnly()) return;
    this.stack.update(undoRevision);
    this.editGeneration += 1;
    this.saved.set(false);
    this.ready.set(null);
    this.readyState.set('idle');
    this.scheduleSave();
  }

  redo(): void {
    if (this.readOnly()) return;
    this.stack.update(redoRevision);
    this.editGeneration += 1;
    this.saved.set(false);
    this.ready.set(null);
    this.readyState.set('idle');
    this.scheduleSave();
  }

  propose(): void {
    const pageId = this.pageId() ?? 'home';
    const sel = this.selection();
    const item = proposeAssistantPatch(
      this.prompt(),
      this.doc(),
      pageId,
      {
        empty: this.i18n.t('state.empty.description'),
        approvalTitle: this.i18n.t('experience.runtime.approval.title'),
        approvalBody: this.i18n.t('experience.home.approval.body'),
      },
      sel?.kind === 'node' ? sel.nodeId : null,
    );
    this.proposal.set(item);
    this.assistantMiss.set(!item);
  }

  applyProposal(): void {
    if (this.readOnly()) return;
    const item = this.proposal();
    if (!item || !acceptAssistantPatch(item.patch)) {
      this.proposal.set(null);
      this.assistantMiss.set(true);
      return;
    }
    this.stack.update((stack) => applyPatchOnStack(stack, item.patch));
    this.editGeneration += 1;
    this.saved.set(false);
    this.ready.set(null);
    this.readyState.set('idle');
    this.proposal.set(null);
    this.scheduleSave();
  }

  proposalSummary(item: AssistantProposal): string {
    const page = item.after.pages.find((row) => row.id === (item.patch as { pageId: string }).pageId);
    if (item.summary === 'set_empty_state') {
      return this.i18n.t('experience.assistant.diff.add_empty', { page: page ? textFallback(page.title) : '' });
    }
    if (item.summary === 'rename_page' && item.patch.kind === 'rename_page') {
      return this.i18n.t('experience.assistant.diff.rename', { title: item.patch.title });
    }
    if (item.summary === 'set_density') {
      return this.i18n.t('experience.assistant.diff.density', { page: page ? textFallback(page.title) : '' });
    }
    if (item.summary === 'update_props' || item.summary === 'json_patch') {
      return this.i18n.t('experience.assistant.diff.update', { page: page ? textFallback(page.title) : '' });
    }
    return this.i18n.t('experience.assistant.diff.approval', { page: page ? textFallback(page.title) : '' });
  }

  flushSave(): void {
    if (this.readOnly()) return;
    this.requestSave();
  }

  protected publishTrigger: HTMLElement | null = null;

  preparePublish(event?: Event): void {
    this.publishTrigger = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null;
    if (!this.canRelease()) return;
    this.deploymentRelease.set(null);
    if (this.readOnly()) {
      const draft = this.detail()?.draft;
      if (draft) {
        this.lockedDraft.set(draft);
        this.publishOpen.set(true);
      }
      return;
    }
    this.publishRequested = true;
    this.lockedDraft.set(null);
    this.requestSave();
  }

  closePublish(): void {
    this.publishOpen.set(false);
    this.deploymentRelease.set(null);
    this.lockedDraft.set(null);
  }

  openDeployment(release: StudioRelease, event?: Event): void {
    this.publishTrigger = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null;
    if (!this.canRelease()) return;
    const draft = this.detail()?.draft;
    if (!draft) return;
    this.deploymentRelease.set(release);
    this.lockedDraft.set(draft);
    this.publishOpen.set(true);
  }

  private requestSave(): void {
    const id = this.id();
    if (!id) return;
    const current = this.detail()?.draft;
    if (!current) {
      this.error.set(this.i18n.t('experience.editor.save_error'));
      this.publishRequested = false;
      return;
    }
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
      this.saveTimer = null;
    }
    if (this.saving()) {
      this.saveQueued = true;
      return;
    }
    const generation = this.editGeneration;
    const bindingKeys = documentBindingKeys(this.doc());
    this.bindingKeys.set(bindingKeys);
    this.saving.set(true);
    this.saved.set(false);
    this.error.set(null);
    const request = this.api.saveDraft(id, pagesPayload(this.doc()), bindingKeys, current.revision).subscribe({
      next: (draft) => {
        if (this.id() !== id) return;
        this.detail.update((row) => row ? { ...row, draft, binding_keys: draft.binding_keys } : row);
        this.saving.set(false);
        const changedWhileSaving = generation !== this.editGeneration;
        if (changedWhileSaving || this.saveQueued) {
          this.saveQueued = false;
          this.requestSave();
          return;
        }
        this.refreshReady(id);
        this.saved.set(true);
        if (this.publishRequested) {
          this.publishRequested = false;
          this.lockedDraft.set(draft);
          this.publishOpen.set(true);
        }
      },
      error: (err) => {
        if (this.id() !== id) return;
        this.error.set(
          apiCode(err) === 'EXPERIENCE_DRAFT_REVISION_CONFLICT'
            ? this.i18n.t('experience.editor.conflict')
            : studioError(this.i18n, err, 'experience.editor.save_error'),
        );
        this.publishRequested = false;
        this.saveQueued = false;
        this.saving.set(false);
      },
    });
    this.trackRoute(request);
  }

  toggleBottom(tab: BottomTab): void {
    if (this.bottomTab() === tab) this.bottomOpen.update((open) => !open);
    else {
      this.bottomTab.set(tab);
      this.bottomOpen.set(true);
    }
  }

  openTests(): void {
    this.bottomTab.set('tests');
    this.bottomOpen.set(true);
  }

  historyDate(value: string | null | undefined): string {
    if (!value) return '—';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '—';
    return new Intl.DateTimeFormat(this.i18n.locale() === 'en' ? 'en-GB' : 'fr-FR', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  }

  shortHash(value: string): string {
    const hash = value.trim();
    return hash ? hash.slice(0, 12) : '—';
  }

  canRestoreRevision(revision: StudioDraftRevision): boolean {
    const current = this.detail()?.draft;
    return !this.readOnly()
      && !this.draftHistoryBusy()
      && !this.saving()
      && this.saved()
      && !this.metadataDirty()
      && !this.metadataBusy()
      && !!current
      && revision.revision !== current.revision;
  }

  restoreDisabledHint(revision: StudioDraftRevision): string | null {
    if (this.canRestoreRevision(revision)) return null;
    if (this.draftHistoryBusy()) return this.i18n.t('experience.editor.history.restoring');
    return this.i18n.t('experience.editor.history.save_first');
  }

  requestDraftRestore(revision: StudioDraftRevision): void {
    if (!this.canRestoreRevision(revision)) return;
    this.draftHistoryStatus.set('');
    this.restoreCandidate.set(revision);
  }

  cancelDraftRestore(): void {
    this.restoreCandidate.set(null);
  }

  restoreDraftRevision(): void {
    const id = this.id();
    const target = this.restoreCandidate();
    const current = this.detail()?.draft;
    if (!id || !target || !current || !this.canRestoreRevision(target)) {
      this.restoreCandidate.set(null);
      return;
    }
    const previousPageId = this.pageId();
    const expectedRevision = current.revision;
    this.restoreCandidate.set(null);
    this.draftHistoryBusy.set(true);
    this.error.set(null);
    this.draftHistoryStatus.set(
      this.i18n.t('experience.editor.history.restoring_revision', { n: target.revision }),
    );
    const request = this.api.restoreDraftRevision(id, target.revision, expectedRevision).subscribe({
      next: (draft) => {
        if (this.id() !== id) return;
        const document = hydrateDocument(draft.pages);
        this.detail.update((row) => row
          ? { ...row, draft, binding_keys: draft.binding_keys }
          : row);
        this.bindingKeys.set(draft.binding_keys ?? []);
        this.stack.set(emptyStack(document));
        const pageId = document.pages.some((page) => page.id === previousPageId)
          ? previousPageId
          : document.pages[0]?.id ?? null;
        this.selection.set(pageId ? { kind: 'page', pageId } : null);
        this.editGeneration += 1;
        this.saveQueued = false;
        this.saved.set(true);
        this.ready.set(null);
        this.readyState.set('idle');
        this.draftHistoryBusy.set(false);
        this.draftHistoryStatus.set(this.i18n.t('experience.editor.history.restored', {
          target: target.revision,
          current: draft.revision,
        }));
        this.refreshReady(id);
        this.loadDraftHistory(id);
        this.focusDraftHistory();
      },
      error: (err) => {
        if (this.id() !== id) return;
        const conflict = apiCode(err) === 'EXPERIENCE_DRAFT_REVISION_CONFLICT';
        const message = this.i18n.t(conflict
          ? 'experience.editor.history.conflict'
          : 'experience.editor.history.restore_error');
        this.draftHistoryBusy.set(false);
        this.error.set(message);
        this.draftHistoryStatus.set(message);
        if (conflict) this.load(id);
        else this.loadDraftHistory(id);
        this.focusDraftHistory();
      },
    });
    this.trackRoute(request);
  }

  retryDraftHistory(): void {
    const id = this.id();
    if (id) this.loadDraftHistory(id);
  }

  rollback(deployment: StudioDeployment): void {
    if (!this.canRelease()) return;
    const id = this.id();
    const channel = deployment.channel;
    const targetReleaseId = deployment.previous_release_id;
    const expectedDeploymentUpdatedAt = deployment.updated_at;
    if (!id || (channel !== 'pilot' && channel !== 'live')) return;
    if (!targetReleaseId || !expectedDeploymentUpdatedAt) return;
    this.lifecycleBusy.set(true);
    const request = this.api.rollback(id, channel, {
      releaseId: targetReleaseId,
      expectedCurrentReleaseId: deployment.release_id,
      expectedDeploymentUpdatedAt,
    }).subscribe({
      next: () => {
        if (this.id() !== id) return;
        this.lifecycleBusy.set(false);
        this.reloadDeployments();
      },
      error: (err) => {
        if (this.id() !== id) return;
        this.lifecycleBusy.set(false);
        const conflict = apiCode(err) === 'EXPERIENCE_DEPLOYMENT_CONFLICT';
        this.error.set(conflict
          ? this.i18n.t('experience.deployment.conflict')
          : studioError(this.i18n, err, 'experience.editor.lifecycle.error'));
        if (conflict) this.reloadDeployments();
      },
    });
    this.trackRoute(request);
  }

  repairDrift(drift: StudioDrift): void {
    if (this.readOnly()) return;
    if (!this.confirmBindingChange(drift.binding.binding_key)) return;
    const version = this.publishedVersions()[drift.binding.system_id];
    if (!version) {
      this.error.set(this.i18n.t('experience.editor.lifecycle.no_version'));
      return;
    }
    this.lifecycleBusy.set(true);
    const request = this.api.patchBinding(drift.binding.binding_key, {
      published_flow_version_id: version,
      ingress_id: drift.binding.ingress_id,
    }).subscribe({
      next: (row) => {
        this.bindings.update((items) => items.map((item) => item.binding_key === row.binding_key ? row : item));
        this.lifecycleBusy.set(false);
        this.loadDrifts();
        const id = this.id();
        if (id) this.refreshReady(id);
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.error.set(studioError(this.i18n, err, 'experience.editor.lifecycle.error'));
      },
    });
    this.trackRoute(request);
  }

  /**
   * Keeps the "ready to publish" badge honest between two saves. Debounced
   * well past the save debounce: the check walks the whole document, and a
   * burst of keystrokes must not turn into a burst of checks.
   */
  private refreshReady(id: string): void {
    const generation = ++this.readyGeneration;
    this.readyState.set('loading');
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = setTimeout(() => {
      this.readyTimer = null;
      if (generation !== this.readyGeneration || this.id() !== id || !this.saved() || this.saving() || this.saveQueued) return;
      const request = this.api.readyCheck(id).subscribe({
        next: (check) => {
          if (
            generation === this.readyGeneration
            && this.id() === id
            && this.saved()
            && !this.saving()
            && !this.saveQueued
          ) {
            this.ready.set(check);
            this.readyState.set('ready');
          }
        },
        error: () => {
          if (generation === this.readyGeneration && this.id() === id) {
            this.ready.set(null);
            this.readyState.set('error');
          }
        },
      });
      this.trackRoute(request);
    }, READY_DEBOUNCE_MS);
  }

  reload(): void {
    const id = this.id();
    if (id) this.load(id);
  }

  retryReady(): void {
    const id = this.id();
    if (id && this.saved() && !this.saving()) this.refreshReady(id);
  }

  reloadLifecycle(): void {
    const id = this.id();
    if (id) this.loadLifecycle(id);
  }

  reloadDeployments(): void {
    const id = this.id();
    if (!id) return;
    const request = this.api.getExperience(id).subscribe({
      next: (row) => {
        if (this.id() !== id) return;
        this.detail.update((current) => current ? { ...current, deployments: row.deployments } : current);
      },
      error: () => undefined,
    });
    this.trackRoute(request);
  }

  metadataValid(): boolean {
    return this.metadataLanguages().length > 0
      && (this.accessWhole() || this.accessRoles().length > 0 || this.accessGroups().length > 0);
  }

  toggleMetadataLanguage(locale: string): void {
    if (this.readOnly()) return;
    const current = this.metadataLanguages();
    this.metadataLanguages.set(
      current.includes(locale) ? current.filter((item) => item !== locale) : [...current, locale],
    );
    this.metadataDirty.set(true);
  }

  toggleMetadataRole(role: string): void {
    if (this.readOnly()) return;
    this.accessWhole.set(false);
    const current = this.accessRoles();
    this.accessRoles.set(
      current.includes(role) ? current.filter((item) => item !== role) : [...current, role],
    );
    this.metadataDirty.set(true);
  }

  toggleMetadataWhole(): void {
    if (this.readOnly()) return;
    const next = !this.accessWhole();
    this.accessWhole.set(next);
    if (next) {
      this.accessRoles.set([]);
      this.accessGroups.set([]);
    }
    this.metadataDirty.set(true);
  }

  setMetadataGroups(event: Event): void {
    if (this.readOnly()) return;
    const groups = this.inputValue(event)
      .split(',')
      .map((item) => item.trim())
      .filter((item, index, all) => !!item && all.indexOf(item) === index);
    this.accessGroups.set(groups);
    if (groups.length > 0) this.accessWhole.set(false);
    this.metadataDirty.set(true);
  }

  private readonly hostElement: ElementRef<HTMLElement> = inject(ElementRef);

  openVisualIdentity(): void {
    this.bottomTab.set('access');
    this.bottomOpen.set(true);
    requestAnimationFrame(() => {
      const control = this.hostElement.nativeElement.querySelector<HTMLElement>('app-brand-appearance-editor select');
      control?.scrollIntoView({ block: 'center' });
      control?.focus({ preventScroll: true });
    });
  }

  setMetadataAppearance(value: BrandAppearance): void {
    if (this.readOnly() || this.detail()?.theme?.['live_href']) return;
    this.metadataAppearance.set(value);
    this.appearanceEdited = true;
    this.metadataDirty.set(true);
  }

  setMetadataTheme(event: Event): void {
    if (this.readOnly()) return;
    this.metadataTheme.set(this.selectValue(event));
    this.metadataDirty.set(true);
  }

  setMetadataDescription(event: Event): void {
    if (this.readOnly()) return;
    this.metadataDescription.set(this.inputValue(event));
    this.metadataDirty.set(true);
  }

  setMetadataEmblem(event: Event): void {
    if (this.readOnly()) return;
    this.metadataEmblem.set(this.selectValue(event));
    this.metadataDirty.set(true);
  }

  knownEmblem(value: string): boolean {
    return this.emblemOptions.some((option) => option.value === value);
  }

  saveMetadata(): void {
    const row = this.detail();
    if (this.readOnly() || this.metadataBusy() || !this.metadataValid() || !row?.updated_at) return;
    this.metadataBusy.set(true);
    this.error.set(null);
    const request = this.api.patchExperience(row.id, {
      languages: this.metadataLanguages(),
      description: this.metadataDescription().trim() || null,
      emblem: this.metadataEmblem().trim() || null,
      theme: { ...(row.theme ?? {}), mode: this.metadataTheme(), ...(this.appearanceEdited ? { appearance: this.metadataAppearance() } : {}) },
      access_policy: {
        roles: this.accessWhole() ? [] : this.accessRoles(),
        groups: this.accessWhole() ? [] : this.accessGroups(),
      },
      expected_updated_at: row.updated_at,
    }).subscribe({
      next: (updated) => {
        // Metadata and draft saves are independent HTTP requests. Preserve the
        // newest locally-observed draft if their responses arrive out of order.
        this.detail.update((current) => current?.id === updated.id
          ? { ...updated, draft: current.draft, binding_keys: current.binding_keys }
          : updated);
        this.hydrateMetadata(updated);
        this.metadataBusy.set(false);
      },
      error: (err) => {
        this.metadataBusy.set(false);
        this.error.set(
          apiCode(err) === 'EXPERIENCE_METADATA_CONFLICT'
            ? this.i18n.t('experience.editor.conflict')
            : studioError(this.i18n, err, 'experience.editor.save_error'),
        );
      },
    });
    this.trackRoute(request);
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement).value;
  }

  selectValue(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  private openRoute(id: string | null): void {
    if (id === this.id()) return;
    this.cancelRouteWork();
    this.routeScope = new Subscription();
    this.id.set(id);
    this.detail.set(null);
    this.name.set('');
    this.slug.set('');
    this.stack.set(emptyStack({ pages: [] }));
    this.selection.set(null);
    this.bindingKeys.set([]);
    this.ready.set(null);
    this.readyState.set('idle');
    this.lockedDraft.set(null);
    this.releases.set([]);
    this.draftHistory.set([]);
    this.draftHistoryState.set('idle');
    this.draftHistoryBusy.set(false);
    this.draftHistoryStatus.set('');
    this.restoreCandidate.set(null);
    this.drifts.set([]);
    this.publishedVersions.set({});
    this.error.set(null);
    this.dataError.set(null);
    this.accessRoles.set([]);
    this.accessGroups.set([]);
    this.accessWhole.set(false);
    this.metadataLanguages.set([]);
    this.metadataTheme.set('default');
    this.metadataAppearance.set({});
    this.appearanceEdited = false;
    this.metadataDescription.set('');
    this.metadataEmblem.set('◇');
    this.metadataBusy.set(false);
    this.metadataDirty.set(false);
    this.publishOpen.set(false);
    this.deploymentRelease.set(null);
    this.proposal.set(null);
    this.assistantMiss.set(false);
    this.contentLocale.set('fr');
    this.previewRole.set('workspace_viewer');
    this.previewGroup.set('');
    this.editGeneration = 0;
    this.saved.set(false);
    if (id) this.load(id);
  }

  private cancelRouteWork(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.saveTimer = null;
    this.readyTimer = null;
    this.routeScope.unsubscribe();
    this.actionBindingRequests.clear();
    this.loadGeneration += 1;
    this.readyGeneration += 1;
    this.saveQueued = false;
    this.publishRequested = false;
    this.saving.set(false);
    this.lifecycleBusy.set(false);
    this.draftHistoryBusy.set(false);
    this.restoreCandidate.set(null);
  }

  private trackRoute(subscription: Subscription): void {
    this.routeScope.add(subscription);
  }

  private load(id: string): void {
    const generation = ++this.loadGeneration;
    const request = this.api.getExperience(id).subscribe({
      next: (row) => {
        if (generation === this.loadGeneration && this.id() === id) this.hydrate(row);
      },
      error: (err) => {
        if (generation === this.loadGeneration && this.id() === id) {
          this.error.set(studioError(this.i18n, err, 'experience.editor.load_error'));
        }
      },
    });
    this.trackRoute(request);
  }

  private hydrate(row: StudioDetail): void {
    this.detail.set(row);
    this.hydrateMetadata(row);
    this.name.set(row.name);
    this.slug.set(row.slug);
    this.bindingKeys.set(row.draft?.binding_keys ?? row.binding_keys ?? []);
    const doc = this.api.draftDocument(row);
    this.stack.set(emptyStack(doc));
    this.saved.set(true);
    const requested = this.requestedPageId();
    const first = doc.pages.find((page) => page.id === requested)?.id ?? doc.pages[0]?.id;
    this.selection.set(first ? { kind: 'page', pageId: first } : null);
    const locale = row.languages?.map((item) => item.toLowerCase().slice(0, 2)).find((item) => item === 'fr' || item === 'en');
    if (locale) this.contentLocale.set(locale);
    this.refreshReady(row.id);
    this.loadLifecycle(row.id);
  }

  private selectRequestedPage(): void {
    const requested = this.requestedPageId();
    if (requested && this.doc().pages.some((page) => page.id === requested)) {
      this.selection.set({ kind: 'page', pageId: requested });
    }
  }

  private hydrateMetadata(row: StudioDetail): void {
    const policy = row.access_policy ?? {};
    const roles = Array.isArray(policy['roles'])
      ? policy['roles'].filter((item): item is string => typeof item === 'string')
      : [];
    const groups = Array.isArray(policy['groups'])
      ? policy['groups'].filter((item): item is string => typeof item === 'string')
      : [];
    this.accessRoles.set(roles);
    this.accessGroups.set(groups);
    this.accessWhole.set(Array.isArray(policy['roles']) && roles.length === 0 && groups.length === 0);
    this.metadataLanguages.set(
      [...new Set((row.languages ?? []).map((item) => item.toLowerCase()).filter((item) => item === 'fr' || item === 'en'))],
    );
    this.metadataAppearance.set(brandAppearance(row.theme?.['appearance']));
    this.appearanceEdited = false;
    const mode = row.theme?.['mode'];
    this.metadataTheme.set(mode === 'light' || mode === 'dark' ? mode : 'default');
    this.metadataDescription.set(row.description ?? '');
    this.metadataEmblem.set(row.emblem ?? '◇');
    this.metadataDirty.set(false);
  }

  private commit(next: ExperienceDocument): void {
    if (this.readOnly()) return;
    this.stack.update((stack) => pushRevision(stack, next));
    this.editGeneration += 1;
    this.saved.set(false);
    this.ready.set(null);
    this.readyState.set('idle');
    this.scheduleSave();
  }

  private scheduleSave(): void {
    this.readyGeneration += 1;
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      this.flushSave();
    }, 400);
  }

  private confirmBindingChange(key: string): boolean {
    if (this.appsState() !== 'ready') {
      this.error.set(this.i18n.t('experience.editor.catalog.error'));
      return false;
    }
    const others = this.sharedWith(key);
    return others.length === 0 || globalThis.confirm(
      this.i18n.t('experience.editor.action.shared_confirm', { apps: others.join(', ') }),
    );
  }

  loadCatalogs(): void {
    this.bindingsState.set('loading');
    this.appsState.set('loading');
    this.api.listBindings().subscribe({
      next: (rows) => {
        this.bindings.set(rows);
        this.bindingsState.set('ready');
        const node = this.selectedNode();
        if (node) this.ensureNodeDataContract(node);
      },
      error: () => this.bindingsState.set('error'),
    });
    this.api.listExperiences().subscribe({
      next: (rows) => {
        this.apps.set(rows);
        this.appsState.set('ready');
      },
      error: () => this.appsState.set('error'),
    });
  }

  private loadLifecycle(id: string): void {
    this.loadDraftHistory(id);
    this.trackRoute(this.api.listReleases(id).subscribe({
      next: (rows) => {
        if (this.id() === id) this.releases.set(rows);
      },
      error: () => {
        if (this.id() === id) this.releases.set([]);
      },
    }));
    this.loadDrifts();
    this.trackRoute(this.api.publishedSystems().subscribe({
      next: (rows) => {
        if (this.id() !== id) return;
        const versions: Record<string, string> = {};
        for (const row of rows) {
          const version = row.published_flow_version_id;
          if (version) versions[row.id] = version;
        }
        this.publishedVersions.set(versions);
      },
      error: () => {
        if (this.id() === id) this.publishedVersions.set({});
      },
    }));
  }

  private loadDrifts(): void {
    this.trackRoute(this.api.listDriftedBindings().subscribe({
      next: (rows) => this.drifts.set(rows),
      error: () => this.drifts.set([]),
    }));
  }

  private loadDraftHistory(id: string): void {
    this.draftHistoryState.set('loading');
    this.trackRoute(this.api.listDraftRevisions(id).subscribe({
      next: (rows) => {
        if (this.id() !== id) return;
        this.draftHistory.set([...rows].sort((a, b) => b.revision - a.revision));
        this.draftHistoryState.set('ready');
      },
      error: () => {
        if (this.id() === id) this.draftHistoryState.set('error');
      },
    }));
  }

  private focusDraftHistory(): void {
    queueMicrotask(() => {
      if (typeof document !== 'undefined') {
        document.getElementById('xp-draft-history-title')?.focus();
      }
    });
  }
}
