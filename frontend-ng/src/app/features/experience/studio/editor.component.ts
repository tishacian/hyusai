import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { HelpTooltipComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { canEditExperienceStudio, canReleaseExperienceStudio } from '../experience-access';
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { acceptAssistantPatch, proposeAssistantPatch, type AssistantProposal } from './studio-assistant';
import {
  apiCode,
  apiMessage,
  StudioApiService,
  type StudioBinding,
  type StudioDetail,
  type StudioDraft,
  type StudioDrift,
  type StudioRelease,
} from './studio-api.service';
import {
  applyPatch,
  applyPatchOnStack,
  emptyStack,
  findNode,
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
  CONFIRMATION_POLICIES,
  UNAVAILABLE_POLICIES,
  bindingSharedWith,
  experienceAudience,
  inventoryState,
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
} from '../runtime/model';
import {
  fieldsFromSchema,
  localizeDocument,
  runtimeDataBinding,
  textFallback,
} from '../runtime/model';
import {
  a11yOf,
  a11yPayload,
  accentContrastWarning,
  appearanceOf,
  needsEmptyText,
  pageAppearance,
  supportsAccent,
  supportsDescription,
  supportsHeading,
  supportsTitle,
  themeOf,
  type NodeA11y,
} from '../runtime/style';

const READY_DEBOUNCE_MS = 1500;

type Tab = 'content' | 'action' | 'appearance' | 'a11y';
type LeftTab = 'pages' | 'components';
type Viewport = 'desktop' | 'tablet' | 'mobile';
type BottomTab = 'data' | 'actions' | 'tests' | 'journal';
type Selection = { kind: 'page'; pageId: string } | { kind: 'node'; pageId: string; nodeId: string };

@Component({
  selector: 'app-experience-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    HelpTooltipComponent,
    ExperienceRuntimeHostComponent,
    ExperiencePublishDialogComponent,
  ],
  styleUrl: './studio.scss',
  template: `
    <div class="xp-ed" [class.is-readonly]="readOnly()">
      <header class="xp-ed-chrome">
        <div class="xp-ed-id">
          <a routerLink="/create/apps" class="xp-btn">{{ i18n.t('experience.editor.back') }}</a>
          <strong>{{ name() }}</strong>
          <span class="xp-tag">{{ stateLabel() }}</span>
          @if (readOnly()) { <span class="xp-tag">{{ i18n.t('experience.editor.review_mode') }}</span> }
          @if (readyLabel(); as label) {
            <span class="xp-tag" [class.xp-tag-ok]="readyTone() === 'ok'" [class.xp-tag-warn]="readyTone() === 'warn'">
              {{ label }}
            </span>
          }
        </div>
        <div class="xp-ed-tools">
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
            <button type="button" class="xp-btn" [disabled]="saving()" (click)="flushSave()">
              {{ saving() ? i18n.t('experience.editor.saving') : i18n.t('experience.editor.save') }}
            </button>
          </div>
          }
          @if (viewSlug(); as slug) {
            <div class="xp-ed-group">
              <a class="xp-btn" [routerLink]="['/work', slug]">{{ i18n.t('experience.editor.view') }}</a>
            </div>
          }
          <div class="xp-ed-group">
            @if (canRelease()) {
            <button type="button" class="xp-btn xp-btn-primary" [disabled]="saving()" (click)="preparePublish()">
              {{ i18n.t('experience.editor.publish') }}
            </button>
            <ck-help id="concept.release" />
            } @else {
              <span class="xp-hint">{{ i18n.t('experience.editor.review_required') }}</span>
            }
          </div>
        </div>
      </header>

      @if (error(); as err) {
        <p class="xp-error" role="alert">{{ err }}</p>
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
          <div class="xp-canvas-stage" [class]="'is-' + viewport()">
            <div class="xp-canvas-preview" inert>
              <app-experience-runtime-host [document]="previewDoc()" [pageId]="pageId()" />
            </div>
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

          <div class="xp-tabs" role="tablist">
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
                  <option value="">{{ i18n.t('experience.editor.action.none_option') }}</option>
                  @if (ownBindings().length > 0) {
                    <optgroup [label]="i18n.t('experience.editor.action.group.app')">
                      @for (row of ownBindings(); track row.binding_key) {
                        <option [value]="row.binding_key">{{ bindingLabel(row) }}</option>
                      }
                    </optgroup>
                  }
                  @if (otherBindings().length > 0) {
                    <optgroup [label]="i18n.t('experience.editor.action.group.other')">
                      @for (row of otherBindings(); track row.binding_key) {
                        <option [value]="row.binding_key">{{ bindingLabel(row) }}</option>
                      }
                    </optgroup>
                  }
                </select>
              </div>
              @if (bound(node); as row) {
                <p class="xp-meta">
                  <span>{{ i18n.t('experience.editor.action.calls') }} · {{ row.system_id }}</span>
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
                    <option value="run-output">{{ i18n.t('experience.editor.data.run') }}</option>
                    <option value="system-binding">{{ i18n.t('experience.editor.data.query') }}</option>
                  </select>
                </label>
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
                  <label class="xp-field">
                    <span>{{ i18n.t('experience.editor.data.input') }}</span>
                    <textarea [value]="queryInput(node)" (change)="setQueryInput(node, inputValue($event))"></textarea>
                  </label>
                  @if (dataError(); as dataErr) { <p class="xp-error" role="alert">{{ dataErr }}</p> }
                }
                @if (dataSource(node) !== 'none') {
                  <label class="xp-field">
                    <span>{{ i18n.t('experience.editor.data.selector') }}</span>
                    <input [value]="dataBinding(node)?.selector ?? ''" (input)="setDataField(node, 'selector', inputValue($event))" />
                  </label>
                  <p class="xp-hint">{{ i18n.t('experience.editor.data.explicit') }}</p>
                }
              </div>
            }
          }

          @if (inspectorTab() === 'appearance') {
            @if (selectedNode(); as node) {
              @if (supportsTitle(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.title') }}</span>
                  <input [value]="str(node, 'title')" (input)="setProp(node, 'title', inputValue($event))" />
                </label>
              }
              @if (supportsDescription(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.description') }}</span>
                  <textarea [value]="str(node, 'description')" (input)="setProp(node, 'description', inputValue($event))"></textarea>
                </label>
              }
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.density') }}</span>
                <select [value]="densityValue(node.props)" (change)="setProp(node, 'density', selectValue($event))">
                  <option value="comfortable">{{ i18n.t('experience.editor.density.comfortable') }}</option>
                  <option value="compact">{{ i18n.t('experience.editor.density.compact') }}</option>
                </select>
              </label>
              @if (supportsAccent(node.type)) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.accent') }}</span>
                  <input type="color" [value]="accentValue(node)" (input)="setProp(node, 'accent', inputValue($event))" />
                </label>
              }
            } @else if (selectedPage(); as page) {
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.title') }}</span>
                <input [value]="pageTitle(page)" (input)="renamePage(page.id, inputValue($event))" />
              </label>
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.description') }}</span>
                <textarea
                  [value]="pageStr(page, 'description')"
                  (input)="setPageProp(page.id, 'description', inputValue($event))"
                ></textarea>
              </label>
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
                <input [value]="a11yStr(node, 'ariaLabel')" (input)="setA11y(node, 'ariaLabel', inputValue($event))" />
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
                    [value]="a11yStr(node, 'emptyText')"
                    (input)="setA11y(node, 'emptyText', inputValue($event))"
                  ></textarea>
                </label>
                @if (!a11yStr(node, 'emptyText')) {
                  <p class="xp-error" role="status">{{ i18n.t('experience.editor.a11y.empty.required') }}</p>
                }
              }
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.a11y.keyboard') }}</span>
                <textarea
                  [value]="a11yStr(node, 'keyboardHint')"
                  (input)="setA11y(node, 'keyboardHint', inputValue($event))"
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

      <div class="xp-bottom" [class.is-open]="bottomOpen()">
        <div class="xp-bottom-bar">
          <div class="xp-bottom-tabs" role="tablist" [attr.aria-label]="i18n.t('experience.editor.bottom.label')">
            @for (tab of bottomTabs; track tab; let index = $index) {
              <button
                type="button"
                role="tab"
                [attr.aria-selected]="bottomTab() === tab && bottomOpen()"
                [tabIndex]="bottomTab() === tab ? 0 : -1"
                [class.is-on]="bottomTab() === tab && bottomOpen()"
                (click)="toggleBottom(tab)"
                (keydown)="onBottomTabKey($event, index)"
              >{{ i18n.t('experience.editor.bottom.' + tab) }}</button>
            }
          </div>
          <button type="button" class="xp-ready-link" (click)="openTests()">{{ readyLabel() || i18n.t('experience.publish.loading') }}</button>
        </div>
        @if (bottomOpen()) {
          <section class="xp-bottom-panel" role="tabpanel" [attr.aria-label]="i18n.t('experience.editor.bottom.' + bottomTab())">
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
              @case ('tests') {
                @if (ready(); as check) {
                  <div class="xp-bottom-list">
                    @for (item of check.blockers; track item.code ?? item.message) { <span class="xp-error">{{ item.message || item.code }}</span> }
                    @for (item of check.warnings; track item.code ?? item.message) { <span class="xp-warn">{{ item.message || item.code }}</span> }
                    @if (check.blockers.length === 0 && check.warnings.length === 0) { <span>{{ i18n.t('experience.editor.ready.ok') }}</span> }
                  </div>
                } @else { <p class="xp-hint">{{ i18n.t('experience.publish.loading') }}</p> }
              }
              @case ('journal') {
                <div class="xp-journal-grid">
                  <section>
                    <h3>{{ i18n.t('experience.editor.lifecycle.releases') }}</h3>
                    @for (release of releases(); track release.id) {
                      <div class="xp-journal-row"><span>R{{ release.release_number }} · {{ release.created_at || '—' }}</span></div>
                    } @empty { <p class="xp-hint">{{ i18n.t('experience.publish.recap.none') }}</p> }
                  </section>
                  <section>
                    <h3>{{ i18n.t('experience.editor.lifecycle.deployments') }}</h3>
                    @for (deployment of detail()?.deployments ?? []; track deployment.id ?? deployment.channel) {
                      <div class="xp-journal-row">
                        <span>{{ deployment.channel }} · {{ deployment.release_id }}</span>
                        @if (canRelease()) {
                          <button type="button" class="xp-btn" [disabled]="lifecycleBusy()" (click)="rollback(deployment.channel)">{{ i18n.t('experience.editor.lifecycle.rollback') }}</button>
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

    @if (id(); as experienceId) {
      @if (lockedDraft(); as draft) {
      <app-experience-publish-dialog
        [experienceId]="experienceId"
        [draft]="draft"
        [audience]="audience()"
        [summary]="summary()"
        [open]="publishOpen()"
        (closed)="closePublish()"
        (released)="reloadLifecycle()"
        (deployed)="reload()"
      />
      }
    }
  `,
})
export class ExperienceEditorComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StudioApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly workspace = inject(WorkspaceService);
  readonly addable = ADDABLE_TYPES;
  readonly confirms = CONFIRMATION_POLICIES;
  readonly unavailable = UNAVAILABLE_POLICIES;
  readonly tabs: Tab[] = ['content', 'action', 'appearance', 'a11y'];
  readonly leftTabs: LeftTab[] = ['pages', 'components'];
  readonly viewports: Viewport[] = ['desktop', 'tablet', 'mobile'];
  readonly bottomTabs: BottomTab[] = ['data', 'actions', 'tests', 'journal'];
  readonly supportsTitle = supportsTitle;
  readonly supportsDescription = supportsDescription;
  readonly supportsAccent = supportsAccent;
  readonly supportsHeading = supportsHeading;
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
  readonly bottomTab = signal<BottomTab>('data');
  readonly bottomOpen = signal(false);
  readonly contentLocale = signal('fr');
  readonly bindings = signal<StudioBinding[]>([]);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly publishOpen = signal(false);
  readonly prompt = signal('');
  readonly proposal = signal<AssistantProposal | null>(null);
  readonly assistantMiss = signal(false);
  readonly bindingKeys = signal<string[]>([]);
  readonly ready = signal<ReadyCheck | null>(null);
  readonly apps = signal<StudioExperience[]>([]);
  readonly lockedDraft = signal<StudioDraft | null>(null);
  readonly releases = signal<StudioRelease[]>([]);
  readonly drifts = signal<StudioDrift[]>([]);
  readonly publishedVersions = signal<Record<string, string>>({});
  readonly lifecycleBusy = signal(false);
  readonly dataError = signal<string | null>(null);
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private readyTimer: ReturnType<typeof setTimeout> | null = null;
  private editGeneration = 0;
  private saveQueued = false;
  private publishRequested = false;

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
  readonly audience = computed(() => ({ roles: experienceAudience(this.detail()) }));

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
    return check.warnings.length > 0 ? null : 'ok';
  });

  readonly readyLabel = computed(() => {
    const check = this.ready();
    if (!check) return '';
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
    this.route.paramMap.subscribe((params) => {
      const id = params.get('id');
      this.id.set(id);
      if (id) this.load(id);
    });
    this.api.listBindings().subscribe((rows) => this.bindings.set(rows));
    this.api.listExperiences().subscribe((rows) => this.apps.set(rows));
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
    return `${row.system_id} · ${row.ingress_id}`;
  }

  /** Other applications this binding serves — editing its rules changes theirs too. */
  sharedWith(key: string): string[] {
    return bindingSharedWith(this.apps(), key, this.id());
  }

  inputNames(node: ExperienceNode): string[] {
    return fieldsFromSchema(node.props?.['schema']).map((field) => field.label || field.name);
  }

  setActionBinding(node: ExperienceNode, key: string): void {
    if (this.readOnly()) return;
    const binding = this.bindings().find((row) => row.binding_key === key);
    if (!key || node.type !== 'form' || !binding) {
      this.setProp(node, 'bindingKey', key);
      return;
    }
    this.api.listIngresses(binding.system_id).subscribe({
      next: (body) => {
        const ingress = body?.ingresses.find((row) => row.ingress_id === binding.ingress_id);
        this.setProps(node, {
          bindingKey: key,
          ...(ingress?.input_schema ? { schema: ingress.input_schema } : {}),
        });
        if (!this.bindingKeys().includes(key)) this.bindingKeys.update((keys) => [...keys, key]);
      },
      error: () => this.setProp(node, 'bindingKey', key),
    });
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
    return this.selectedPage()?.components.filter((item) => item.id && item.id !== node.id) ?? [];
  }

  setDataSource(node: ExperienceNode, source: string): void {
    if (this.readOnly()) return;
    this.dataError.set(null);
    if (source === 'run-output') {
      this.setProps(node, {
        dataBinding: { source, componentId: '', selector: '' },
        queryBinding: undefined,
      });
    } else if (source === 'system-binding') {
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

  a11yStr(node: ExperienceNode, key: 'ariaLabel' | 'emptyText' | 'keyboardHint'): string {
    return a11yOf(node)[key];
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

  contrastWarn(node: ExperienceNode): boolean {
    const accent = appearanceOf(node).accent;
    if (!accent || !supportsAccent(node.type)) return false;
    const page = this.selectedPage();
    return accentContrastWarning(accent, page ? pageAppearance(page).theme : 'inherit');
  }

  patchBinding(key: string, body: Partial<{ confirmation_policy: string; on_unavailable: string }>): void {
    if (this.readOnly()) return;
    this.api.patchBinding(key, body).subscribe({
      next: (row) => {
        this.bindings.update((list) => list.map((item) => (item.binding_key === row.binding_key ? row : item)));
      },
      error: (err) => this.error.set(apiMessage(err, this.i18n.t('experience.editor.save_error'))),
    });
  }

  undo(): void {
    if (this.readOnly()) return;
    this.stack.update(undoRevision);
    this.editGeneration += 1;
    this.scheduleSave();
  }

  redo(): void {
    if (this.readOnly()) return;
    this.stack.update(redoRevision);
    this.editGeneration += 1;
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

  preparePublish(): void {
    if (!this.canRelease()) return;
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
    this.lockedDraft.set(null);
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
    this.saving.set(true);
    this.error.set(null);
    this.api.saveDraft(id, pagesPayload(this.doc()), this.bindingKeys(), current.revision).subscribe({
      next: (draft) => {
        this.detail.update((row) => row ? { ...row, draft, binding_keys: draft.binding_keys } : row);
        this.saving.set(false);
        this.refreshReady(id);
        const changedWhileSaving = generation !== this.editGeneration;
        if (changedWhileSaving || this.saveQueued) {
          this.saveQueued = false;
          this.requestSave();
          return;
        }
        if (this.publishRequested) {
          this.publishRequested = false;
          this.lockedDraft.set(draft);
          this.publishOpen.set(true);
        }
      },
      error: (err) => {
        this.error.set(
          apiCode(err) === 'EXPERIENCE_DRAFT_REVISION_CONFLICT'
            ? this.i18n.t('experience.editor.conflict')
            : apiMessage(err, this.i18n.t('experience.editor.save_error')),
        );
        this.publishRequested = false;
        this.saveQueued = false;
        this.saving.set(false);
      },
    });
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

  rollback(channel: string): void {
    if (!this.canRelease()) return;
    const id = this.id();
    if (!id || (channel !== 'pilot' && channel !== 'live')) return;
    this.lifecycleBusy.set(true);
    this.api.rollback(id, channel).subscribe({
      next: () => {
        this.lifecycleBusy.set(false);
        this.load(id);
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.error.set(apiMessage(err, this.i18n.t('experience.editor.lifecycle.error')));
      },
    });
  }

  repairDrift(drift: StudioDrift): void {
    if (this.readOnly()) return;
    const version = this.publishedVersions()[drift.binding.system_id];
    if (!version) {
      this.error.set(this.i18n.t('experience.editor.lifecycle.no_version'));
      return;
    }
    this.lifecycleBusy.set(true);
    this.api.patchBinding(drift.binding.binding_key, {
      published_flow_version_id: version,
      ingress_id: drift.binding.ingress_id,
    }).subscribe({
      next: (row) => {
        this.bindings.update((items) => items.map((item) => item.binding_key === row.binding_key ? row : item));
        this.lifecycleBusy.set(false);
        this.loadDrifts();
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.error.set(apiMessage(err, this.i18n.t('experience.editor.lifecycle.error')));
      },
    });
  }

  /**
   * Keeps the "ready to publish" badge honest between two saves. Debounced
   * well past the save debounce: the check walks the whole document, and a
   * burst of keystrokes must not turn into a burst of checks.
   */
  private refreshReady(id: string): void {
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = setTimeout(() => {
      this.api.readyCheck(id).subscribe({
        next: (check) => this.ready.set(check),
        error: () => this.ready.set(null),
      });
    }, READY_DEBOUNCE_MS);
  }

  reload(): void {
    const id = this.id();
    if (id) this.load(id);
  }

  reloadLifecycle(): void {
    const id = this.id();
    if (id) this.loadLifecycle(id);
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement).value;
  }

  selectValue(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  private load(id: string): void {
    this.api.getExperience(id).subscribe({
      next: (row) => this.hydrate(row),
      error: (err) => this.error.set(apiMessage(err, this.i18n.t('experience.editor.load_error'))),
    });
  }

  private hydrate(row: StudioDetail): void {
    this.detail.set(row);
    this.name.set(row.name);
    this.slug.set(row.slug);
    this.bindingKeys.set(row.draft?.binding_keys ?? row.binding_keys ?? []);
    const doc = this.api.draftDocument(row);
    this.stack.set(emptyStack(doc));
    const first = doc.pages[0]?.id;
    this.selection.set(first ? { kind: 'page', pageId: first } : null);
    const locale = row.languages?.map((item) => item.toLowerCase().slice(0, 2)).find((item) => item === 'fr' || item === 'en');
    if (locale) this.contentLocale.set(locale);
    this.refreshReady(row.id);
    this.loadLifecycle(row.id);
  }

  private commit(next: ExperienceDocument): void {
    if (this.readOnly()) return;
    this.stack.update((stack) => pushRevision(stack, next));
    this.editGeneration += 1;
    this.scheduleSave();
  }

  private scheduleSave(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.flushSave(), 400);
  }

  private loadLifecycle(id: string): void {
    this.api.listReleases(id).subscribe({ next: (rows) => this.releases.set(rows), error: () => this.releases.set([]) });
    this.loadDrifts();
    this.api.publishedSystems().subscribe((rows) => {
      const versions: Record<string, string> = {};
      for (const row of rows) {
        const version = row.published_flow_version_id;
        if (version) versions[row.id] = version;
      }
      this.publishedVersions.set(versions);
    });
  }

  private loadDrifts(): void {
    this.api.listDriftedBindings().subscribe({ next: (rows) => this.drifts.set(rows), error: () => this.drifts.set([]) });
  }
}
