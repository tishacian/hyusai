import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { IconComponent } from '@app/shared/ui/icon.component';

export interface EmbeddingNodeSelection {
  document_id?: string;
  title?: string;
  collection?: string;
  chunk_count?: number;
}

@Component({
  selector: 'app-embedding-map',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="rounded-md border border-white/10 bg-white/[0.03] p-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="text-[10px] uppercase tracking-[0.18em] text-cyan-300">Embedding map</p>
          <h3 class="mt-1 text-sm font-semibold text-white">{{ collection() || 'Collection' }}</h3>
        </div>
        <app-icon name="network" [size]="18" class="text-cyan-300" />
      </div>
      <div class="mt-4 grid gap-2 sm:grid-cols-3">
        @for (node of placeholderNodes(); track node.document_id) {
          <button
            type="button"
            class="rounded-md border border-white/10 bg-gray-950/50 px-3 py-2 text-left hover:border-cyan-400/40 hover:bg-cyan-400/10"
            (click)="previewRequested.emit(node)"
          >
            <span class="block truncate text-xs font-medium text-gray-100">{{ node.title }}</span>
            <span class="mt-1 block text-[10px] text-gray-500">{{ node.chunk_count }} chunks</span>
          </button>
        }
      </div>
    </section>
  `,
})
export class EmbeddingMapComponent {
  readonly collection = input<string>('');
  readonly previewRequested = output<EmbeddingNodeSelection>();

  placeholderNodes(): EmbeddingNodeSelection[] {
    const collection = this.collection();
    return [
      {
        document_id: '',
        title: collection ? `${collection} · documents` : 'Indexed documents',
        collection,
        chunk_count: 0,
      },
    ];
  }
}
