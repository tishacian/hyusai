import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ToastrService } from 'ngx-toastr';
import { IconComponent } from '@app/shared/ui/icon.component';
import { SectionHeaderComponent } from '@app/shared/ui/section-header.component';
import { StatTileComponent } from '@app/shared/ui/stat-tile.component';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

interface DocInfo {
  collection: string;
  count: number;
}

@Component({
  selector: 'app-knowledge-base',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    IconComponent,
    SectionHeaderComponent,
    StatTileComponent,
    EmptyStateComponent,
    StatusPulseComponent,
  ],
  template: `
    <app-section-header
      breadcrumb="Build"
      title="Knowledge"
      icon="database"
      subtitle="Ingest documents and give every system fresh context."
    >
      <button
        type="button"
        (click)="fileInput.click()"
        class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded text-sm font-medium bg-brand-500 hover:bg-brand-600 text-white shadow-glow-sm transition"
      >
        <app-icon name="cloud-upload" [size]="14" /> Upload
      </button>
    </app-section-header>

    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <app-stat-tile label="Collections" [value]="collections().length" icon="boxes" />
      <app-stat-tile label="Chunks" [value]="totalChunks()" icon="braces" />
      <app-stat-tile label="Retrievals · 24h" value="842" icon="activity" trend="up" delta="+18%" />
      <app-stat-tile label="Reindex" value="Live" icon="refresh-cw" />
    </div>

    <!-- Dropzone -->
    <div
      class="relative rounded-md p-10 text-center mb-6 transition-colors cursor-pointer group"
      [class.border-2]="true"
      [class.border-dashed]="true"
      [class.border-white\\/10]="!dragging()"
      [class.border-brand-500\\/60]="dragging()"
      [class.bg-brand-500\\/5]="dragging()"
      (dragover)="onDragOver($event)"
      (dragleave)="onDragLeave($event)"
      (drop)="onDrop($event)"
      (click)="fileInput.click()"
    >
      <input
        #fileInput
        type="file"
        multiple
        class="hidden"
        (change)="onFileSelect($event)"
        accept=".pdf,.txt,.md,.docx,.csv,.json"
      />
      <div
        class="mx-auto w-16 h-16 rounded-xl flex items-center justify-center bg-gradient-to-br from-brand-500/15 to-violet-500/15 ring-1 ring-brand-500/30 text-brand-400 mb-3 shadow-glow-sm group-hover:scale-105 transition-transform"
      >
        <app-icon name="cloud-upload" [size]="28" />
      </div>
      <p class="text-sm font-medium text-white">
        Drag & drop files here <span class="text-gray-400">or</span>
        <span class="text-brand-400">click to browse</span>
      </p>
      <p class="text-xs text-gray-500 mt-1">PDF · TXT · MD · DOCX · CSV · JSON</p>

      @if (uploading()) {
        <div class="absolute inset-x-4 bottom-4 flex items-center gap-2 justify-center text-xs text-brand-300">
          <app-icon name="loader-2" [size]="14" class="animate-spin" />
          Uploading…
        </div>
      }
    </div>

    <!-- Collections -->
    @if (collections().length === 0) {
      <div class="t-card t-elevated rounded-md">
        <app-empty-state
          icon="database"
          title="No collections yet"
          description="Upload your first document to build a knowledge base for your systems."
        />
      </div>
    } @else {
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        @for (doc of collections(); track doc.collection) {
          <div class="t-card t-elevated rounded-md p-5 group">
            <div class="flex items-start gap-3 mb-4">
              <div
                class="w-10 h-10 rounded-md flex items-center justify-center bg-gradient-to-br from-brand-500/20 to-violet-500/20 ring-1 ring-brand-500/30 text-brand-400 shrink-0"
              >
                <app-icon name="folder" [size]="18" />
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="font-semibold text-white truncate">{{ doc.collection }}</h3>
                <div class="text-xs text-gray-500 mt-0.5 flex items-center gap-1">
                  <app-icon name="braces" [size]="11" />
                  {{ doc.count }} chunks
                </div>
              </div>
            </div>

            <div class="flex items-center justify-between">
              <app-status-pulse tone="success" label="Indexed" />
              <div class="flex items-center gap-1">
                <button class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Search">
                  <app-icon name="search" [size]="14" />
                </button>
                <button class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-white transition" title="Reindex">
                  <app-icon name="refresh-cw" [size]="14" />
                </button>
                <button class="p-1.5 rounded hover:bg-white/5 text-gray-400 hover:text-red-400 transition" title="Delete">
                  <app-icon name="trash-2" [size]="14" />
                </button>
              </div>
            </div>
          </div>
        }
      </div>
    }
  `,
})
export class KnowledgeBaseComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly toastr = inject(ToastrService);

  collections = signal<DocInfo[]>([]);
  uploading = signal(false);
  dragging = signal(false);

  totalChunks = () =>
    this.collections()
      .map((c) => c.count || 0)
      .reduce((a, b) => a + b, 0);

  ngOnInit(): void {
    this.loadCollections();
  }

  loadCollections(): void {
    this.http.get<{ collections: DocInfo[] }>('/api/v1/documents/collections').subscribe({
      next: (res) => this.collections.set(res.collections ?? []),
      error: () => {},
    });
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const files = event.dataTransfer?.files;
    if (files && files.length) this.uploadFiles(files);
  }

  onFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length) this.uploadFiles(input.files);
  }

  private uploadFiles(files: FileList): void {
    this.uploading.set(true);
    const formData = new FormData();
    Array.from(files).forEach((f) => formData.append('files', f));

    this.http.post('/api/v1/documents/upload', formData).subscribe({
      next: () => {
        this.uploading.set(false);
        this.toastr.success(`${files.length} file(s) ingested`, 'Upload complete');
        this.loadCollections();
      },
      error: (err) => {
        this.uploading.set(false);
        this.toastr.error(err?.error?.detail || 'Failed to upload', 'Error');
      },
    });
  }
}
