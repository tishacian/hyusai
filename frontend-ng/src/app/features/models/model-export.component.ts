import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { ModelExportService } from './model-export.service';

@Component({
  selector: 'ck-model-export', standalone: true, changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (canExport()) {
      <section data-testid="model-export">
        <h4>{{ t('title') }}</h4><p>{{ t('hint') }}</p>
        <p>{{ t('data_hint') }}</p>
        <button type="button" [disabled]="!ready() || busy()" (click)="download()">{{ t(busy() ? 'busy' : 'download') }}</button>
        @if (failed()) { <p role="alert">{{ t('failed') }}</p> }
      </section>
    }
  `,
  styles: [`section{padding:12px;border:1px solid var(--ck-stroke-2);border-radius:6px;margin:12px 0;font-size:12px}h4{margin:0 0 8px;font-size:13px}p{color:var(--ck-fg-3);line-height:1.5}button{padding:8px 12px;background:var(--ck-bg-2);color:var(--ck-fg-1);border:1px solid var(--ck-stroke-2);border-radius:4px;cursor:pointer}button:disabled{opacity:.5;cursor:default}[role=alert]{color:var(--ck-signal-neg)}`],
})
export class ModelExportComponent {
  readonly modelId = input.required<string>();
  readonly ready = input(false);
  /** Comes from the server's M1 capabilities, never inferred from a workspace label. */
  readonly canExport = input(false);
  readonly busy = signal(false);
  readonly failed = signal(false);
  private readonly i18n = inject(I18nService);
  private readonly api = inject(ModelExportService);
  private readonly workspace = inject(WorkspaceService);
  private readonly destroyRef = inject(DestroyRef);
  private generation = 0;

  constructor() {
    effect(() => { this.modelId(); this.canExport(); this.reset(); });
    const unregister = this.workspace.registerContextReset(() => this.reset());
    this.destroyRef.onDestroy(() => { this.reset(); unregister(); });
  }
  private reset(): void { this.generation++; this.busy.set(false); this.failed.set(false); }
  t(key: string): string { return this.i18n.t('models.export.' + key); }
  async download(): Promise<void> {
    if (!this.canExport() || !this.ready() || this.busy()) return;
    const generation = this.generation, model = this.modelId();
    this.busy.set(true); this.failed.set(false);
    try {
      const archive = await this.api.download(model);
      if (!archive || generation !== this.generation || model !== this.modelId() || !this.canExport()) return;
      const url = URL.createObjectURL(archive);
      try {
        const anchor = document.createElement('a');
        anchor.href = url; anchor.download = `model-${model.replace(/[^a-zA-Z0-9_-]/g, '')}.zip`;
        anchor.click();
      } finally { URL.revokeObjectURL(url); }
    } catch {
      if (generation === this.generation) this.failed.set(true);
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }
}
