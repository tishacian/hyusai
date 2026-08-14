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
import { ExperienceRuntimeHostComponent } from '../runtime/runtime-host.component';
import { acceptAssistantPatch, proposeAssistantPatch, type AssistantProposal } from './studio-assistant';
import {
  apiMessage,
  StudioApiService,
  type StudioBinding,
  type StudioDetail,
} from './studio-api.service';
import {
  applyPatch,
  applyPatchOnStack,
  emptyStack,
  findNode,
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
  inventoryState,
  themeAudience,
  type StudioExperience,
} from './studio-model';
import type { ReadyCheck } from './studio-publish';
import { ExperiencePublishDialogComponent } from './publish-dialog.component';
import type { CertifiedType, ExperienceDocument, ExperienceNode, ExperiencePage } from '../runtime/model';
import { fieldsFromSchema } from '../runtime/model';
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
    <div class="xp-ed">
      <header class="xp-ed-chrome">
        <div class="xp-ed-id">
          <a routerLink="/create/apps" class="xp-btn">{{ i18n.t('experience.editor.back') }}</a>
          <strong>{{ name() }}</strong>
          <span class="xp-tag">{{ stateLabel() }}</span>
          @if (readyLabel(); as label) {
            <span class="xp-tag" [class.xp-tag-ok]="readyTone() === 'ok'" [class.xp-tag-warn]="readyTone() === 'warn'">
              {{ label }}
            </span>
          }
        </div>
        <div class="xp-ed-tools">
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
            @if (viewSlug(); as slug) {
              <a class="xp-btn" [routerLink]="['/work', slug]">{{ i18n.t('experience.editor.view') }}</a>
            }
          </div>
          <div class="xp-ed-group">
            <button type="button" class="xp-btn xp-btn-primary" (click)="publishOpen.set(true)">
              {{ i18n.t('experience.editor.publish') }}
            </button>
            <ck-help id="concept.release" />
          </div>
        </div>
      </header>

      @if (error(); as err) {
        <p class="xp-error" role="alert">{{ err }}</p>
      }

      <div class="xp-ed-grid">
        <aside class="xp-ed-col" [attr.aria-label]="i18n.t('experience.editor.tree')">
          <div class="xp-ed-col-head">
            <strong>{{ i18n.t('experience.editor.tree') }}</strong>
            <button
              type="button"
              class="xp-btn xp-btn-icon"
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
                  {{ page.title }}
                </button>
                <ul class="xp-tree">
                  @for (node of page.components; track node.id ?? $index) {
                    <li>
                      <button
                        type="button"
                        class="is-child"
                        [class.is-on]="isNodeSelected(node.id)"
                        (click)="selectNode(page.id, node.id)"
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
          <label class="xp-field">
            <span>{{ i18n.t('experience.editor.add') }}</span>
            <select [attr.aria-label]="i18n.t('experience.editor.add.aria')" (change)="addComponent($event)">
              <option value="">{{ i18n.t('experience.editor.add.choose') }}</option>
              @for (type of addable; track type) {
                <option [value]="type">{{ typeLabel(type) }}</option>
              }
            </select>
          </label>
          <p class="xp-hint">{{ i18n.t('experience.editor.add.hint') }}</p>
        </aside>

        <section class="xp-ed-col">
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
          <app-experience-runtime-host [document]="doc()" [pageId]="pageId()" />
        </section>

        <aside class="xp-ed-col" [attr.aria-label]="i18n.t('experience.editor.inspector')">
          @if (selectedNode(); as node) {
            <div class="xp-node-bar">
              <strong>{{ typeLabel(node.type) }}</strong>
              <div>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="!canMove(-1)"
                  [attr.aria-label]="i18n.t('experience.editor.move_up')"
                  [title]="i18n.t('experience.editor.move_up')"
                  (click)="moveSelected(-1)"
                >
                  ↑
                </button>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="!canMove(1)"
                  [attr.aria-label]="i18n.t('experience.editor.move_down')"
                  [title]="i18n.t('experience.editor.move_down')"
                  (click)="moveSelected(1)"
                >
                  ↓
                </button>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
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
              <strong>{{ page.title }}</strong>
              <div>
                <button
                  type="button"
                  class="xp-btn xp-btn-icon"
                  [disabled]="doc().pages.length <= 1"
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
            @for (tab of tabs; track tab) {
              <button
                type="button"
                role="tab"
                [class.is-on]="inspectorTab() === tab"
                [attr.aria-selected]="inspectorTab() === tab"
                (click)="inspectorTab.set(tab)"
              >
                {{ i18n.t('experience.editor.tab.' + tab) }}
              </button>
            }
          </div>

          @if (inspectorTab() === 'content') {
            @if (selectedPage(); as page) {
              <label class="xp-field">
                <span>{{ i18n.t('experience.editor.field.title') }}</span>
                <input [value]="page.title" (input)="renamePage(page.id, inputValue($event))" />
              </label>
            }
            @if (selectedNode(); as node) {
              @if (hasProp(node, 'title')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.title') }}</span>
                  <input [value]="str(node, 'title')" (input)="setProp(node, 'title', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'subtitle')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.subtitle') }}</span>
                  <input [value]="str(node, 'subtitle')" (input)="setProp(node, 'subtitle', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'body')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.body') }}</span>
                  <textarea [value]="str(node, 'body')" (input)="setProp(node, 'body', inputValue($event))"></textarea>
                </label>
              }
              @if (hasProp(node, 'label')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.label') }}</span>
                  <input [value]="str(node, 'label')" (input)="setProp(node, 'label', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'caption')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.caption') }}</span>
                  <input [value]="str(node, 'caption')" (input)="setProp(node, 'caption', inputValue($event))" />
                </label>
              }
              @if (hasProp(node, 'value')) {
                <label class="xp-field">
                  <span>{{ i18n.t('experience.editor.field.value') }}</span>
                  <input [value]="str(node, 'value')" (input)="setProp(node, 'value', inputValue($event))" />
                </label>
              }
            }
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
                  (change)="setProp(node, 'bindingKey', selectValue($event))"
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
                <input [value]="page.title" (input)="renamePage(page.id, inputValue($event))" />
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
        </aside>
      </div>
    </div>

    @if (id()) {
      <app-experience-publish-dialog
        [experienceId]="id()!"
        [audience]="audience()"
        [summary]="summary()"
        [open]="publishOpen()"
        (closed)="publishOpen.set(false)"
        (deployed)="reload()"
      />
    }
  `,
})
export class ExperienceEditorComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StudioApiService);
  private readonly route = inject(ActivatedRoute);
  readonly addable = ADDABLE_TYPES;
  readonly confirms = CONFIRMATION_POLICIES;
  readonly unavailable = UNAVAILABLE_POLICIES;
  readonly tabs: Tab[] = ['content', 'action', 'appearance', 'a11y'];
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
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private readyTimer: ReturnType<typeof setTimeout> | null = null;

  readonly doc = computed(() => this.stack().present);
  readonly pageId = computed(() => {
    const sel = this.selection();
    return sel?.pageId ?? this.doc().pages[0]?.id ?? null;
  });
  readonly viewSlug = computed(() => {
    const row = this.detail();
    if (!row) return null;
    return inventoryState(row.deployments) === 'draft' ? null : row.slug;
  });
  readonly audience = computed(() => ({ roles: themeAudience(this.detail()?.theme) }));

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
    return typeof value === 'string' ? value : '';
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

  addComponent(event: Event): void {
    const type = this.selectValue(event) as CertifiedType;
    (event.target as HTMLSelectElement).value = '';
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
    const sel = this.selection();
    if (sel?.kind !== 'node') return;
    this.commit(
      applyPatch(this.doc(), { kind: 'move_component', pageId: sel.pageId, nodeId: sel.nodeId, delta }),
    );
  }

  addPage(): void {
    const doc = this.doc();
    const title = this.i18n.t('experience.editor.page.new', { n: doc.pages.length + 1 });
    const pageId = newPageId(doc, title);
    this.commit(applyPatch(doc, { kind: 'add_page', pageId, title }));
    this.selection.set({ kind: 'page', pageId });
  }

  removePage(pageId: string): void {
    const doc = this.doc();
    if (doc.pages.length <= 1) return;
    const next = applyPatch(doc, { kind: 'remove_page', pageId });
    this.commit(next);
    const first = next.pages[0]?.id;
    this.selection.set(first ? { kind: 'page', pageId: first } : null);
  }

  renamePage(pageId: string, title: string): void {
    this.commit(applyPatch(this.doc(), { kind: 'rename_page', pageId, title }));
  }

  setProp(node: ExperienceNode, key: string, value: unknown): void {
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
    this.api.patchBinding(key, body).subscribe({
      next: (row) => {
        this.bindings.update((list) => list.map((item) => (item.binding_key === row.binding_key ? row : item)));
      },
      error: (err) => this.error.set(apiMessage(err, this.i18n.t('experience.editor.save_error'))),
    });
  }

  undo(): void {
    this.stack.update(undoRevision);
    this.scheduleSave();
  }

  redo(): void {
    this.stack.update(redoRevision);
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
    const item = this.proposal();
    if (!item || !acceptAssistantPatch(item.patch)) {
      this.proposal.set(null);
      this.assistantMiss.set(true);
      return;
    }
    this.stack.update((stack) => applyPatchOnStack(stack, item.patch));
    this.proposal.set(null);
    this.scheduleSave();
  }

  proposalSummary(item: AssistantProposal): string {
    const page = item.after.pages.find((row) => row.id === (item.patch as { pageId: string }).pageId);
    if (item.summary === 'set_empty_state') {
      return this.i18n.t('experience.assistant.diff.add_empty', { page: page?.title ?? '' });
    }
    if (item.summary === 'rename_page' && item.patch.kind === 'rename_page') {
      return this.i18n.t('experience.assistant.diff.rename', { title: item.patch.title });
    }
    if (item.summary === 'set_density') {
      return this.i18n.t('experience.assistant.diff.density', { page: page?.title ?? '' });
    }
    if (item.summary === 'update_props' || item.summary === 'json_patch') {
      return this.i18n.t('experience.assistant.diff.update', { page: page?.title ?? '' });
    }
    return this.i18n.t('experience.assistant.diff.approval', { page: page?.title ?? '' });
  }

  flushSave(): void {
    const id = this.id();
    if (!id) return;
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
      this.saveTimer = null;
    }
    this.saving.set(true);
    this.api.saveDraft(id, pagesPayload(this.doc()), this.bindingKeys()).subscribe({
      next: () => {
        this.saving.set(false);
        this.refreshReady(id);
      },
      error: (err) => {
        this.error.set(apiMessage(err, this.i18n.t('experience.editor.save_error')));
        this.saving.set(false);
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
    this.refreshReady(row.id);
  }

  private commit(next: ExperienceDocument): void {
    this.stack.update((stack) => pushRevision(stack, next));
    this.scheduleSave();
  }

  private scheduleSave(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.flushSave(), 400);
  }
}
