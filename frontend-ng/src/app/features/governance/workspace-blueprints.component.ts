import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '@app/core/api.service';

interface BlueprintReport {
  dry_run: boolean;
  activate_systems: boolean;
  created: Record<string, number>;
  reused: Record<string, number>;
  skipped: Array<Record<string, unknown>>;
  unresolved_skills: string[];
  actions: Array<Record<string, unknown>>;
}

type WorkspaceBlueprint = Record<string, any>;

@Component({
  selector: 'app-workspace-blueprints',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <section class="blueprint-page">
      <header class="page-head">
        <div>
          <p class="eyebrow">Governance · Workspace Blueprint</p>
          <h1>Workspace Blueprints</h1>
          <p class="lead">
            Export and recreate workspace structure, systems, IAM flags and knowledge collection metadata without moving members, secrets, files or vectors.
          </p>
        </div>
        <div class="actions">
          <button type="button" class="ghost" (click)="load()" [disabled]="loading()">Refresh export</button>
          <button type="button" class="ghost" (click)="download()" [disabled]="!blueprint()">Download JSON</button>
          <button type="button" class="primary" (click)="validate()" [disabled]="loading()">Dry run</button>
          <button type="button" class="danger" (click)="apply()" [disabled]="loading() || !canApply()">Apply</button>
        </div>
      </header>

      @if (error()) {
        <div class="error">{{ error() }}</div>
      }
      @if (status()) {
        <div class="notice">{{ status() }}</div>
      }

      <div class="kpi-grid">
        <div class="kpi">
          <span>Systems</span>
          <strong>{{ summary().systems }}</strong>
        </div>
        <div class="kpi">
          <span>Capabilities</span>
          <strong>{{ summary().capabilities }}</strong>
        </div>
        <div class="kpi">
          <span>Contexts</span>
          <strong>{{ summary().contexts }}</strong>
        </div>
        <div class="kpi">
          <span>Collections</span>
          <strong>{{ summary().collections }}</strong>
        </div>
      </div>

      <div class="layout">
        <section class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Portable contract</p>
              <h2>Blueprint JSON</h2>
            </div>
            <span class="badge">{{ blueprint()?.['kind'] || 'not loaded' }}</span>
          </div>
          <textarea
            [(ngModel)]="importText"
            spellcheck="false"
            aria-label="Workspace blueprint JSON"
          ></textarea>
        </section>

        <aside class="side">
          <section class="panel">
            <p class="eyebrow">Data policy</p>
            <h2>Excluded by design</h2>
            <ul>
              <li>Workspace members and Keycloak identities</li>
              <li>Secure Deposit links, passwords and staged files</li>
              <li>Raw Knowledge documents and vector payloads</li>
              <li>Run history and audit evidence</li>
            </ul>
          </section>

          <section class="panel">
            <p class="eyebrow">Import report</p>
            <h2>{{ report()?.dry_run ? 'Dry-run result' : 'Last apply result' }}</h2>
            @if (report(); as r) {
              <div class="report-grid">
                <div>
                  <span>Created</span>
                  <strong>{{ total(r.created) }}</strong>
                </div>
                <div>
                  <span>Reused</span>
                  <strong>{{ total(r.reused) }}</strong>
                </div>
                <div>
                  <span>Skipped</span>
                  <strong>{{ r.skipped.length }}</strong>
                </div>
                <div>
                  <span>Unresolved skills</span>
                  <strong>{{ r.unresolved_skills.length }}</strong>
                </div>
              </div>
              <div class="action-list">
                @for (action of r.actions.slice(0, 18); track $index) {
                  <code>{{ actionLine(action) }}</code>
                } @empty {
                  <p class="muted">No actions yet.</p>
                }
              </div>
            } @else {
              <p class="muted">Run a dry-run before applying a pasted blueprint.</p>
            }
          </section>
        </aside>
      </div>
    </section>
  `,
  styles: [
    `
      :host { display: block; }
      .blueprint-page {
        max-width: 1480px;
        margin: 0 auto;
        padding: 28px 32px 48px;
        color: #eef4ff;
      }
      .page-head {
        display: flex;
        justify-content: space-between;
        gap: 24px;
        align-items: flex-start;
        margin-bottom: 20px;
      }
      .eyebrow {
        margin: 0 0 8px;
        color: #67d8ff;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0;
        text-transform: uppercase;
      }
      h1, h2 { margin: 0; letter-spacing: 0; }
      h1 { font-size: 32px; line-height: 1.15; }
      h2 { font-size: 17px; line-height: 1.35; }
      .lead {
        max-width: 760px;
        margin: 10px 0 0;
        color: #98a2b8;
        line-height: 1.55;
      }
      .actions {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 10px;
        min-width: 360px;
      }
      button {
        border: 0;
        border-radius: 6px;
        padding: 10px 14px;
        color: #f7fbff;
        background: #1a2233;
        cursor: pointer;
        font: inherit;
        font-weight: 700;
      }
      button:disabled { opacity: 0.55; cursor: not-allowed; }
      button.ghost { border: 1px solid rgba(255,255,255,0.10); }
      button.primary { background: #4fc3e3; color: #071018; }
      button.danger { background: rgba(248, 93, 109, 0.16); border: 1px solid rgba(248, 93, 109, 0.3); }
      .error, .notice {
        border-radius: 6px;
        padding: 12px 14px;
        margin-bottom: 14px;
      }
      .error { color: #fecdd3; background: rgba(127, 29, 29, 0.32); border: 1px solid rgba(248, 113, 113, 0.26); }
      .notice { color: #cffafe; background: rgba(8, 145, 178, 0.16); border: 1px solid rgba(103, 216, 255, 0.22); }
      .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 18px;
      }
      .kpi, .panel {
        background: #111827;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 7px;
      }
      .kpi {
        padding: 16px;
      }
      .kpi span, .report-grid span {
        display: block;
        color: #8993a7;
        font-size: 11px;
        text-transform: uppercase;
        font-weight: 700;
        letter-spacing: 0;
      }
      .kpi strong {
        display: block;
        margin-top: 8px;
        font-size: 28px;
      }
      .layout {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 390px;
        gap: 18px;
      }
      .panel {
        overflow: hidden;
      }
      .panel-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 20px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
      }
      .badge {
        max-width: 260px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        border-radius: 999px;
        padding: 5px 9px;
        background: rgba(103, 216, 255, 0.12);
        color: #a8edff;
        font-size: 12px;
      }
      textarea {
        display: block;
        width: 100%;
        min-height: 620px;
        resize: vertical;
        border: 0;
        outline: 0;
        padding: 18px 20px;
        color: #d8e5f7;
        background: #0c111b;
        font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      }
      .side {
        display: grid;
        gap: 18px;
        align-content: start;
      }
      ul {
        margin: 12px 0 0;
        padding: 0 20px 18px 38px;
        color: #a5afc2;
        line-height: 1.55;
      }
      .report-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        padding: 16px 20px;
      }
      .report-grid div {
        border-radius: 6px;
        background: rgba(0,0,0,0.22);
        padding: 12px;
      }
      .report-grid strong {
        display: block;
        margin-top: 6px;
        font-size: 22px;
      }
      .action-list {
        display: grid;
        gap: 8px;
        padding: 0 20px 18px;
      }
      .action-list code {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        border-radius: 5px;
        background: rgba(255,255,255,0.04);
        padding: 7px 9px;
        color: #b7c3d8;
      }
      .muted {
        margin: 0;
        padding: 0 20px 18px;
        color: #8993a7;
      }
      @media (max-width: 1040px) {
        .page-head, .layout { display: block; }
        .actions { justify-content: flex-start; min-width: 0; margin-top: 16px; }
        .side { margin-top: 18px; }
        .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      }
    `,
  ],
})
export class WorkspaceBlueprintsComponent implements OnInit {
  private readonly api = inject(ApiService);

  readonly blueprint = signal<WorkspaceBlueprint | null>(null);
  readonly report = signal<BlueprintReport | null>(null);
  readonly error = signal<string | null>(null);
  readonly status = signal<string | null>(null);
  readonly loading = signal(false);
  importText = '';
  private lastValidatedText = '';

  readonly summary = computed(() => {
    const bp = this.blueprint();
    return {
      systems: Array.isArray(bp?.['systems']) ? bp!['systems'].length : 0,
      capabilities: Array.isArray(bp?.['capabilities']) ? bp!['capabilities'].length : 0,
      contexts: Array.isArray(bp?.['contexts']) ? bp!['contexts'].length : 0,
      collections: Array.isArray(bp?.['knowledge']?.['collections']) ? bp!['knowledge']['collections'].length : 0,
    };
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.status.set(null);
    this.api.get<WorkspaceBlueprint>('/blueprints/workspace/current').subscribe({
      next: (blueprint) => {
        this.blueprint.set(blueprint);
        this.importText = JSON.stringify(blueprint, null, 2);
        this.status.set('Current workspace blueprint loaded.');
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(this.messageFromError(err));
        this.loading.set(false);
      },
    });
  }

  validate(): void {
    const blueprint = this.parseImportText();
    if (!blueprint) return;
    this.loading.set(true);
    this.api.post<BlueprintReport>('/blueprints/workspace/validate', { blueprint, dry_run: true }).subscribe({
      next: (report) => {
        this.report.set(report);
        this.lastValidatedText = this.importText;
        this.status.set('Dry-run completed. No workspace objects were written.');
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(this.messageFromError(err));
        this.loading.set(false);
      },
    });
  }

  apply(): void {
    const blueprint = this.parseImportText();
    if (!blueprint) return;
    this.loading.set(true);
    this.api.post<BlueprintReport>('/blueprints/workspace/apply', { blueprint, dry_run: false }).subscribe({
      next: (report) => {
        this.report.set(report);
        this.lastValidatedText = '';
        this.status.set('Blueprint applied. Imported systems are created as drafts by default.');
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(this.messageFromError(err));
        this.loading.set(false);
      },
    });
  }

  download(): void {
    const blueprint = this.blueprint();
    if (!blueprint) return;
    const slug = blueprint['source']?.['workspace_slug'] || 'workspace';
    const blob = new Blob([JSON.stringify(blueprint, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${slug}-workspace-blueprint.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  total(values: Record<string, number>): number {
    return Object.values(values || {}).reduce((sum, value) => sum + Number(value || 0), 0);
  }

  actionLine(action: Record<string, unknown>): string {
    const kind = String(action['kind'] || 'object');
    const actionName = String(action['action'] || 'inspect');
    const name = String(action['name'] || action['slug'] || '');
    return name ? `${kind}: ${actionName} ${name}` : `${kind}: ${actionName}`;
  }

  canApply(): boolean {
    return this.report()?.dry_run === true && this.lastValidatedText === this.importText;
  }

  private parseImportText(): WorkspaceBlueprint | null {
    this.error.set(null);
    this.status.set(null);
    try {
      return JSON.parse(this.importText || '{}') as WorkspaceBlueprint;
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : 'Invalid JSON');
      return null;
    }
  }

  private messageFromError(err: any): string {
    const detail = err?.error?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
    if (detail?.code) return detail.code;
    return err?.message || 'Blueprint request failed.';
  }
}
