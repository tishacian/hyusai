import { CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { forkJoin } from 'rxjs';
import { IconComponent } from '@app/shared/ui/icon.component';
import { I18nService } from '@app/core/i18n.service';

interface DepositFile {
  id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  status: 'received' | 'rejected' | 'promoted';
  uploaded_at: string | null;
}

interface DepositLink {
  label: string;
  access_id: string;
  status: string;
  expires_at: string | null;
  max_file_size_mb: number;
  allowed_extensions: string[];
}

@Component({
  selector: 'app-deposit-portal',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="min-h-screen" style="background:var(--ck-bg-base);color:var(--ck-fg-1)">
      <div class="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-5 py-6">
        <header class="flex items-center justify-between border-b border-white/10 pb-5">
          <div class="flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center rounded-md bg-cyan-400/10 text-cyan-300 ring-1 ring-cyan-400/30">
              <app-icon name="inbox" [size]="21" />
            </div>
            <div>
              <p class="font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-300">{{ i18n.t('deposit.portal.eyebrow') }}</p>
              <h1 class="mt-1 text-xl font-semibold tracking-normal text-white">{{ link()?.label || i18n.t('deposit.portal.title_fallback') }}</h1>
            </div>
          </div>
          @if (link(); as meta) {
            <span class="rounded bg-white/5 px-2.5 py-1 text-xs text-gray-300 ring-1 ring-white/10">
              {{ linkStatusLabel(meta.status) }}
            </span>
          }
        </header>

        @if (!token()) {
          <section class="mx-auto mt-16 w-full max-w-md rounded-md bg-[#111827] p-6 ring-1 ring-white/10">
            <p class="font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-300">{{ i18n.t('deposit.portal.access_required') }}</p>
            <h2 class="mt-2 text-lg font-semibold text-white">{{ i18n.t('deposit.portal.password_prompt') }}</h2>
            <form class="mt-5 space-y-4" (ngSubmit)="unlock()">
              <label class="block">
                <span class="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-gray-400">{{ i18n.t('deposit.portal.password') }}</span>
                <input
                  name="password"
                  type="password"
                  [(ngModel)]="password"
                  class="w-full rounded-md border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white outline-none transition focus:border-cyan-400/50 focus:ring-2 focus:ring-cyan-400/40"
                  autocomplete="current-password"
                />
              </label>
              @if (error()) {
                <p class="rounded bg-red-500/10 px-3 py-2 text-sm text-red-100 ring-1 ring-red-400/25">{{ error() }}</p>
              }
              <button
                type="submit"
                class="inline-flex w-full items-center justify-center gap-2 rounded-md bg-cyan-500 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
                [disabled]="authenticating() || !password"
              >
                <app-icon name="unlock" [size]="16" />
                {{ authenticating() ? i18n.t('deposit.portal.opening') : i18n.t('deposit.portal.open') }}
              </button>
            </form>
          </section>
        } @else {
          <section class="grid flex-1 grid-cols-1 gap-5 py-6 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div class="space-y-5">
              <div
                class="rounded-md border border-dashed p-8 text-center transition"
                [class.border-cyan-400]="dragging()"
                [class.bg-cyan-400\\/10]="dragging()"
                [class.border-white\\/15]="!dragging()"
                [class.bg-white\\/[0.03]]="!dragging()"
                (dragover)="onDragOver($event)"
                (dragleave)="onDragLeave($event)"
                (drop)="onDrop($event)"
              >
                <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-md bg-cyan-400/10 text-cyan-300 ring-1 ring-cyan-400/30">
                  <app-icon name="upload-cloud" [size]="26" />
                </div>
                <h2 class="mt-4 text-lg font-semibold">{{ i18n.t('deposit.portal.drop.title') }}</h2>
                <p class="mt-1 text-sm text-gray-400">{{ i18n.t('deposit.portal.drop.hint') }}</p>
                <input #fileInput type="file" multiple class="hidden" (change)="onFileInput($event)" />
                <button
                  type="button"
                  class="mt-5 inline-flex items-center gap-2 rounded-md bg-white/5 px-4 py-2 text-sm font-semibold text-gray-100 ring-1 ring-white/10 transition hover:bg-white/10"
                  (click)="fileInput.click()"
                >
                  <app-icon name="file-up" [size]="16" />
                  {{ i18n.t('deposit.portal.drop.select') }}
                </button>
                @if (selectedFiles().length) {
                  <div class="mt-5 rounded-md bg-black/25 p-3 text-left ring-1 ring-white/10">
                    <p class="text-xs text-gray-400">{{ i18n.t('deposit.portal.drop.ready', { count: selectedFiles().length }) }}</p>
                    <button
                      type="button"
                      class="mt-3 inline-flex items-center gap-2 rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
                      (click)="uploadSelected()"
                      [disabled]="uploading()"
                    >
                      <app-icon name="upload" [size]="15" />
                      {{ uploading() ? i18n.t('deposit.portal.uploading') : i18n.t('deposit.portal.upload') }}
                    </button>
                  </div>
                }
              </div>

              <section class="rounded-md bg-[#111827] ring-1 ring-white/10">
                <div class="flex items-center justify-between border-b border-white/10 px-4 py-3">
                  <h2 class="text-sm font-semibold">{{ i18n.t('deposit.portal.files.title') }}</h2>
                  <button type="button" class="text-xs text-cyan-300 hover:text-cyan-100" (click)="loadFiles()">{{ i18n.t('common.refresh') }}</button>
                </div>
                @if (files().length === 0) {
                  <div class="px-4 py-10 text-center text-sm text-gray-500">{{ i18n.t('deposit.portal.files.empty') }}</div>
                } @else {
                  <ul class="divide-y divide-white/10">
                    @for (file of files(); track file.id) {
                      <li class="grid grid-cols-[minmax(0,1fr)_110px_92px] gap-3 px-4 py-3 text-sm">
                        <div class="min-w-0">
                          <div class="truncate font-medium text-white">{{ file.filename }}</div>
                          <div class="mt-1 truncate font-mono text-[10px] text-gray-500">{{ file.sha256 }}</div>
                        </div>
                        <div class="text-right text-xs text-gray-400">{{ formatBytes(file.size_bytes) }}</div>
                        <div class="text-right">
                          <span class="rounded bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200 ring-1 ring-emerald-500/20">
                            {{ fileStatusLabel(file.status) }}
                          </span>
                        </div>
                      </li>
                    }
                  </ul>
                }
              </section>
            </div>

            <aside class="space-y-4">
              <section class="rounded-md bg-[#111827] p-4 ring-1 ring-cyan-400/30">
                <p class="font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-300">{{ i18n.t('deposit.portal.scope') }}</p>
                <h2 class="mt-2 text-base font-semibold">{{ link()?.label || accessId() }}</h2>
                <dl class="mt-4 space-y-3 text-sm">
                  <div class="flex justify-between gap-3">
                    <dt class="text-gray-500">{{ i18n.t('deposit.portal.max_file') }}</dt>
                    <dd class="text-gray-200">{{ link()?.max_file_size_mb || 100 }} MB</dd>
                  </div>
                  <div class="flex justify-between gap-3">
                    <dt class="text-gray-500">{{ i18n.t('deposit.portal.expires') }}</dt>
                    <dd class="text-gray-200">{{ link()?.expires_at ? (link()!.expires_at | date:'mediumDate') : i18n.t('deposit.portal.no_expiry') }}</dd>
                  </div>
                </dl>
              </section>
              @if (error()) {
                <p class="rounded bg-red-500/10 px-3 py-2 text-sm text-red-100 ring-1 ring-red-400/25">{{ error() }}</p>
              }
            </aside>
          </section>
        }
      </div>
    </main>
  `,
})
export class DepositPortalComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly http = inject(HttpClient);
  readonly i18n = inject(I18nService);

  readonly accessId = signal('');
  readonly token = signal<string | null>(null);
  readonly link = signal<DepositLink | null>(null);
  readonly files = signal<DepositFile[]>([]);
  readonly selectedFiles = signal<File[]>([]);
  readonly authenticating = signal(false);
  readonly uploading = signal(false);
  readonly dragging = signal(false);
  readonly error = signal<string | null>(null);
  readonly storageKey = computed(() => `deposit:${this.accessId()}:token`);

  password = '';

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('accessId') || '';
    this.accessId.set(id);
    const saved = sessionStorage.getItem(this.storageKey());
    if (saved) {
      this.token.set(saved);
      this.loadFiles();
    }
  }

  unlock(): void {
    this.authenticating.set(true);
    this.error.set(null);
    this.http
      .post<{ token: string; link: DepositLink; files: DepositFile[] }>(
        `/api/v1/deposit-links/${this.accessId()}/session`,
        { password: this.password },
      )
      .subscribe({
        next: (res) => {
          this.token.set(res.token);
          sessionStorage.setItem(this.storageKey(), res.token);
          this.link.set(res.link);
          this.files.set(res.files || []);
          this.password = '';
          this.authenticating.set(false);
        },
        error: (err) => {
          this.error.set(this.errorMessage(err, this.i18n.t('deposit.portal.error.open')));
          this.authenticating.set(false);
        },
      });
  }

  loadFiles(): void {
    const token = this.token();
    if (!token) return;
    this.http
      .get<{ link: DepositLink; files: DepositFile[] }>(`/api/v1/deposit-links/${this.accessId()}/files`, {
        headers: this.authHeaders(token),
      })
      .subscribe({
        next: (res) => {
          this.link.set(res.link);
          this.files.set(res.files || []);
        },
        error: (err) => this.error.set(this.errorMessage(err, this.i18n.t('deposit.portal.error.load_files'))),
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
    if (event.dataTransfer?.files?.length) {
      this.selectedFiles.set(Array.from(event.dataTransfer.files));
    }
  }

  onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) this.selectedFiles.set(Array.from(input.files));
    input.value = '';
  }

  uploadSelected(): void {
    const token = this.token();
    const files = this.selectedFiles();
    if (!token || files.length === 0) return;
    this.uploading.set(true);
    this.error.set(null);
    const requests = files.map((file) => {
      const form = new FormData();
      form.append('file', file, file.name);
      return this.http.post(`/api/v1/deposit-links/${this.accessId()}/files`, form, {
        headers: this.authHeaders(token),
      });
    });
    forkJoin(requests).subscribe({
      next: () => {
        this.selectedFiles.set([]);
        this.uploading.set(false);
        this.loadFiles();
      },
      error: (err) => {
        this.error.set(this.errorMessage(err, this.i18n.t('deposit.portal.error.upload')));
        this.uploading.set(false);
        this.loadFiles();
      },
    });
  }

  /**
   * Translate an API link status, falling back to the raw value when the
   * backend grows a status the dictionary hasn't caught up with — an unknown
   * status must stay visible, not turn into a dotted key.
   */
  linkStatusLabel(status: string): string {
    const key = `deposit.link_status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  /** Same contract as {@link linkStatusLabel}, for deposited-file statuses. */
  fileStatusLabel(status: string): string {
    const key = `deposit.file_status.${status}`;
    const label = this.i18n.t(key);
    return label === key ? status : label;
  }

  formatBytes(size: number): string {
    if (!size) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
    return `${(size / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
  }

  private authHeaders(token: string): HttpHeaders {
    return new HttpHeaders({ Authorization: `Bearer ${token}` });
  }

  private errorMessage(err: unknown, fallback: string): string {
    const detail = (err as { error?: { detail?: unknown; message?: unknown } })?.error?.detail;
    const message = (err as { error?: { message?: unknown } })?.error?.message;
    const value = detail ?? message;
    if (!value) return fallback;
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) {
      return value
        .map((item) => {
          if (typeof item === 'string') return item;
          const entry = item as { loc?: unknown[]; msg?: string };
          const where = Array.isArray(entry.loc) ? entry.loc.join('.') : '';
          return where && entry.msg ? `${where}: ${entry.msg}` : entry.msg || JSON.stringify(item);
        })
        .join(' | ');
    }
    if (typeof value === 'object') {
      const body = value as { message?: string; msg?: string; detail?: string };
      return body.message || body.msg || body.detail || JSON.stringify(value);
    }
    return String(value);
  }
}
