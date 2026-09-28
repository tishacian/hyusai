import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { IconComponent } from '@app/shared/ui/icon.component';
import type { PassageParts } from './chat-proof';

/** One source as the proof rail shows it; every field comes from the source. */
export interface ProofSourceView {
  n: number;
  title: string;
  /** Collection name as the reader knows it (the scope label when unambiguous). */
  collection: string | null;
  /** Collection id the « Collection » link opens. */
  collectionRef: string | null;
  locator: string | null;
  passage: PassageParts | null;
  cited: boolean;
  canPreview: boolean;
}

/**
 * L30 — « Preuve ouverte »: the selected source beside the answer, its
 * passage with the supporting sentence marked, then the other proofs, cited
 * ones first and passages read but not cited set apart by a word and a
 * dashed edge (never by colour alone). Escape is owned by the chat panel,
 * which closes the rail and gives focus back to the citation.
 */
@Component({
  selector: 'app-chat-proof-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NavLinkDirective],
  template: `
    <aside
      class="proof-rail"
      [class.proof-rail--enter]="animate()"
      [attr.aria-labelledby]="headingId"
      data-testid="chat-proof-rail"
    >
      <div class="proof-head">
        <h3 class="proof-heading" [id]="headingId" tabindex="-1" #heading>
          {{ i18n.t('chat.proof.open') }}
        </h3>
        @if (selected().cited) {
          <span class="proof-number">[{{ selected().n }}]</span>
        }
        <button
          type="button"
          class="proof-close"
          [attr.aria-label]="i18n.t('chat.proof.close')"
          [title]="i18n.t('chat.proof.close')"
          (click)="closed.emit($event.detail > 0)"
        >
          <app-icon name="x" [size]="14" />
        </button>
      </div>

      <article class="proof-card" data-testid="chat-proof-selected">
        <p class="proof-doc">{{ selected().title }}</p>
        @if (whereLine(selected()); as where) {
          <p class="proof-where">{{ where }}</p>
        }
        @if (!selected().cited) {
          <p class="proof-read-tag">{{ i18n.t('chat.proof.read_not_cited') }}</p>
        }
        @if (selected().passage; as passage) {
          <!-- Kept on one line: the passage is pre-wrap, template spaces would show. -->
          <blockquote class="proof-passage" [attr.aria-label]="i18n.t('chat.proof.passage')">{{ passage.before }}<mark class="proof-mark" data-testid="chat-proof-mark">{{ passage.mark }}</mark>{{ passage.after }}</blockquote>
        } @else {
          <p class="proof-empty">{{ i18n.t('chat.proof.no_passage') }}</p>
        }
        @if (selected().canPreview || selected().collectionRef) {
          <div class="proof-actions">
            @if (selected().canPreview) {
              <button
                type="button"
                class="proof-action"
                [attr.aria-label]="i18n.t('chat.proof.page_aria', { title: selected().title })"
                (click)="pageRequested.emit(selected().n)"
              >
                {{ i18n.t('chat.proof.page') }}
              </button>
            }
            @if (selected().collectionRef; as collectionRef) {
              <a
                class="proof-action"
                [navLink]="{ leaf: 'knowledge-doc', ref: collectionRef }"
                [attr.aria-label]="i18n.t('chat.proof.collection_aria', { collection: selected().collection || collectionRef })"
                (click)="collectionOpened.emit()"
              >
                {{ i18n.t('chat.proof.collection') }}
              </a>
            }
          </div>
        }
      </article>

      @if (others().length || readOnly().length) {
        <h4 class="proof-subheading">{{ i18n.t('chat.proof.others') }}</h4>
        <ul class="proof-list">
          @for (item of others(); track item.n) {
            <li>
              <button
                type="button"
                class="proof-item"
                [attr.aria-label]="i18n.t('chat.proof.item_cited_aria', { n: item.n, title: item.title })"
                (click)="selectedChange.emit(item.n)"
              >
                <span class="proof-item-number">[{{ item.n }}]</span>
                <span class="proof-item-title">{{ item.title }}</span>
                @if (item.locator) {
                  <span class="proof-item-where">{{ item.locator }}</span>
                }
              </button>
            </li>
          }
          @for (item of readOnly(); track item.n) {
            <li>
              <button
                type="button"
                class="proof-item proof-item--read"
                [attr.aria-label]="i18n.t('chat.proof.item_read_aria', { title: item.title })"
                (click)="selectedChange.emit(item.n)"
              >
                <span class="proof-item-tag">{{ i18n.t('chat.proof.read_not_cited') }}</span>
                <span class="proof-item-title">{{ item.title }}</span>
                @if (item.locator) {
                  <span class="proof-item-where">{{ item.locator }}</span>
                }
              </button>
            </li>
          }
        </ul>
      }
    </aside>
  `,
  styles: [`
    :host { display: block; height: 100%; min-height: 0; }
    .proof-rail {
      display: flex;
      flex-direction: column;
      gap: 12px;
      height: 100%;
      min-height: 0;
      overflow-y: auto;
      padding: 16px;
      background: var(--ck-bg-base);
      color: var(--ck-fg-1);
      font-family: var(--ck-font-sans);
    }
    /* Occasional, pointer-opened only: a short slide that settles. */
    .proof-rail--enter { animation: proof-rail-in var(--ck-dur-med, 200ms) var(--ck-ease-out) both; }
    @keyframes proof-rail-in {
      from { opacity: 0; transform: translateX(12px); }
      to { opacity: 1; transform: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      .proof-rail--enter { animation: none; }
    }
    .proof-head { display: flex; align-items: center; gap: 8px; }
    .proof-heading {
      margin: 0;
      font-size: 13px;
      font-weight: 600;
      color: var(--ck-fg-2);
    }
    .proof-heading:focus { outline: none; }
    .proof-heading:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; border-radius: 2px; }
    .proof-number {
      margin-left: auto;
      font: 600 12px/1 var(--ck-font-mono);
      color: var(--ck-primary);
    }
    .proof-close {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 4px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--ck-fg-3);
    }
    .proof-head > .proof-heading + .proof-close { margin-left: auto; }
    .proof-close:hover { color: var(--ck-fg-1); border-color: var(--ck-stroke-2); }
    .proof-close:focus-visible,
    .proof-action:focus-visible,
    .proof-item:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .proof-card {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 14px;
      border: 1px solid var(--ck-stroke-hot);
      border-left: 3px solid var(--ck-primary);
      border-radius: 6px;
      background: var(--ck-bg-panel);
    }
    .proof-doc { margin: 0; font-size: 14px; font-weight: 600; line-height: 1.35; overflow-wrap: anywhere; }
    .proof-where { margin: 0; font-size: 12px; color: var(--ck-fg-3); }
    .proof-read-tag,
    .proof-item-tag {
      margin: 0;
      font-size: 11px;
      font-weight: 600;
      color: var(--ck-fg-3);
    }
    .proof-passage {
      margin: 6px 0 2px;
      padding: 10px 12px;
      border-left: 2px solid var(--ck-fg-3);
      background: var(--ck-bg-inset);
      font-size: 13px;
      line-height: 1.6;
      color: var(--ck-fg-2);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .proof-mark {
      background: color-mix(in oklab, var(--ck-primary) 20%, transparent);
      color: var(--ck-fg-1);
      border-radius: 2px;
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
      padding: 0 1px;
    }
    .proof-empty { margin: 4px 0 0; font-size: 12px; color: var(--ck-fg-3); }
    .proof-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
    .proof-action {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border: 1px solid var(--ck-stroke-3, var(--ck-stroke-2));
      border-radius: 4px;
      background: var(--ck-bg-base);
      color: var(--ck-fg-1);
      font-size: 12px;
      font-weight: 500;
      text-decoration: none;
      cursor: pointer;
    }
    .proof-action:hover { border-color: var(--ck-stroke-hot); background: var(--ck-bg-panel-hi, var(--ck-bg-panel)); }
    .proof-subheading {
      margin: 8px 0 0;
      font-size: 13px;
      font-weight: 600;
      color: var(--ck-fg-2);
    }
    .proof-list { display: flex; flex-direction: column; gap: 8px; margin: 0; padding: 0; list-style: none; }
    .proof-item {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 3px;
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--ck-stroke-2);
      border-left: 3px solid var(--ck-primary);
      border-radius: 6px;
      background: var(--ck-bg-panel);
      color: var(--ck-fg-1);
      text-align: left;
      font-size: 13px;
      line-height: 1.4;
      cursor: pointer;
    }
    .proof-item:hover { border-color: var(--ck-stroke-hot); }
    .proof-item--read {
      border-style: dashed;
      border-left: 1px dashed var(--ck-stroke-3, var(--ck-stroke-2));
      background: transparent;
      color: var(--ck-fg-2);
    }
    .proof-item-number { font: 600 12px/1 var(--ck-font-mono); color: var(--ck-primary); }
    .proof-item-title { overflow-wrap: anywhere; }
    .proof-item-where { font-size: 12px; color: var(--ck-fg-3); }
  `],
})
export class ChatProofRailComponent {
  protected readonly i18n = inject(I18nService);
  private readonly injector = inject(Injector);

  readonly selected = input.required<ProofSourceView>();
  readonly others = input<ProofSourceView[]>([]);
  readonly readOnly = input<ProofSourceView[]>([]);
  readonly animate = input(false);
  /** Bumped by the panel on each opening: focus lands on the heading. */
  readonly focusToken = input(0);

  /** `true` when a pointer closed it (the panel may animate back). */
  readonly closed = output<boolean>();
  readonly selectedChange = output<number>();
  readonly pageRequested = output<number>();
  readonly collectionOpened = output<void>();

  private static nextId = 0;
  readonly headingId = `chat-proof-heading-${++ChatProofRailComponent.nextId}`;
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  constructor() {
    effect(() => {
      if (!this.focusToken()) return;
      afterNextRender(() => this.heading()?.nativeElement.focus(), { injector: this.injector });
    });
  }

  whereLine(view: ProofSourceView): string {
    return [view.collection, view.locator].filter(Boolean).join(' · ');
  }
}
