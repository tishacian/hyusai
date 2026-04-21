import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  CkObjectHeaderComponent,
  type CkObjectKpi,
} from '@app/shared/cockpit/object-header.component';
import { CkTabsComponent, CkTabComponent } from '@app/shared/cockpit/tabs.component';
import { CkPanelComponent } from '@app/shared/cockpit/panel.component';
import { LensService } from '@app/core/lens';

/**
 * `KnowledgeViewComponent` — detail page for a single Knowledge Base
 * (Qdrant collection). Uses the canonical `<ck-object-header>` +
 * `<ck-tabs>` pattern. Canonical tabs: Overview · Sources · Chunks · Bindings.
 *
 * The `:kbId` route parameter is the collection name; real data wiring
 * (docs count, chunks count, bindings to skills/systems) will land in the
 * follow-up data wave.
 */
@Component({
  selector: 'app-knowledge-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    CkObjectHeaderComponent,
    CkTabsComponent,
    CkTabComponent,
    CkPanelComponent,
  ],
  template: `
    <ck-object-header
      eyebrow="Knowledge · Collection"
      [title]="title()"
      subtitle="A knowledge base is a pool of context that one or more systems can cite."
      [kpis]="kpis()"
    >
      <button
        actions
        type="button"
        (click)="bindingsPanelOpen.set(true)"
        class="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition"
      >
        Bindings
      </button>
    </ck-object-header>

    <ck-tabs
      [active]="activeTab()"
      (activeChange)="onTabChange($event)"
      ariaLabel="Knowledge facets"
    >
      <ck-tab id="overview" label="Overview">
        <section class="t-card t-elevated rounded-md p-5 space-y-3">
          <h3 class="text-sm font-semibold text-white">Purpose</h3>
          <p class="text-xs text-gray-400">
            The collection holds embedded chunks of source documents. Presets
            (RAG, CHAH, HAH) decide how it is consumed by a System at run time.
          </p>
          <div class="flex items-center gap-2 flex-wrap text-xs">
            <a routerLink="/knowledge" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 ring-1 ring-white/10 text-gray-200 transition">
              Back to collections
            </a>
          </div>
          <p class="text-[11px] text-gray-500">
            Lens: <span class="font-mono text-brand-300">{{ lens() }}</span>
          </p>
        </section>
      </ck-tab>

      <ck-tab id="sources" label="Sources">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Source documents ingested into this collection (filename, size,
          upload timestamp). Wires to /kb/&#123;name&#125;/documents.
        </div>
      </ck-tab>

      <ck-tab id="chunks" label="Chunks">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Exploded view of vector chunks with preview and similarity search.
          Wires to /kb/&#123;name&#125;/search.
        </div>
      </ck-tab>

      <ck-tab id="bindings" label="Bindings">
        <div class="t-card rounded-md p-5 text-center text-gray-400 text-sm">
          Skills and Systems consuming this collection. Open the side panel
          for a quick overview.
        </div>
      </ck-tab>
    </ck-tabs>

    <ck-panel
      [open]="bindingsPanelOpen()"
      (openChange)="bindingsPanelOpen.set($event)"
      position="side"
      eyebrow="Knowledge · panel"
      title="Bindings"
      width="420px"
    >
      <p class="text-xs text-gray-400">
        Systems and skills currently bound to this collection, with their
        preset (RAG, CHAH, HAH) and confidence floor.
      </p>
    </ck-panel>
  `,
})
export class KnowledgeViewComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  readonly lensService = inject(LensService);

  kbId = '';
  readonly title = signal('Knowledge base');
  readonly activeTab = signal<KbTabId>('overview');
  readonly bindingsPanelOpen = signal(false);

  readonly lens = this.lensService.lens;

  readonly kpis = computed<CkObjectKpi[]>(() => [
    { label: 'Docs', value: '—', hint: 'Number of source documents ingested.' },
    { label: 'Chunks', value: '—', hint: 'Vector chunks currently indexed.' },
    { label: 'Bindings', value: '—', hint: 'Skills + Systems consuming this KB.' },
    { label: 'Freshness', value: '—', tone: 'neutral', hint: 'Last ingestion time.' },
  ]);

  ngOnInit(): void {
    this.kbId = this.route.snapshot.paramMap.get('kbId') ?? '';
    this.title.set(this.kbId || 'Knowledge base');
  }

  onTabChange(id: string): void {
    this.activeTab.set(id as KbTabId);
  }
}

type KbTabId = 'overview' | 'sources' | 'chunks' | 'bindings';
