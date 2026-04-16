import { Component, inject, signal, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';

interface DocInfo {
  collection: string;
  count: number;
}

@Component({
  selector: 'app-knowledge-base',
  standalone: true,
  template: `
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Knowledge Base</h1>
    </div>

    <!-- Upload zone -->
    <div
      class="border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-xl p-8 text-center mb-6 hover:border-brand-400 transition cursor-pointer"
      (dragover)="$event.preventDefault()"
      (drop)="onDrop($event)"
      (click)="fileInput.click()"
    >
      <input #fileInput type="file" multiple class="hidden" (change)="onFileSelect($event)" accept=".pdf,.txt,.md,.docx" />
      <p class="text-gray-500 dark:text-gray-400">Drag & drop files here or click to browse</p>
      <p class="text-xs text-gray-400 mt-1">PDF, TXT, MD, DOCX</p>
    </div>

    @if (uploading()) {
      <div class="mb-4 p-3 bg-brand-50 dark:bg-brand-900/20 rounded-lg text-sm text-brand-700 dark:text-brand-300">
        Uploading...
      </div>
    }

    <!-- Collections list -->
    <div class="space-y-3">
      @for (doc of collections(); track doc.collection) {
        <div class="flex items-center justify-between p-4 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
          <div>
            <h3 class="font-medium text-gray-900 dark:text-white">{{ doc.collection }}</h3>
            <p class="text-xs text-gray-500">{{ doc.count }} chunks indexed</p>
          </div>
          <span class="px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs rounded-full">Indexed</span>
        </div>
      } @empty {
        <p class="text-center text-gray-400 py-8">No documents uploaded yet</p>
      }
    </div>
  `,
})
export class KnowledgeBaseComponent implements OnInit {
  private readonly http = inject(HttpClient);
  collections = signal<DocInfo[]>([]);
  uploading = signal(false);

  ngOnInit(): void {
    this.loadCollections();
  }

  loadCollections(): void {
    this.http.get<{ collections: DocInfo[] }>('/api/v1/documents/collections').subscribe({
      next: (res) => this.collections.set(res.collections ?? []),
      error: () => {},
    });
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    const files = event.dataTransfer?.files;
    if (files) this.uploadFiles(files);
  }

  onFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files) this.uploadFiles(input.files);
  }

  private uploadFiles(files: FileList): void {
    this.uploading.set(true);
    const formData = new FormData();
    Array.from(files).forEach((f) => formData.append('files', f));

    this.http.post('/api/v1/documents/upload', formData).subscribe({
      next: () => {
        this.uploading.set(false);
        this.loadCollections();
      },
      error: () => this.uploading.set(false),
    });
  }
}
