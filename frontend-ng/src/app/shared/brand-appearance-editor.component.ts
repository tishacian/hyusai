import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { NgStyle } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@app/core/i18n.service';
import { ThemeService } from '@app/core/theme.service';
import { appearanceLogo, appearanceStyles, brandAppearance, BRAND_LOGO_BYTES, type BrandAppearance } from '@app/core/brand-appearance';

@Component({
  selector: 'app-brand-appearance-editor', standalone: true, imports: [NgStyle, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <fieldset [disabled]="disabled()" class="brand-fields">
      <legend>{{ i18n.t('experience.brand.title') }}</legend>
      <p>{{ i18n.t('experience.brand.hint') }}</p>
      <div class="brand-options">
        <label>{{ i18n.t('experience.brand.palette') }}
          <select [ngModel]="brand().palette || 'agentium'" (ngModelChange)="set('palette', $event)">
            @for (palette of palettes; track palette) { <option [value]="palette">{{ i18n.t('experience.brand.palette.' + palette) }}</option> }
          </select>
        </label>
        <label>{{ i18n.t('experience.brand.accent') }}
          <input type="color" [value]="brand().accent || (previewMode() === 'dark' ? '#00bcd4' : '#0e7490')" (input)="set('accent', value($event))" />
        </label>
        <label>{{ i18n.t('experience.brand.corners') }}
          <select [ngModel]="brand().corners || 'soft'" (ngModelChange)="set('corners', $event)">
            @for (corner of corners; track corner) { <option [value]="corner">{{ i18n.t('experience.brand.corners.' + corner) }}</option> }
          </select>
        </label>
        @for (field of logoFields; track field) {
          <label>{{ i18n.t('experience.brand.' + field) }}
            <input type="file" accept="image/png,image/jpeg,image/webp" (change)="upload(field, $event)" />
            @if (brand()[field]) { <button type="button" (click)="set(field, '')">{{ i18n.t('experience.brand.remove_logo') }}</button> }
          </label>
        }
      </div>
      <small>{{ i18n.t('experience.brand.logo_hint') }}</small>
      @if (error()) { <p role="alert">{{ i18n.t(error()) }}</p> }
      <button type="button" (click)="resetStyle()">{{ i18n.t('experience.brand.reset') }}</button>
    </fieldset>
    <div class="brand-preview-region">
    <div class="brand-preview-controls">
      <strong>{{ i18n.t('experience.brand.preview') }}</strong>
      <label>{{ i18n.t('experience.brand.preview_mode') }}
        <select [value]="previewMode()" (change)="previewMode.set(value($event))">
          <option value="light">{{ i18n.t('experience.wizard.access.theme.light') }}</option>
          <option value="dark">{{ i18n.t('experience.wizard.access.theme.dark') }}</option>
        </select>
      </label>
    </div>
    <section data-brand-scope class="brand-preview" [attr.data-theme]="previewMode()" [ngStyle]="styles()" [attr.aria-label]="i18n.t('experience.brand.preview')">
      <header>@if (logo()) { <img [src]="logo()" alt="" /> } <strong>{{ name() || i18n.t('experience.brand.sample_name') }}</strong></header>
      <article><h3>{{ i18n.t('experience.brand.sample_title') }}</h3><p>{{ i18n.t('experience.brand.sample_description') }}</p>
        <span class="brand-status">{{ i18n.t('experience.brand.sample_status') }}</span>
        <button type="button">{{ i18n.t('experience.brand.sample_action') }}</button>
      </article>
    </section>
    </div>
  `,
  styles: [`
    :host { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr)); align-items:start; gap:20px; min-width:0; }
    fieldset { border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); padding:16px; margin:0; }
    legend, strong { font-weight:600; } p,small { color:var(--ck-fg-3); } p { margin:8px 0 16px; }
    .brand-options { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr)); gap:16px; }
    label { display:flex; flex-direction:column; gap:6px; min-width:0; }
    input,select,button { font:inherit; max-width:100%; background:var(--ck-bg-panel); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-3); border-radius:var(--ck-radius-sm); padding:8px; }
    input[type=color] { width:100%; height:40px; padding:3px; } input[type=file] { width:100%; font-size:12px; }
    button { cursor:pointer; } button:disabled { cursor:default; opacity:.5; }
    :is(input,select,button):focus-visible { outline:2px solid var(--ck-signal-cool); outline-offset:3px; }
    small { display:block; margin:12px 0; } [role=alert] { color:var(--ck-status-neg-fg); }
    .brand-preview-region { min-width:0; }
    .brand-preview-controls { display:flex; flex-wrap:wrap; align-items:center; gap:16px; justify-content:space-between; margin:20px 0 10px; }
    .brand-preview-controls label { flex-direction:row; align-items:center; }
    .brand-preview { padding:20px; background:var(--ck-bg-base); color:var(--ck-fg-1); border:1px solid var(--ck-stroke-3); border-radius:var(--ck-radius-xl); }
    .brand-preview header { display:flex; gap:12px; align-items:center; min-height:40px; margin-bottom:20px; }
    .brand-preview img { max-width:120px; max-height:40px; object-fit:contain; }
    .brand-preview article { background:var(--ck-bg-panel); border:1px solid var(--ck-stroke-2); border-radius:var(--ck-radius-lg); padding:20px; }
    .brand-preview h3 { margin:0; font-size:18px; } .brand-preview button { background:var(--ck-cta-bg); color:var(--ck-cta-fg); border:0; margin-top:16px; display:block; }
    .brand-status { background:var(--ck-status-info-bg); color:var(--ck-status-info-fg); border:1px solid var(--ck-status-info-line); padding:4px 8px; border-radius:var(--ck-radius-sm); font-size:12px; }
  `],
})
export class BrandAppearanceEditorComponent {
  readonly i18n = inject(I18nService);
  readonly appearance = input<unknown>({});
  readonly name = input('');
  readonly disabled = input(false);
  readonly changed = output<BrandAppearance>();
  readonly brand = computed(() => brandAppearance(this.appearance()));
  readonly previewMode = signal<string>(inject(ThemeService).resolved());
  readonly styles = computed(() => appearanceStyles({ corners: 'soft', ...this.brand() }, this.previewMode()));
  readonly logo = computed(() => appearanceLogo(this.brand(), this.previewMode()));
  readonly error = signal('');
  readonly palettes = ['agentium', 'graphite', 'sand'];
  readonly corners = ['square', 'soft', 'round'];
  readonly logoFields = ['logo', 'logo_light'] as const;
  value(event: Event): string { return (event.target as HTMLInputElement).value; }
  set(key: keyof BrandAppearance, value: string): void {
    if (this.disabled()) return;
    const next = { ...this.brand(), [key]: value };
    if (!value) delete next[key];
    this.changed.emit(brandAppearance(next));
  }
  resetStyle(): void {
    if (this.disabled()) return;
    const { logo, logo_light } = this.brand();
    this.changed.emit(brandAppearance({ logo, logo_light }));
  }
  async upload(key: 'logo' | 'logo_light', event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    this.error.set('');
    if (!file || this.disabled()) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > BRAND_LOGO_BYTES) {
      this.error.set('experience.brand.logo_error'); return;
    }
    // Capture the edited value: a delayed file read must not cross workspace/app navigation.
    const before = this.appearance();
    const reader = new FileReader();
    reader.onload = () => { if (before === this.appearance()) this.set(key, String(reader.result)); };
    reader.onerror = () => this.error.set('experience.brand.logo_error');
    reader.readAsDataURL(file);
  }
}
