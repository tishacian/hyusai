import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { navigationLeafUrl } from '@app/core/navigation.catalog';
import { WorkspaceService } from '@app/core/workspace.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StartApiService, type SystemExample, type SystemImportPreview } from './start-api.service';
import { exampleImportFailure, type ExampleImportFailure } from './start.model';

type ListState = 'loading' | 'ready' | 'error';
type PreviewState = 'idle' | 'loading' | 'ready' | 'error';

/**
 * "Start from an example" (plan lot 4, US09): the creator picks an example,
 * reads its provenance, objects and dependencies, then imports it on purpose
 * into a new draft System of their own. Nothing is created before the button.
 */
@Component({
  selector: 'app-start-example-import',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <section class="example" aria-labelledby="example-title" data-testid="start-example">
      <h3 id="example-title">{{ i18n.t('experience.start.example.title') }}</h3>
      @switch (listState()) {
        @case ('loading') {
          <p class="muted" role="status">{{ i18n.t('experience.start.example.loading') }}</p>
        }
        @case ('error') {
          <div class="notice ck-tone-neg" role="alert" data-testid="start-example-list-error">
            <p>{{ i18n.t('experience.start.example.list_error') }}</p>
            <button type="button" class="ck-btn ck-btn-quiet ck-btn--sm" (click)="load()">{{ i18n.t('common.retry') }}</button>
          </div>
        }
        @case ('ready') {
          @if (examples().length === 0) {
            <p class="muted" data-testid="start-example-empty">{{ i18n.t('experience.start.example.none') }}</p>
          } @else {
            <fieldset>
              <legend class="muted">{{ i18n.t('experience.start.example.pick') }}</legend>
              @for (example of examples(); track example.id) {
                <label class="choice">
                  <input
                    type="radio"
                    name="start-example"
                    [value]="example.id"
                    [checked]="selected()?.id === example.id"
                    (change)="select(example)"
                    [attr.data-testid]="'start-example-' + example.id"
                  />
                  <span>
                    <strong>{{ example.name }}</strong>
                    <small>{{ example.objective }}</small>
                  </span>
                </label>
              }
            </fieldset>
          }
        }
      }

      @if (selected(); as example) {
        <dl class="provenance" data-testid="start-example-provenance">
          <dt>{{ i18n.t('experience.start.example.provenance') }}</dt>
          <dd>{{ i18n.t('experience.start.example.provenance_value', { publisher: example.provenance.publisher, version: example.provenance.version }) }}</dd>
          <dt>{{ i18n.t('experience.start.example.effect') }}</dt>
          <dd>{{ i18n.t('experience.start.example.effect_value') }}</dd>
        </dl>

        @switch (previewState()) {
          @case ('loading') {
            <p class="muted" role="status">{{ i18n.t('experience.start.example.previewing') }}</p>
          }
          @case ('error') {
            <div class="notice ck-tone-neg" role="alert" data-testid="start-example-preview-error">
              <p>{{ i18n.t('experience.start.example.failure.' + (failure() ?? 'failed')) }}</p>
              @if (failure() !== 'refused') {
                <button type="button" class="ck-btn ck-btn-quiet ck-btn--sm" (click)="select(example)">{{ i18n.t('common.retry') }}</button>
              }
            </div>
          }
          @case ('ready') {
            @if (preview(); as p) {
              <div class="preview" data-testid="start-example-preview">
                <h4>{{ i18n.t('experience.start.example.objects') }}</h4>
                <ul>
                  @for (node of p.nodes; track node.id) {
                    <li>{{ node.label || node.id }}@if (node.skill_slug) { <code>{{ node.skill_slug }}</code> }</li>
                  }
                </ul>
                <h4>{{ i18n.t('experience.start.example.dependencies') }}</h4>
                <ul data-testid="start-example-dependencies">
                  @for (slug of p.resolved_skills; track slug) {
                    <li class="dep is-ok"><app-icon name="check-circle" [size]="14" aria-hidden="true" /> <code>{{ slug }}</code> {{ i18n.t('experience.start.example.dep_ok') }}</li>
                  }
                  @for (slug of p.unresolved_skills; track slug) {
                    <li class="dep is-missing" data-testid="start-example-unresolved"><app-icon name="alert-triangle" [size]="14" aria-hidden="true" /> <code>{{ slug }}</code> {{ i18n.t('experience.start.example.dep_missing') }}</li>
                  }
                  <li class="dep">{{ i18n.t('experience.start.example.dep_documents') }}</li>
                </ul>
                @if (!p.valid) {
                  <p class="notice ck-tone-neg" role="alert">{{ i18n.t('experience.start.example.invalid') }}</p>
                }
              </div>
              <div class="actions">
                <button
                  type="button"
                  class="ck-btn ck-cta"
                  [disabled]="importing() || !p.valid"
                  (click)="importSelected()"
                  data-testid="start-example-import"
                >
                  {{ i18n.t(importing() ? 'experience.start.example.importing' : 'experience.start.example.import') }}
                </button>
              </div>
              @if (importFailure(); as kind) {
                <p class="notice ck-tone-neg" role="alert" data-testid="start-example-import-error">
                  {{ i18n.t('experience.start.example.failure.' + kind) }}
                </p>
              }
            }
          }
        }
      }
    </section>
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    h3 { margin: 0 0 var(--ck-space-2); font-size: 15px; font-weight: 600; color: var(--ck-fg-1); }
    h4 { margin: var(--ck-space-3) 0 var(--ck-space-1); font-size: 13px; font-weight: 600; color: var(--ck-fg-1); }
    .muted { margin: 0; font-size: 13px; color: var(--ck-fg-3); }
    fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: var(--ck-space-2); }
    legend { padding: 0; margin-bottom: var(--ck-space-2); }
    .choice { display: flex; gap: var(--ck-space-3); align-items: flex-start; padding: var(--ck-space-3); border: 1px solid var(--ck-stroke-2); border-radius: var(--ck-radius-md); cursor: pointer; }
    .choice:has(input:checked) { border-color: var(--ck-primary); }
    .choice input { margin-top: 3px; }
    .choice input:focus-visible { outline: 2px solid var(--ck-primary); outline-offset: 2px; }
    .choice span { display: grid; gap: var(--ck-space-1); min-width: 0; }
    .choice strong { font-size: 14px; color: var(--ck-fg-1); }
    .choice small { font-size: 13px; color: var(--ck-fg-2); line-height: 1.5; }
    .provenance { display: grid; grid-template-columns: max-content 1fr; gap: var(--ck-space-1) var(--ck-space-3); margin: var(--ck-space-4) 0 0; font-size: 13px; }
    .provenance dt { color: var(--ck-fg-3); }
    .provenance dd { margin: 0; color: var(--ck-fg-1); }
    .preview ul { margin: 0; padding-left: var(--ck-space-6); font-size: 13px; color: var(--ck-fg-2); line-height: 1.7; }
    .preview code { font-family: var(--ck-font-mono); font-size: 12px; margin-left: var(--ck-space-1); }
    .dep.is-ok { color: var(--ck-status-ok-fg); }
    .dep.is-missing { color: var(--ck-status-warn-fg); }
    .actions { margin-top: var(--ck-space-4); }
    .notice { display: flex; flex-wrap: wrap; gap: var(--ck-space-2); align-items: center; margin: var(--ck-space-3) 0 0; padding: var(--ck-space-2) var(--ck-space-3); border-radius: var(--ck-radius-md); font-size: 13px; }
    .notice p { margin: 0; flex: 1 1 220px; }
    @media (max-width: 480px) { .provenance { grid-template-columns: 1fr; } }
  `],
})
export class StartExampleImportComponent {
  readonly i18n = inject(I18nService);
  private readonly api = inject(StartApiService);
  private readonly workspace = inject(WorkspaceService);
  private readonly router = inject(Router);

  readonly listState = signal<ListState>('loading');
  readonly examples = signal<SystemExample[]>([]);
  readonly selected = signal<SystemExample | null>(null);
  readonly previewState = signal<PreviewState>('idle');
  readonly preview = signal<SystemImportPreview | null>(null);
  readonly failure = signal<ExampleImportFailure | null>(null);
  readonly importing = signal(false);
  readonly importFailure = signal<ExampleImportFailure | null>(null);

  constructor() {
    this.load();
  }

  load(): void {
    const scope = this.workspace.captureRequestScope();
    this.listState.set('loading');
    this.api.examples(scope.workspaceSlug).subscribe({
      next: (rows) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.examples.set(rows);
        this.listState.set('ready');
      },
      error: () => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.listState.set('error');
      },
    });
  }

  select(example: SystemExample): void {
    const scope = this.workspace.captureRequestScope();
    this.selected.set(example);
    this.preview.set(null);
    this.failure.set(null);
    this.importFailure.set(null);
    this.previewState.set('loading');
    this.api.preview(example.envelope, scope.workspaceSlug).subscribe({
      next: (preview) => {
        if (!this.workspace.isRequestScopeCurrent(scope) || this.selected()?.id !== example.id) return;
        this.preview.set(preview);
        this.previewState.set('ready');
      },
      error: (error: unknown) => {
        if (!this.workspace.isRequestScopeCurrent(scope) || this.selected()?.id !== example.id) return;
        this.failure.set(exampleImportFailure(error));
        this.previewState.set('error');
      },
    });
  }

  importSelected(): void {
    const example = this.selected();
    if (!example || this.importing() || this.previewState() !== 'ready') return;
    const scope = this.workspace.captureRequestScope();
    this.importing.set(true);
    this.importFailure.set(null);
    this.api.importEnvelope(example.envelope, scope.workspaceSlug).subscribe({
      next: (system) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.importing.set(false);
        if (!system?.id) {
          this.importFailure.set('unverifiable');
          return;
        }
        void this.router.navigateByUrl(navigationLeafUrl('system-flow', { ref: system.id }));
      },
      error: (error: unknown) => {
        if (!this.workspace.isRequestScopeCurrent(scope)) return;
        this.importing.set(false);
        this.importFailure.set(exampleImportFailure(error));
      },
    });
  }
}
