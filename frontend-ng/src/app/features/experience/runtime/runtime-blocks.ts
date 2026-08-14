import {
  ChangeDetectionStrategy,
  Component,
  type Type,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { take } from 'rxjs/operators';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { TagComponent, type CkTagTone } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { ExperienceRuntimeService } from './experience-runtime.service';
import {
  type CertifiedType,
  type ExperienceNode,
  type RuntimeField,
  extractCitations,
  extractResult,
  fieldsFromSchema,
  mapRunStatus,
  seedFromSchema,
  unavailablePolicy,
  validateValues,
  valuesToPayload,
} from './model';
import { a11yOf, appearanceOf } from './style';

function str(node: ExperienceNode, key: string, fallback = ''): string {
  const value = node.props?.[key];
  return typeof value === 'string' ? value : fallback;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

type Slot = 'ready' | 'loading' | 'empty' | 'error';

function slotOf(node: ExperienceNode, empty: boolean, loading = false, error = false): Slot {
  if (node.props?.['loading'] === true || loading) return 'loading';
  if (typeof node.props?.['error'] === 'string' || error) return 'error';
  if (empty) return 'empty';
  return 'ready';
}

@Component({
  selector: 'xp-rt-slot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-empty-state icon="sparkles" size="sm" [title]="i18n.t('common.loading')" />
      }
      @case ('error') {
        <app-empty-state
          icon="alert-triangle"
          size="sm"
          [title]="i18n.t('state.error.title')"
          [description]="detail() || undefined"
        />
      }
      @case ('empty') {
        <app-empty-state
          icon="inbox"
          size="sm"
          [title]="i18n.t('state.empty.title')"
          [description]="empty() || i18n.t('state.empty.description')"
        />
      }
      @default {
        <ng-content />
      }
    }
  `,
})
export class RuntimeSlotComponent {
  readonly i18n = inject(I18nService);
  readonly state = input<Slot>('ready');
  readonly detail = input('');
  readonly empty = input('');
}

@Component({
  selector: 'xp-rt-fallback',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <aside class="xp-rt-block xp-rt-fallback" role="note">
      <h3>{{ i18n.t('experience.runtime.unknown.title') }}</h3>
      <p class="xp-rt-sub">{{ i18n.t('experience.runtime.unknown.body') }}</p>
    </aside>
  `,
})
export class FallbackBlock {
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
}

@Component({
  selector: 'xp-rt-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @switch (level()) {
        @case (2) { <h2>{{ title() }}</h2> }
        @case (4) { <h4>{{ title() }}</h4> }
        @default { <h3>{{ title() }}</h3> }
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
    </section>
  `,
})
export class SectionBlock {
  readonly node = input.required<ExperienceNode>();
  readonly title = computed(() => appearanceOf(this.node()).title || this.node().id || '');
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly level = computed(() => a11yOf(this.node()).headingLevel ?? 3);
}

@Component({
  selector: 'xp-rt-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <header class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @switch (level()) {
        @case (2) { <h2 class="xp-rt-head">{{ title() }}</h2> }
        @case (4) { <h4 class="xp-rt-head">{{ title() }}</h4> }
        @default { <h3 class="xp-rt-head">{{ title() }}</h3> }
      }
      @if (subtitle()) {
        <p class="xp-rt-sub">{{ subtitle() }}</p>
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
    </header>
  `,
})
export class HeaderBlock {
  readonly node = input.required<ExperienceNode>();
  readonly title = computed(() => appearanceOf(this.node()).title || this.node().id || '');
  readonly subtitle = computed(() => str(this.node(), 'subtitle'));
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly level = computed(() => a11yOf(this.node()).headingLevel ?? 3);
}

@Component({
  selector: 'xp-rt-callout',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  styleUrl: './runtime.scss',
  template: `
    <aside class="xp-rt-block" role="note">
      <p class="xp-rt-sub">{{ body() }}</p>
      @if (href()) {
        <a class="xp-rt-link" [routerLink]="href()">{{ href() }}</a>
      }
    </aside>
  `,
})
export class CalloutBlock {
  readonly node = input.required<ExperienceNode>();
  readonly body = computed(() => str(this.node(), 'body'));
  readonly href = computed(() => {
    const value = this.node().props?.['href'];
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return null;
    return trimmed;
  });
}

@Component({
  selector: 'xp-rt-kpi',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <article class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      <p class="xp-rt-sub">{{ label() }}</p>
      <p class="xp-rt-kpi">{{ value() }}</p>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
    </article>
  `,
})
export class KpiBlock {
  readonly node = input.required<ExperienceNode>();
  readonly label = computed(() => str(this.node(), 'label'));
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly value = computed(() => {
    const raw = this.node().props?.['value'];
    return raw === undefined || raw === null ? '—' : String(raw);
  });
}

@Component({
  selector: 'xp-rt-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      @if (title()) {
        <h3>{{ title() }}</h3>
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-slot [state]="slot()" [empty]="emptyText()">
        <table class="xp-rt-table">
          @if (caption()) {
            <caption class="xp-rt-sub">{{ caption() }}</caption>
          }
          <thead>
            <tr>
              @for (col of columns(); track col.key) {
                <th scope="col">{{ col.label }}</th>
              }
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track $index) {
              <tr>
                @for (col of columns(); track col.key) {
                  <td>{{ cell(row, col.key) }}</td>
                }
              </tr>
            }
          </tbody>
        </table>
      </xp-rt-slot>
    </div>
  `,
})
export class TableBlock {
  readonly node = input.required<ExperienceNode>();
  readonly columns = computed(() => {
    const raw = list(this.node().props?.['columns']);
    return raw.map((item, index) => {
      if (typeof item === 'string') return { key: item, label: item };
      if (isRecord(item) && typeof item['key'] === 'string') {
        return {
          key: item['key'],
          label: typeof item['label'] === 'string' ? item['label'] : item['key'],
        };
      }
      return { key: `c${index}`, label: String(item) };
    });
  });
  readonly rows = computed(() => list(this.node().props?.['rows']).filter(isRecord));
  readonly caption = computed(() => str(this.node(), 'caption'));
  readonly title = computed(() => appearanceOf(this.node()).title);
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly slot = computed(() => slotOf(this.node(), this.rows().length === 0));
  cell(row: Record<string, unknown>, key: string): string {
    const value = row[key];
    return value === undefined || value === null ? '' : String(value);
  }
}

@Component({
  selector: 'xp-rt-queue',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="ariaName() || i18n.t('experience.runtime.queue.title')">
      <h3>{{ title() || i18n.t('experience.runtime.queue.title') }}</h3>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-slot [state]="slot()" [empty]="emptyText()">
        <ul class="xp-rt-list">
          @for (item of items(); track $index) {
            <li>{{ item }}</li>
          }
        </ul>
      </xp-rt-slot>
    </section>
  `,
})
export class QueueBlock {
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly items = computed(() =>
    list(this.node().props?.['items']).map((item) => {
      if (typeof item === 'string') return item;
      if (isRecord(item) && typeof item['title'] === 'string') return item['title'];
      return String(item);
    }),
  );
  readonly title = computed(() => appearanceOf(this.node()).title);
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly slot = computed(() => slotOf(this.node(), this.items().length === 0));
}

@Component({
  selector: 'xp-rt-approval',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, TagComponent],
  styleUrl: './runtime.scss',
  template: `
    <article class="xp-rt-block" [attr.aria-label]="ariaName() || null">
      <xp-rt-slot [state]="slot()" [empty]="emptyText()">
        <div class="xp-rt-row">
          <h3>{{ title() }}</h3>
          @if (status()) {
            <ck-tag tone="warn">{{ status() }}</ck-tag>
          }
        </div>
        <p class="xp-rt-sub">{{ body() }}</p>
        @if (description()) {
          <p class="xp-rt-sub">{{ description() }}</p>
        }
      </xp-rt-slot>
    </article>
  `,
})
export class ApprovalCardBlock {
  readonly node = input.required<ExperienceNode>();
  readonly title = computed(() =>
    appearanceOf(this.node()).title || this.node().id || '',
  );
  readonly body = computed(() => str(this.node(), 'body'));
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly status = computed(() => str(this.node(), 'status'));
  readonly slot = computed(() =>
    slotOf(this.node(), !this.title() && !this.body()),
  );
}

@Component({
  selector: 'xp-rt-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="i18n.t('experience.runtime.history.title')">
      <h3>{{ i18n.t('experience.runtime.history.title') }}</h3>
      <ul class="xp-rt-list">
        @for (item of items(); track $index) {
          <li>
            <span>{{ item.title }}</span>
            @if (item.at) {
              <span>{{ item.at }}</span>
            }
          </li>
        }
      </ul>
    </section>
  `,
})
export class HistoryBlock {
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly items = computed(() =>
    list(this.node().props?.['items']).map((item) => {
      if (typeof item === 'string') return { title: item, at: '' };
      if (isRecord(item)) {
        return {
          title: typeof item['title'] === 'string' ? item['title'] : String(item['title'] ?? ''),
          at: typeof item['at'] === 'string' ? item['at'] : '',
        };
      }
      return { title: String(item), at: '' };
    }),
  );
}

@Component({
  selector: 'xp-rt-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TagComponent],
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block xp-rt-row">
      <ck-tag [tone]="tone()">{{ label() }}</ck-tag>
    </div>
  `,
})
export class RuntimeStatusBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly vocab = computed(() => {
    const raw = str(this.node(), 'status') || this.runtime.run()?.status;
    return mapRunStatus(raw);
  });
  readonly label = computed(() => {
    const vocab = this.vocab();
    if (!vocab) return this.i18n.t('state.empty.title');
    return this.i18n.t(`experience.runtime.status.${vocab}`);
  });
  readonly tone = computed<CkTagTone>(() => {
    switch (this.vocab()) {
      case 'completed':
        return 'pos';
      case 'pending_validation':
      case 'running':
        return 'cool';
      case 'retry':
        return 'warn';
      case 'error':
        return 'neg';
      default:
        return 'neutral';
    }
  });
}

@Component({
  selector: 'xp-rt-result',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="i18n.t('experience.runtime.result.title')">
      <h3>{{ i18n.t('experience.runtime.result.title') }}</h3>
      <xp-rt-slot [state]="slot()" [detail]="errorText()">
        @if (pairs(); as rows) {
          <dl class="xp-rt-kv">
            @for (row of rows; track row[0]) {
              <dt>{{ row[0] }}</dt>
              <dd>{{ row[1] }}</dd>
            }
          </dl>
        } @else if (pretty()) {
          <pre class="xp-rt-pre">{{ pretty() }}</pre>
        }
      </xp-rt-slot>
    </section>
  `,
})
export class ResultBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly data = computed(() => {
    const fromProps = this.node().props?.['value'];
    if (fromProps !== undefined) return fromProps;
    return extractResult(this.runtime.run());
  });
  readonly pairs = computed(() => {
    const data = this.data();
    if (!isRecord(data) || Array.isArray(data)) return null;
    const entries = Object.entries(data).filter(([, value]) => !isRecord(value) && !Array.isArray(value));
    return entries.length > 0 && entries.length === Object.keys(data).length
      ? entries.map(([key, value]) => [key, String(value)] as const)
      : null;
  });
  readonly pretty = computed(() => {
    const data = this.data();
    if (data === null || data === undefined) return '';
    try {
      return JSON.stringify(data, null, 2);
    } catch {
      return String(data);
    }
  });
  readonly slot = computed(() =>
    slotOf(
      this.node(),
      this.data() === null || this.data() === undefined,
      this.runtime.phase() === 'loading' || this.runtime.phase() === 'running',
      this.runtime.phase() === 'error',
    ),
  );
  readonly errorText = computed(() => this.runtime.lastError() ?? '');
}

@Component({
  selector: 'xp-rt-evidence',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="i18n.t('experience.runtime.evidence.title')">
      <h3>{{ i18n.t('experience.runtime.evidence.title') }}</h3>
      @if (citations().length === 0) {
        <p class="xp-rt-sub">{{ i18n.t('state.empty.description') }}</p>
      } @else {
        <ul class="xp-rt-list">
          @for (item of citations(); track $index) {
            <li>
              <span>{{ item.title }}</span>
              @if (item.source) {
                <span>{{ item.source }}</span>
              }
            </li>
          }
        </ul>
      }
    </section>
  `,
})
export class EvidenceBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly citations = computed(() => {
    const fromProps = this.node().props?.['citations'];
    if (Array.isArray(fromProps)) {
      return extractCitations({ output_ref: { citations: fromProps } });
    }
    return extractCitations(this.runtime.run());
  });
}

@Component({
  selector: 'xp-rt-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, EmptyStateComponent],
  styleUrl: './runtime.scss',
  template: `
    <form
      class="xp-rt-block"
      (submit)="$event.preventDefault(); submit()"
      [attr.aria-busy]="busy()"
      [attr.aria-label]="ariaName() || null"
    >
      @if (title()) {
        <h3>{{ title() }}</h3>
      }
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      @if (blocked()) {
        <app-empty-state
          icon="alert-triangle"
          size="sm"
          [title]="unavailableTitle()"
          [description]="unavailableBody()"
        />
      }
      <xp-rt-slot [state]="slot()" [empty]="emptyText()">
        @for (field of fields(); track field.name) {
          <div class="xp-rt-field">
            <label [for]="fid(field)">{{ field.label }}</label>
            @switch (field.kind) {
              @case ('boolean') {
                <input
                  type="checkbox"
                  [id]="fid(field)"
                  [checked]="values()[field.name] === true"
                  [attr.aria-invalid]="!!errors()[field.name]"
                  [attr.aria-describedby]="descId(field)"
                  (change)="set(field.name, checkboxValue($event))"
                />
              }
              @case ('enum') {
                <select
                  [id]="fid(field)"
                  [value]="strVal(field.name)"
                  [attr.aria-invalid]="!!errors()[field.name]"
                  [attr.aria-describedby]="descId(field)"
                  (change)="set(field.name, inputValue($event))"
                >
                  <option value=""></option>
                  @for (opt of field.options; track opt) {
                    <option [value]="opt">{{ opt }}</option>
                  }
                </select>
              }
              @default {
                <input
                  [type]="inputType(field)"
                  [id]="fid(field)"
                  [value]="strVal(field.name)"
                  [attr.aria-invalid]="!!errors()[field.name]"
                  [attr.aria-describedby]="descId(field)"
                  (input)="set(field.name, inputValue($event))"
                />
              }
            }
            @if (field.kind === 'file') {
              <p class="xp-rt-hint" [id]="fid(field) + '-hint'">{{ i18n.t('experience.runtime.form.file_hint') }}</p>
            }
            @if (errors()[field.name]; as err) {
              <p class="xp-rt-err" [id]="fid(field) + '-err'" role="alert">
                {{ i18n.t(err === 'required' ? 'experience.runtime.form.required' : 'experience.runtime.form.invalid') }}
              </p>
            }
          </div>
        }
        @if (confirming()) {
          <div class="xp-rt-confirm" role="dialog" aria-modal="true" [attr.aria-labelledby]="confirmTitleId">
            <h3 [id]="confirmTitleId">{{ i18n.t('experience.runtime.form.confirm_title') }}</h3>
            <p class="xp-rt-sub">{{ i18n.t('experience.runtime.form.confirm_body') }}</p>
            <div class="xp-rt-actions">
              <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="confirming.set(false)">
                {{ i18n.t('common.cancel') }}
              </button>
              <button type="button" class="xp-rt-btn" (click)="invoke(true)">
                {{ i18n.t('common.confirm') }}
              </button>
            </div>
          </div>
        } @else {
          <div class="xp-rt-actions">
            <button type="submit" class="xp-rt-btn" [disabled]="busy() || blocked()">
              {{ i18n.t('experience.runtime.form.submit') }}
            </button>
            @if (canRetry()) {
              <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="retry()">
                {{ i18n.t('common.retry') }}
              </button>
            }
          </div>
        }
      </xp-rt-slot>
    </form>
  `,
})
export class FormBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly values = signal<Record<string, unknown>>({});
  readonly errors = signal<Record<string, 'required' | 'invalid'>>({});
  readonly confirming = signal(false);
  readonly resolveStatus = signal<string | null>(null);
  readonly policy = signal(unavailablePolicy(undefined));
  readonly confirmTitleId = 'xp-rt-confirm-title';

  readonly fields = computed(() => fieldsFromSchema(this.node().props?.['schema']));
  readonly title = computed(() => appearanceOf(this.node()).title);
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly bindingKey = computed(() => str(this.node(), 'bindingKey'));
  readonly busy = computed(
    () => this.runtime.phase() === 'loading' || this.runtime.phase() === 'running',
  );
  readonly blocked = computed(() => {
    const status = this.resolveStatus();
    return !!status && status !== 'ok';
  });
  readonly slot = computed<Slot>(() => slotOf(this.node(), this.fields().length === 0));
  readonly unavailableTitle = computed(() => {
    if (this.policy() === 'admin-repair') return this.i18n.t('experience.runtime.unavailable.repair.title');
    if (this.policy() === 'empty') return this.i18n.t('experience.runtime.unavailable.empty.title');
    return this.i18n.t('experience.runtime.unavailable.title');
  });
  readonly unavailableBody = computed(() => {
    if (this.policy() === 'admin-repair') return this.i18n.t('experience.runtime.unavailable.repair.body');
    if (this.policy() === 'empty') return this.i18n.t('experience.runtime.unavailable.empty.body');
    return this.i18n.t('experience.runtime.unavailable.body');
  });
  readonly canRetry = computed(() => {
    const status = mapRunStatus(this.runtime.run()?.status);
    return status === 'error' || status === 'retry' || this.runtime.phase() === 'error';
  });

  constructor() {
    effect(() => {
      this.values.set({ ...seedFromSchema(this.node().props?.['schema']) });
      this.errors.set({});
    });
    effect(() => {
      const key = this.bindingKey();
      if (!key) {
        this.resolveStatus.set(null);
        return;
      }
      this.runtime.resolve(key).pipe(take(1)).subscribe((resolved) => {
        if (!resolved) {
          this.resolveStatus.set('unavailable');
          this.policy.set('unavailable');
          return;
        }
        this.resolveStatus.set(resolved.status);
        this.policy.set(unavailablePolicy(resolved.binding.on_unavailable));
        this.confirmation = resolved.binding.confirmation_policy === 'confirm';
      });
    });
  }

  private confirmation = false;

  fid(field: RuntimeField): string {
    return `xp-rt-${this.node().id ?? 'form'}-${field.name}`;
  }

  descId(field: RuntimeField): string | null {
    if (this.errors()[field.name]) return `${this.fid(field)}-err`;
    if (field.kind === 'file') return `${this.fid(field)}-hint`;
    return null;
  }

  strVal(name: string): string {
    const value = this.values()[name];
    return value === undefined || value === null ? '' : String(value);
  }

  inputType(field: RuntimeField): string {
    if (field.kind === 'number' || field.kind === 'integer') return 'number';
    if (field.kind === 'date') return 'date';
    return 'text';
  }

  set(name: string, value: unknown): void {
    this.values.update((current) => ({ ...current, [name]: value }));
  }

  inputValue(event: Event): string {
    return (event.target as HTMLInputElement | HTMLSelectElement).value;
  }

  checkboxValue(event: Event): boolean {
    return (event.target as HTMLInputElement).checked;
  }

  submit(): void {
    const next = validateValues(this.fields(), this.values());
    this.errors.set(next);
    if (Object.keys(next).length > 0 || this.blocked() || !this.bindingKey()) return;
    if (this.confirmation) {
      this.confirming.set(true);
      return;
    }
    this.invoke(false);
  }

  invoke(confirmed: boolean): void {
    this.confirming.set(false);
    const payload = valuesToPayload(this.fields(), this.values());
    this.runtime.invoke(this.bindingKey(), payload, confirmed || undefined).subscribe((started) => {
      if (started?.id) this.runtime.poll(started.id).subscribe();
    });
  }

  retry(): void {
    this.runtime.retry().subscribe((started) => {
      if (started?.id) this.runtime.poll(started.id).subscribe();
    });
  }
}

@Component({
  selector: 'xp-rt-action',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './runtime.scss',
  template: `
    <div class="xp-rt-block">
      @if (confirming()) {
        <div class="xp-rt-confirm" role="dialog" aria-modal="true" aria-labelledby="xp-rt-action-confirm">
          <h3 id="xp-rt-action-confirm">{{ i18n.t('experience.runtime.form.confirm_title') }}</h3>
          <p class="xp-rt-sub">{{ i18n.t('experience.runtime.form.confirm_body') }}</p>
          <div class="xp-rt-actions">
            <button type="button" class="xp-rt-btn xp-rt-btn-ghost" (click)="confirming.set(false)">
              {{ i18n.t('common.cancel') }}
            </button>
            <button type="button" class="xp-rt-btn" (click)="invoke(true)">{{ i18n.t('common.confirm') }}</button>
          </div>
        </div>
      } @else {
        <button
          type="button"
          class="xp-rt-btn"
          [disabled]="busy() || blocked()"
          [attr.aria-label]="ariaName() || null"
          (click)="onClick()"
        >
          {{ label() }}
        </button>
      }
    </div>
  `,
})
export class ActionButtonBlock {
  private readonly runtime = inject(ExperienceRuntimeService);
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly confirming = signal(false);
  readonly resolveStatus = signal<string | null>(null);
  private confirmation = false;

  readonly label = computed(
    () => str(this.node(), 'label') || this.i18n.t('experience.runtime.form.submit'),
  );
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly bindingKey = computed(() => str(this.node(), 'bindingKey'));
  readonly busy = computed(
    () => this.runtime.phase() === 'loading' || this.runtime.phase() === 'running',
  );
  readonly blocked = computed(() => {
    const status = this.resolveStatus();
    return !!status && status !== 'ok';
  });

  constructor() {
    effect(() => {
      const key = this.bindingKey();
      if (!key) {
        this.resolveStatus.set(null);
        return;
      }
      this.runtime.resolve(key).pipe(take(1)).subscribe((resolved) => {
        if (!resolved) {
          this.resolveStatus.set('unavailable');
          return;
        }
        this.resolveStatus.set(resolved.status);
        this.confirmation = resolved.binding.confirmation_policy === 'confirm';
      });
    });
  }

  onClick(): void {
    if (this.blocked() || !this.bindingKey()) return;
    if (this.confirmation) {
      this.confirming.set(true);
      return;
    }
    this.invoke(false);
  }

  invoke(confirmed: boolean): void {
    this.confirming.set(false);
    const input = this.node().props?.['input'];
    const payload = isRecord(input) ? input : {};
    this.runtime.invoke(this.bindingKey(), payload, confirmed || undefined).subscribe((started) => {
      if (started?.id) this.runtime.poll(started.id).subscribe();
    });
  }
}

@Component({
  selector: 'xp-rt-feed',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RuntimeSlotComponent, TagComponent, RouterLink],
  styleUrl: './runtime.scss',
  template: `
    <section class="xp-rt-block" [attr.aria-label]="ariaName() || title()">
      <div class="xp-rt-row">
        <h3>{{ title() }}</h3>
      </div>
      @if (description()) {
        <p class="xp-rt-sub">{{ description() }}</p>
      }
      <xp-rt-slot [state]="slot()" [empty]="emptyText()">
        <ul class="xp-rt-list">
          @for (item of items(); track $index) {
            <li>
              <span>{{ item.title }}</span>
              @if (item.when) {
                <span>{{ item.when }}</span>
              }
              @if (item.tone) {
                <ck-tag [tone]="item.tone">{{ item.tone }}</ck-tag>
              }
              @if (item.detail) {
                <span class="xp-rt-sub">{{ item.detail }}</span>
              }
            </li>
          }
        </ul>
      </xp-rt-slot>
      @if (href()) {
        <a class="xp-rt-link" [routerLink]="href()">{{ href() }}</a>
      }
    </section>
  `,
})
export class FeedBlock {
  readonly i18n = inject(I18nService);
  readonly node = input.required<ExperienceNode>();
  readonly title = computed(() => {
    const custom = appearanceOf(this.node()).title;
    if (custom) return custom;
    switch (this.node().type) {
      case 'map_panel':
        return this.i18n.t('experience.runtime.map_panel.title');
      case 'agenda_panel':
        return this.i18n.t('experience.runtime.agenda_panel.title');
      case 'intelligence_feed':
        return this.i18n.t('experience.runtime.intelligence_feed.title');
      case 'decision_queue':
        return this.i18n.t('experience.runtime.decision_queue.title');
      default:
        return this.node().id || '';
    }
  });
  readonly description = computed(() => appearanceOf(this.node()).description);
  readonly ariaName = computed(() => a11yOf(this.node()).ariaLabel);
  readonly emptyText = computed(() => a11yOf(this.node()).emptyText);
  readonly href = computed(() => {
    const value = this.node().props?.['href'];
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return null;
    return trimmed;
  });
  readonly items = computed(() =>
    list(this.node().props?.['items']).map((item) => {
      if (typeof item === 'string') return { title: item, detail: '', when: '', tone: '' as CkTagTone | '' };
      if (!isRecord(item)) return { title: String(item), detail: '', when: '', tone: '' as CkTagTone | '' };
      const toneRaw = typeof item['tone'] === 'string' ? item['tone'].toLowerCase() : '';
      const tone: CkTagTone | '' =
        toneRaw === 'pos' || toneRaw === 'ok' || toneRaw === 'good'
          ? 'pos'
          : toneRaw === 'neg' || toneRaw === 'danger' || toneRaw === 'critical'
            ? 'neg'
            : toneRaw === 'warn' || toneRaw === 'watch'
              ? 'warn'
              : toneRaw === 'cool' || toneRaw === 'info'
                ? 'cool'
                : toneRaw === 'violet'
                  ? 'violet'
                  : toneRaw === 'neutral'
                    ? 'neutral'
                    : '';
      return {
        title:
          typeof item['title'] === 'string'
            ? item['title']
            : typeof item['label'] === 'string'
              ? item['label']
              : String(item['title'] ?? ''),
        detail:
          typeof item['detail'] === 'string'
            ? item['detail']
            : typeof item['source'] === 'string'
              ? item['source']
              : typeof item['body'] === 'string'
                ? item['body']
                : '',
        when: typeof item['when'] === 'string' ? item['when'] : '',
        tone,
      };
    }),
  );
  readonly slot = computed(() => slotOf(this.node(), this.items().length === 0));
}

export const CATALOG: Record<CertifiedType, Type<unknown>> = {
  section: SectionBlock,
  header: HeaderBlock,
  form: FormBlock,
  action_button: ActionButtonBlock,
  result: ResultBlock,
  table: TableBlock,
  queue: QueueBlock,
  approval_card: ApprovalCardBlock,
  runtime_status: RuntimeStatusBlock,
  evidence: EvidenceBlock,
  history: HistoryBlock,
  kpi: KpiBlock,
  callout: CalloutBlock,
  map_panel: FeedBlock,
  agenda_panel: FeedBlock,
  intelligence_feed: FeedBlock,
  decision_queue: FeedBlock,
};
