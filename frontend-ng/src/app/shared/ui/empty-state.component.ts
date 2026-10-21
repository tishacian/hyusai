import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from './icon.component';
import type { LoadState, LoadStateKind } from './load-state';

export type EmptyStateSize = 'sm' | 'md' | 'lg';

type ShownKind = Exclude<LoadStateKind, 'ready'>;

const STATE_ICON: Record<ShownKind, string> = {
  loading: 'loader',
  empty: 'inbox',
  'no-results': 'search',
  denied: 'lock',
  error: 'alert-triangle',
};

const STATE_TONE: Record<ShownKind, string> = {
  loading: 'ck-tone-neutral',
  empty: 'ck-tone-info',
  'no-results': 'ck-tone-info',
  denied: 'ck-tone-warn',
  error: 'ck-tone-neg',
};

/**
 * Standardized empty state, and the display of the shared read contract
 * (`LoadState`, see `./load-state.ts`).
 *
 * Without `state` it is the historical empty state: an icon, a title, an
 * optional description and projected actions. Given a `state`, it tells the
 * reader which of loading, empty, no results, access denied or failed read
 * they are looking at, with the cause, a Retry button for a failed read and
 * the date of the data still on screen. A `ready` state renders nothing, so
 * a host can place it above its content unconditionally.
 *
 * Each state carries `data-testid="load-state-<state>"` for mocked e2e tests.
 *
 * Three density variants:
 * - `sm` fits inside charts / cards with fixed heights
 * - `md` (default) is for list / table containers
 * - `lg` for first-run zero states where we want to fill the page
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  imports: [NgClass, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (kind() !== 'ready') {
      <div
        class="flex flex-col items-center justify-center text-center"
        [ngClass]="{
          'py-6 px-4': size === 'sm',
          'py-12 px-6': size === 'md',
          'py-16 px-8': size === 'lg'
        }"
        [attr.data-testid]="testId()"
        [attr.data-state]="stateKind()"
        [attr.role]="role()"
        [attr.aria-busy]="stateKind() === 'loading' ? 'true' : null"
      >
        <div
          class="rounded-2xl flex items-center justify-center mb-3"
          [ngClass]="[tone(), size === 'sm' ? 'w-10 h-10' : size === 'lg' ? 'w-20 h-20' : 'w-16 h-16']"
          aria-hidden="true"
        >
          <app-icon [name]="iconName()" [size]="iconSize()" />
        </div>
        <h3
          class="font-semibold mb-1"
          [style.color]="'var(--ck-fg-1)'"
          [ngClass]="{
            'text-sm': size === 'sm',
            'text-base': size === 'md',
            'text-lg': size === 'lg'
          }"
        >
          {{ titleText() }}
        </h3>
        @if (descriptionText()) {
          <p
            class="max-w-sm mb-3"
            [style.color]="'var(--ck-fg-4)'"
            [ngClass]="{
              'text-[11px] leading-relaxed': size === 'sm',
              'text-sm': size === 'md' || size === 'lg'
            }"
          >
            {{ descriptionText() }}
          </p>
        }
        @if (freshness()) {
          <p class="max-w-sm mb-3 text-xs" [style.color]="'var(--ck-fg-3)'" data-testid="load-state-freshness">
            {{ freshness() }}
          </p>
        }
        @if (showRetry()) {
          <button
            type="button"
            class="ck-btn ck-btn--sm ck-btn-quiet mb-3"
            data-testid="load-state-retry"
            (click)="retry.emit()"
          >
            {{ i18n.t('common.retry') }}
          </button>
        }
        <ng-content />
      </div>
    }
  `,
})
export class EmptyStateComponent {
  readonly i18n = inject(I18nService);

  private readonly iconInput = signal<string | null>(null);
  private readonly titleInput = signal<string | null>(null);
  private readonly descriptionInput = signal<string | null>(null);
  private readonly causeInput = signal<string | null>(null);
  private readonly stateInput = signal<LoadState<unknown> | null>(null);
  private readonly retryableInput = signal(true);

  @Input() set icon(value: string | null | undefined) { this.iconInput.set(value || null); }
  @Input() set title(value: string | null | undefined) { this.titleInput.set(value || null); }
  @Input() set description(value: string | null | undefined) { this.descriptionInput.set(value || null); }
  @Input() size: EmptyStateSize = 'md';

  /** The read state to display. Omit it for a plain empty state. */
  @Input() set state(value: LoadState<unknown> | null | undefined) { this.stateInput.set(value ?? null); }
  /** The cause in the reader's words, when the host knows better than the status code. */
  @Input() set cause(value: string | null | undefined) { this.causeInput.set(value || null); }
  /** Show Retry on a failed read (default). Turn it off when retrying cannot help. */
  @Input() set retryable(value: boolean) { this.retryableInput.set(value); }

  /** Emitted by the Retry button of a failed read. */
  @Output() readonly retry = new EventEmitter<void>();

  /** The state given by the host, or null for a plain empty state. */
  readonly stateKind = computed<LoadStateKind | null>(() => this.stateInput()?.s ?? null);
  readonly kind = computed<LoadStateKind>(() => this.stateKind() ?? 'empty');

  readonly testId = computed(() => {
    const kind = this.stateKind();
    return kind ? `load-state-${kind}` : null;
  });

  readonly role = computed(() => {
    const kind = this.stateKind();
    if (!kind) return null;
    return kind === 'error' || kind === 'denied' ? 'alert' : 'status';
  });

  readonly tone = computed(() => {
    const kind = this.kind();
    return kind === 'ready' ? '' : STATE_TONE[kind];
  });

  readonly iconName = computed(() => {
    const explicit = this.iconInput();
    const kind = this.stateKind();
    if (!kind) return explicit ?? 'sparkles';
    if (kind === 'ready') return '';
    // A host icon names the subject of a list; a failure keeps its own sign.
    if (explicit && (kind === 'empty' || kind === 'no-results')) return explicit;
    return STATE_ICON[kind];
  });

  readonly titleText = computed(() => {
    const state = this.stateInput();
    const explicit = this.titleInput();
    if (!state) return explicit ?? '';
    switch (state.s) {
      case 'loading': return explicit ?? this.i18n.t('common.loading');
      case 'empty': return explicit ?? this.i18n.t('state.empty.title');
      case 'no-results': return this.i18n.t('state.no_results.title', { query: state.query });
      case 'denied': return this.i18n.t('state.denied.title');
      case 'error': return this.i18n.t('state.read_failed.title');
      default: return '';
    }
  });

  readonly descriptionText = computed(() => {
    const state = this.stateInput();
    const explicit = this.descriptionInput();
    const cause = this.causeInput();
    if (!state) return explicit ?? '';
    switch (state.s) {
      case 'loading': return explicit ?? '';
      case 'empty': return explicit ?? this.i18n.t('state.empty.description');
      case 'no-results': return explicit ?? this.i18n.t('state.no_results.description');
      case 'denied': return cause ?? this.i18n.t('state.denied.description');
      case 'error': return cause ?? this.readCause(state.status, state.code);
      default: return '';
    }
  });

  readonly freshness = computed(() => {
    const state = this.stateInput();
    if (state?.s !== 'error' || !state.last) return '';
    return this.i18n.t('state.read_failed.last_data', { time: this.formatTime(state.last.at) });
  });

  readonly showRetry = computed(() => this.stateKind() === 'error' && this.retryableInput());

  iconSize() {
    return this.size === 'sm' ? 18 : this.size === 'lg' ? 32 : 28;
  }

  private readCause(status: number | null, code: string | null): string {
    if (code === 'timeout') return this.i18n.t('state.read_failed.timeout');
    if (status === null) return this.i18n.t('state.read_failed.network');
    if (status === 404) return this.i18n.t('state.read_failed.not_found');
    return this.i18n.t('state.read_failed.server', { status });
  }

  private formatTime(at: number): string {
    const locale = this.i18n.locale() === 'fr' ? 'fr-FR' : 'en-GB';
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(at));
  }
}
