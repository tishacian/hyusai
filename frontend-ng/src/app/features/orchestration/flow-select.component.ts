import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { IconComponent } from '@app/shared/ui/icon.component';

export interface FlowSelectOption {
  value: string;
  label: string;
  description?: string | null;
  tone?: 'cyan' | 'emerald' | 'amber' | 'rose' | 'violet' | 'neutral';
}

@Component({
  selector: 'app-flow-select',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="df-select" [attr.data-open]="open() ? 'true' : 'false'">
      <button
        type="button"
        class="df-select-trigger"
        [disabled]="disabled"
        [title]="selected()?.description || selected()?.label || placeholder"
        (click)="toggle()"
        (keydown)="onTriggerKeydown($event)"
      >
        <span class="df-select-trigger__text">
          @if (selected(); as item) {
            <strong>{{ item.label }}</strong>
            @if (item.description) {
              <small>{{ item.description }}</small>
            }
          } @else {
            <strong class="text-gray-500">{{ placeholder }}</strong>
          }
        </span>
        @if (loading) {
          <app-icon name="loader-2" [size]="13" class="animate-spin" />
        } @else {
          <app-icon name="chevron-down" [size]="14" />
        }
      </button>

      @if (open()) {
        <div class="df-select-menu" role="listbox">
          @if (searchable) {
            <div class="df-select-search">
              <app-icon name="search" [size]="12" />
              <input
                type="text"
                [value]="query()"
                (input)="query.set($any($event.target).value || '')"
                placeholder="Search"
                autofocus
              />
            </div>
          }
          <div class="df-select-options">
            @if (allowEmpty) {
              <button
                type="button"
                class="df-select-option"
                [attr.data-selected]="!value ? 'true' : 'false'"
                (click)="choose('')"
              >
                <span>{{ emptyLabel }}</span>
              </button>
            }
            @for (item of filtered(); track item.value) {
              <button
                type="button"
                class="df-select-option"
                [attr.data-selected]="item.value === value ? 'true' : 'false'"
                [attr.data-tone]="item.tone || 'neutral'"
                (click)="choose(item.value)"
              >
                <span>{{ item.label }}</span>
                @if (item.description) {
                  <small>{{ item.description }}</small>
                }
              </button>
            }
            @if (!loading && filtered().length === 0) {
              <div class="df-select-empty">No option</div>
            }
          </div>
        </div>
      }
    </div>
  `,
})
export class FlowSelectComponent {
  @Input() value: string | null = null;
  @Input() options: FlowSelectOption[] = [];
  @Input() placeholder = 'Select';
  @Input() emptyLabel = 'None';
  @Input() allowEmpty = false;
  @Input() searchable = false;
  @Input() loading = false;
  @Input() disabled = false;

  @Output() valueChange = new EventEmitter<string | null>();
  @Output() opened = new EventEmitter<void>();

  readonly open = signal(false);
  readonly query = signal('');

  readonly selected = computed(() =>
    this.options.find((item) => item.value === this.value) ?? null,
  );

  readonly filtered = computed(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return this.options;
    return this.options.filter((item) => {
      const haystack = `${item.label} ${item.description ?? ''}`.toLowerCase();
      return haystack.includes(q);
    });
  });

  constructor(private readonly el: ElementRef<HTMLElement>) {}

  @HostListener('document:mousedown', ['$event'])
  onDocumentMouseDown(event: MouseEvent): void {
    if (!this.open()) return;
    const target = event.target as Node | null;
    if (target && this.el.nativeElement.contains(target)) return;
    this.close();
  }

  toggle(): void {
    if (this.disabled) return;
    if (this.open()) {
      this.close();
      return;
    }
    this.query.set('');
    this.open.set(true);
    this.opened.emit();
  }

  close(): void {
    this.open.set(false);
    this.query.set('');
  }

  choose(value: string): void {
    this.valueChange.emit(value || null);
    this.close();
  }

  onTriggerKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.toggle();
    } else if (event.key === 'Escape') {
      this.close();
    }
  }
}
