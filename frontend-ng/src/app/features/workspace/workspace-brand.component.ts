import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService, type WorkspaceDetail } from '@app/core/workspace.service';
import { brandAppearance, type BrandAppearance } from '@app/core/brand-appearance';
import { BrandAppearanceEditorComponent } from '@app/shared/brand-appearance-editor.component';

@Component({
  selector: 'app-workspace-brand', standalone: true, imports: [BrandAppearanceEditorComponent],
  template: `
    <section class="ck-surface brand-settings" aria-labelledby="workspace-brand-title">
      <h2 id="workspace-brand-title">{{ i18n.t('workspace.brand.title') }}</h2>
      <p>{{ i18n.t('workspace.brand.description') }}</p>
      <label><input type="checkbox" [checked]="enabled()" [disabled]="!canEdit() || busy()" (change)="enabled.set(!enabled()); dirty.set(true)" /> {{ i18n.t('workspace.brand.enable') }}</label>
      @if (enabled()) {
        <label class="brand-name">{{ i18n.t('workspace.brand.name') }}
          <input type="text" maxlength="120" [value]="label()" [disabled]="!canEdit() || busy()" (input)="label.set(value($event)); dirty.set(true)" />
        </label>
        <app-brand-appearance-editor [name]="label()" [appearance]="appearance()" [disabled]="!canEdit() || busy()" (changed)="appearance.set($event); dirty.set(true)" />
        @if (!valid()) { <p>{{ i18n.t('workspace.brand.required') }}</p> }
      }
      @if (!canEdit()) { <p>{{ i18n.t('workspace.brand.permissions') }}</p> }
      @if (message()) { <p role="status">{{ i18n.t(message()) }}</p> }
      @if (canEdit()) {
        <div class="brand-actions">
          <button type="button" [disabled]="busy() || !dirty() || !valid()" (click)="save()">{{ i18n.t(busy() ? 'workspace.saving' : 'common.save') }}</button>
          <button type="button" [disabled]="busy() || !dirty()" (click)="hydrate()">{{ i18n.t('common.cancel') }}</button>
        </div>
      }
    </section>
  `,
  styles: [`
    :host { display:block; min-width:0; }
    .brand-settings { padding:24px; border-radius:var(--ck-radius-lg); color:var(--ck-fg-1); }
    h2 { font-size:18px; font-weight:600; } p { color:var(--ck-fg-3); margin:8px 0 16px; }
    .brand-name { display:flex; flex-direction:column; gap:6px; margin:20px 0; }
    input[type=text],button { background:var(--ck-bg-panel); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-3); border-radius:var(--ck-radius-md); padding:10px; }
    .brand-actions { display:flex; gap:12px; margin-top:20px; } button:first-child { background:var(--ck-cta-bg); color:var(--ck-cta-fg); } button:disabled { opacity:.5; }
    :is(input,button):focus-visible { outline:2px solid var(--ck-signal-cool); outline-offset:3px; }
  `],
})
export class WorkspaceBrandComponent {
  readonly i18n = inject(I18nService);
  private readonly service = inject(WorkspaceService);
  readonly workspace = input.required<WorkspaceDetail>();
  readonly canEdit = input(false);
  readonly saved = output<WorkspaceDetail>();
  readonly enabled = signal(false);
  readonly label = signal('');
  readonly appearance = signal<BrandAppearance>({});
  readonly dirty = signal(false);
  readonly busy = signal(false);
  readonly message = signal('');
  readonly valid = computed(() => !this.enabled() || (!!this.label().trim() && !!this.appearance().logo));
  private expected: Record<string, unknown> | null = null;
  private loadedId = '';
  constructor() {
    effect(() => {
      const current = this.workspace();
      if (current.id !== this.loadedId) { this.loadedId = current.id; this.hydrate(); }
    });
  }
  value(event: Event): string { return (event.target as HTMLInputElement).value; }
  hydrate(): void {
    const raw = this.workspace().settings?.['platform_brand'];
    this.expected = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : null;
    const brand = this.expected ?? {};
    this.enabled.set(!!this.expected);
    this.label.set(String(brand['label'] ?? this.workspace().name));
    this.appearance.set(brandAppearance({ ...brandAppearance(brand['appearance']), logo: brand['emblem'], logo_light: brand['emblem_light'] }));
    this.dirty.set(false); this.message.set(''); this.busy.set(false);
  }
  save(): void {
    if (!this.canEdit() || !this.dirty() || this.busy() || !this.valid()) return;
    const current = this.workspace();
    const { logo, logo_light, ...appearance } = this.appearance();
    const brand = this.enabled() ? {
      label: this.label().trim(), emblem: logo!, ...(logo_light ? { emblem_light: logo_light } : {}),
      ...(this.expected?.['home'] ? { home: this.expected['home'] } : {}), appearance,
    } : null;
    this.busy.set(true); this.message.set('');
    this.service.updateWorkspaceBrand(current.slug, brand, this.expected).subscribe({
      next: result => {
        if (this.workspace().id !== current.id) return;
        this.expected = result.settings?.['platform_brand'] as Record<string, unknown> ?? null;
        this.busy.set(false); this.dirty.set(false); this.message.set('workspace.brand.saved'); this.saved.emit(result);
      },
      error: err => {
        if (this.workspace().id !== current.id) return;
        this.busy.set(false); this.message.set(err.status === 409 ? 'workspace.brand.conflict' : 'workspace.brand.error');
      },
    });
  }
}
