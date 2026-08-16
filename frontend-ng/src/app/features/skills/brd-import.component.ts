/**
 * `<app-brd-import>` — read a Business Requirements document into drafts.
 *
 * The document is parsed server-side and nothing else happens: the rows it
 * yields are material for the authoring wizard, never Skills created behind
 * the author's back. A document the parser cannot read is not a dead end
 * either — the screen says what went wrong and the wizard is still one click
 * away, empty.
 *
 * What lands here is the traceability chain the template makes explicit:
 * business outcomes, functional requirements with their priority and the
 * capability they map to, the decisions the agent makes, and the rules and
 * prohibitions that bound them. A requirement or a decision is the natural
 * seed for one Skill, so those two carry the draft button.
 */
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Output,
  inject,
  signal,
} from '@angular/core';
import { A11yModule } from '@angular/cdk/a11y';
import { CanonicalApiService, type BrdImport } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { GlyphComponent } from '@app/shared/cockpit';
import { backendMessage, type SkillDraftSeed } from './new-skill-dialog.component';

@Component({
  selector: 'app-brd-import',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, GlyphComponent],
  template: `
    <div class="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-auto">
      <div class="absolute inset-0" style="background:var(--ck-scrim);" (click)="dismiss()"></div>
      <div
        class="relative ck-surface rounded-md"
        role="dialog"
        aria-modal="true"
        aria-labelledby="brd-import-title"
        cdkTrapFocus
        [cdkTrapFocusAutoCapture]="true"
        style="width:100%; max-width:820px; padding:24px 28px; border:1px solid var(--ck-stroke-strong);"
      >
        <div class="flex items-start justify-between gap-4" style="margin-bottom:14px;">
          <div>
            <div class="ck-mono flex items-center gap-2" [style]="eyebrowStyle">
              <ck-glyph name="ledger" [size]="12" />
              {{ i18n.t('skills.list.import') }}
            </div>
            <h2 id="brd-import-title" class="text-lg font-medium" style="color:var(--ck-fg-1); margin-top:6px;">
              {{ i18n.t('skills.import.title') }}
            </h2>
            <p class="ck-mono" style="font-size:10px; color:var(--ck-fg-4); margin-top:4px; max-width:60ch;">
              {{ i18n.t('skills.import.description') }}
            </p>
          </div>
          <button type="button" (click)="dismiss()" class="ck-mono" [style]="ghostStyle">
            {{ i18n.t('skills.import.close') }}
          </button>
        </div>

        <button
          type="button"
          class="ck-mono inline-flex items-center"
          [style]="ghostStyle"
          (click)="fileInput.click()"
        >
          {{ i18n.t('skills.import.pick') }}
        </button>
        <input
          #fileInput
          class="sr-only"
          type="file"
          accept=".docx"
          [attr.aria-label]="i18n.t('skills.import.pick')"
          (change)="pick($event)"
        />

        @if (loading()) {
          <p class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.import.parsing') }}</p>
        }
        @if (failure(); as reason) {
          <p class="ck-mono" role="alert" style="font-size:10px; color:var(--ck-neg); margin-top:12px;">
            {{ i18n.t('skills.import.failed', { reason }) }}
          </p>
        }

        @if (result(); as parsed) {
          @if (!rowCount(parsed)) {
            <p class="ck-mono" [style]="noteStyle">{{ i18n.t('skills.import.empty') }}</p>
          }
          @for (problem of parsed.problems; track problem) {
            <p class="ck-mono" style="font-size:10px; color:var(--ck-warn); margin-top:8px;">{{ problem }}</p>
          }

          @if (parsed.context.length) {
            <section style="margin-top:18px;">
              <span class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.import.context') }}</span>
              @for (entry of parsed.context; track entry.label) {
                <div class="flex items-start justify-between" style="gap:16px; padding:4px 0;">
                  <span class="ck-mono" [style]="noteStyle">{{ entry.label }}</span>
                  <span style="font-size:11px; color:var(--ck-fg-2); text-align:right;">{{ entry.value }}</span>
                </div>
              }
            </section>
          }

          @if (parsed.outcomes.length) {
            <section style="margin-top:18px;">
              <span class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.import.outcomes') }}</span>
              @for (row of parsed.outcomes; track row.id) {
                <div [style]="rowStyle">
                  <span class="ck-mono" [style]="refStyle">{{ row.id }}</span>
                  <span style="font-size:11px; color:var(--ck-fg-1);">{{ row.outcome }}</span>
                  <span class="ck-mono" [style]="noteStyle">{{ row.signal }}</span>
                </div>
              }
            </section>
          }

          @if (parsed.requirements.length) {
            <section style="margin-top:18px;">
              <span class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.import.requirements') }}</span>
              @for (row of parsed.requirements; track row.id) {
                <div [style]="rowStyle">
                  <span class="ck-mono" [style]="refStyle">{{ row.id }}</span>
                  <div class="min-w-0" style="flex:1 1 auto;">
                    <div style="font-size:11px; color:var(--ck-fg-1);">{{ row.requirement }}</div>
                    <div class="ck-mono" [style]="noteStyle">
                      {{ i18n.t('skills.import.column.priority') }}: {{ row.priority || '—' }}
                      ·
                      {{ i18n.t('skills.import.column.capability') }}: {{ row.capability || '—' }}
                    </div>
                  </div>
                  <button type="button" class="ck-mono" [style]="ghostStyle" (click)="draft(row.id, row.requirement)">
                    {{ i18n.t('skills.import.draft') }}
                  </button>
                </div>
              }
            </section>
          }

          @if (parsed.decisions.length) {
            <section style="margin-top:18px;">
              <span class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.import.decisions') }}</span>
              @for (row of parsed.decisions; track row.id) {
                <div [style]="rowStyle">
                  <span class="ck-mono" [style]="refStyle">{{ row.id }}</span>
                  <div class="min-w-0" style="flex:1 1 auto;">
                    <div style="font-size:11px; color:var(--ck-fg-1);">{{ row.decision }}</div>
                    <div class="ck-mono" [style]="noteStyle">{{ row.inputs }}</div>
                  </div>
                  <button type="button" class="ck-mono" [style]="ghostStyle" (click)="draft(row.id, row.decision)">
                    {{ i18n.t('skills.import.draft') }}
                  </button>
                </div>
              }
            </section>
          }

          @if (parsed.guardrails.length) {
            <section style="margin-top:18px;">
              <span class="ck-mono" [style]="sectionStyle">{{ i18n.t('skills.import.guardrails') }}</span>
              @for (row of parsed.guardrails; track row.id) {
                <div [style]="rowStyle">
                  <span class="ck-mono" [style]="refStyle">{{ row.id }}</span>
                  <span style="font-size:11px; color:var(--ck-fg-2);">{{ row.text }}</span>
                </div>
              }
            </section>
          }

          <p class="ck-mono" [style]="noteStyle" style="margin-top:18px;">
            {{ i18n.t('skills.import.ignored') }}
          </p>
        }
      </div>
    </div>
  `,
})
export class BrdImportComponent {
  private readonly canonical = inject(CanonicalApiService);
  readonly i18n = inject(I18nService);

  @Output() readonly drafted = new EventEmitter<SkillDraftSeed>();
  @Output() readonly dismissed = new EventEmitter<void>();

  readonly loading = signal(false);
  readonly result = signal<BrdImport | null>(null);
  readonly failure = signal<string | null>(null);
  private readonly previousFocus = typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;

  protected readonly eyebrowStyle =
    'font-size:10px; letter-spacing:0.16em; text-transform:uppercase; color:var(--ck-fg-4);';
  protected readonly sectionStyle =
    'display:block; font-size:9px; letter-spacing:0.16em; text-transform:uppercase;'
    + ' color:var(--ck-fg-4); margin-bottom:6px;';
  protected readonly noteStyle = 'font-size:10px; color:var(--ck-fg-4); line-height:1.5;';
  protected readonly refStyle =
    'font-size:10px; color:var(--ck-fg-3); min-width:44px; letter-spacing:0.08em;';
  protected readonly rowStyle =
    'display:flex; align-items:flex-start; gap:12px; padding:8px 0;'
    + ' border-top:1px solid var(--ck-hair, var(--ck-stroke-soft));';
  protected readonly ghostStyle =
    'padding:6px 10px; border-radius:4px; font-size:10px; letter-spacing:0.14em;'
    + ' text-transform:uppercase; background:var(--ck-bg-inset); color:var(--ck-fg-3);'
    + ' border:1px solid var(--ck-stroke-soft);';

  rowCount(parsed: BrdImport): number {
    return (
      parsed.outcomes.length
      + parsed.requirements.length
      + parsed.decisions.length
      + parsed.guardrails.length
      + parsed.context.length
    );
  }

  pick(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.loading.set(true);
    this.failure.set(null);
    this.result.set(null);
    this.canonical.importBusinessRequirements(file).subscribe({
      next: (parsed) => {
        this.loading.set(false);
        this.result.set(parsed);
      },
      error: (error: unknown) => {
        this.loading.set(false);
        this.failure.set(backendMessage(error, 'unreadable'));
      },
    });
  }

  draft(id: string, text: string): void {
    const trimmed = text.trim();
    this.drafted.emit({
      localName: localNameFrom(id, trimmed),
      name: trimmed.slice(0, 200),
      description: trimmed,
    });
  }

  dismiss(): void {
    this.dismissed.emit();
    queueMicrotask(() => {
      if (this.previousFocus?.isConnected) this.previousFocus.focus();
    });
  }

  @HostListener('document:keydown.escape', ['$event'])
  onEscape(event: Event): void {
    event.preventDefault();
    this.dismiss();
  }
}

/**
 * A slug candidate the server will accept: the requirement reference keeps the
 * trace back to the document, the first words keep it readable.
 */
export function localNameFrom(id: string, text: string): string {
  const words = text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)
    .slice(0, 4)
    .join('_');
  const reference = id.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return [reference, words].filter(Boolean).join('_') || 'imported_requirement';
}
