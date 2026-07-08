import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IconComponent } from './icon.component';

@Component({
  selector: 'app-search-input',
  standalone: true,
  imports: [FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="relative">
      <span class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
        <app-icon name="search" [size]="14" />
      </span>
      <input
        [value]="value"
        (input)="onInput($event)"
        [placeholder]="placeholder"
        type="text"
        class="w-full pl-9 pr-8 py-2 text-sm rounded bg-black/20 dark:bg-black/30 border border-white/10 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/60 focus:border-cyan-500/50 transition"
      />
      @if (value) {
        <button
          type="button"
          (click)="clear()"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white p-0.5 rounded"
          aria-label="Clear"
        >
          <app-icon name="x" [size]="12" />
        </button>
      }
    </div>
  `,
})
export class SearchInputComponent {
  @Input() value: string = '';
  @Input() placeholder: string = 'Search...';
  @Output() valueChange = new EventEmitter<string>();

  onInput(ev: Event): void {
    this.value = (ev.target as HTMLInputElement).value;
    this.valueChange.emit(this.value);
  }

  clear(): void {
    this.value = '';
    this.valueChange.emit('');
  }
}
