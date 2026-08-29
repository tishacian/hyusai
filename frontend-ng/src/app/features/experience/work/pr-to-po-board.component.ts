import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { CanonicalApiService, type Run, type System } from '@app/core/canonical-api.service';
import { I18nService } from '@app/core/i18n.service';
import { WorkspaceService } from '@app/core/workspace.service';
import { EmptyStateComponent } from '@app/shared/ui/empty-state.component';
import { WorkApiService } from './work-api.service';

const SYSTEM_NAME = 'PR to PO';

@Component({
  selector: 'app-pr-to-po-board',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, EmptyStateComponent],
  styleUrl: './work.scss',
  template: `
    <div class="xp-work" data-theme="light">
      <header class="xp-work-bar">
        <div class="xp-work-brand">
          <p class="xp-work-eyebrow">{{ workspace.current()?.name }}</p>
          <h1>{{ i18n.t('experience.pr_to_po.title') }}</h1>
          <p>{{ i18n.t('experience.pr_to_po.subtitle') }}</p>
        </div>
        <div class="xp-work-hitl-actions">
          <a routerLink="/work" class="xp-work-btn">{{ i18n.t('experience.work.title') }}</a>
          <button type="button" class="xp-work-btn" (click)="load()" [disabled]="loading()">
            {{ i18n.t('experience.pr_to_po.refresh') }}
          </button>
          <button
            type="button"
            class="xp-work-btn xp-work-btn-primary"
            (click)="startRun()"
            [disabled]="!system() || starting()"
          >
            {{ starting() ? i18n.t('experience.pr_to_po.starting') : i18n.t('experience.pr_to_po.start') }}
          </button>
        </div>
      </header>

      <section class="xp-work-main xp-work-hitl">
        @if (error(); as err) {
          <p class="xp-work-error">{{ err }}</p>
        }
        @if (loading()) {
          <app-empty-state icon="sparkles" size="lg" [title]="i18n.t('common.loading')" />
        } @else if (items().length === 0) {
          <app-empty-state
            icon="layers"
            size="lg"
            [title]="i18n.t('experience.pr_to_po.empty')"
            [description]="i18n.t('experience.pr_to_po.subtitle')"
          />
        } @else {
          @for (run of items(); track run.id) {
            <article>
              <h3>{{ i18n.t('experience.pr_to_po.run', { id: shortId(run.id) }) }}</h3>
              <p>{{ run.hitl?.prompt }}</p>
              <dl>
                <dt>{{ i18n.t('experience.pr_to_po.supplier') }}</dt>
                <dd>{{ packageField(run, 'supplier') }}</dd>
                <dt>{{ i18n.t('experience.pr_to_po.format') }}</dt>
                <dd>{{ packageField(run, 'format') }}</dd>
                <dt>{{ i18n.t('experience.pr_to_po.summary') }}</dt>
                <dd>{{ packageField(run, 'justification_summary') }}</dd>
              </dl>
              <details>
                <summary>{{ i18n.t('experience.pr_to_po.package') }}</summary>
                <pre>{{ packageJson(run) }}</pre>
              </details>
              <label>
                <span>{{ i18n.t('experience.pr_to_po.note') }}</span>
                <textarea
                  [value]="notes()[run.id] || ''"
                  (input)="setNote(run.id, $event)"
                ></textarea>
              </label>
              <div class="xp-work-hitl-actions">
                <button type="button" class="xp-work-btn xp-work-btn-primary" (click)="decide(run, 'accept')">
                  {{ i18n.t('experience.pr_to_po.approve') }}
                </button>
                <button type="button" class="xp-work-btn" (click)="decide(run, 'reject')">
                  {{ i18n.t('experience.pr_to_po.reject') }}
                </button>
              </div>
            </article>
          }
        }
      </section>
    </div>
  `,
})
export class PrToPoBoardComponent implements OnInit {
  private readonly canonical = inject(CanonicalApiService);
  private readonly workApi = inject(WorkApiService);
  readonly i18n = inject(I18nService);
  readonly workspace = inject(WorkspaceService);

  readonly loading = signal(false);
  readonly starting = signal(false);
  readonly error = signal<string | null>(null);
  readonly system = signal<System | null>(null);
  readonly items = signal<Run[]>([]);
  readonly notes = signal<Record<string, string>>({});
  readonly systemId = computed(() => this.system()?.id ?? null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.canonical
      .listSystems()
      .pipe(
        switchMap((systems) => {
          const found =
            systems.find((row) => row.settings?.['nawa_pr_to_po'] === true) ||
            systems.find((row) => row.name === SYSTEM_NAME) ||
            null;
          this.system.set(found);
          if (!found?.id) return of([] as Run[]);
          return this.canonical.listRuns({ system_id: found.id, status: 'hitl_pending' });
        }),
        switchMap((runs) => {
          if (!runs.length) return of([] as Run[]);
          return forkJoin(runs.map((run) => this.canonical.getRun(run.id).pipe(map((full) => full || run))));
        }),
        catchError(() => {
          this.error.set(this.i18n.t('experience.pr_to_po.missing'));
          return of([] as Run[]);
        }),
      )
      .subscribe((runs) => {
        this.items.set(runs.filter((run) => run.status === 'hitl_pending'));
        this.loading.set(false);
      });
  }

  startRun(): void {
    const system = this.system();
    const sha = system?.flow_sha256;
    if (!system?.id || !sha) {
      this.error.set(this.i18n.t('experience.pr_to_po.missing'));
      return;
    }
    this.starting.set(true);
    this.canonical
      .triggerRun(system.id, {
        trigger: 'manual',
        input_ref: {},
        expected_flow_sha256: sha,
      })
      .subscribe({
        next: () => {
          this.starting.set(false);
          this.load();
        },
        error: () => {
          this.starting.set(false);
          this.error.set(this.i18n.t('experience.pr_to_po.missing'));
        },
      });
  }

  setNote(runId: string, event: Event): void {
    const value = (event.target as HTMLTextAreaElement).value;
    this.notes.update((current) => ({ ...current, [runId]: value }));
  }

  decide(run: Run, action: 'accept' | 'reject'): void {
    const note = (this.notes()[run.id] || '').trim();
    this.workApi.decide(run.id, action, note).subscribe((updated) => {
      if (!updated) {
        this.error.set(this.i18n.t('experience.work.validations.error'));
        return;
      }
      this.items.update((rows) => rows.filter((item) => item.id !== run.id));
    });
  }

  shortId(id: string): string {
    return id.slice(0, 8);
  }

  packageField(run: Run, key: string): string {
    const upstream = run.hitl?.upstream;
    const value = upstream && typeof upstream === 'object' ? upstream[key] : undefined;
    return value == null ? '—' : typeof value === 'string' ? value : JSON.stringify(value);
  }

  packageJson(run: Run): string {
    return JSON.stringify(run.hitl?.upstream ?? {}, null, 2);
  }
}
