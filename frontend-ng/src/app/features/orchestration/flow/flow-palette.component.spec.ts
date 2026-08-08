/**
 * `FlowPaletteComponent` through a real Angular `Injector` (no TestBed in this
 * runner, so signal inputs are bound by {@link bindInput} and the effect
 * schedulers are inert stubs). The ranking and grouping rules themselves live
 * in `flow-palette.vm.spec.ts`; what is exercised here is the surface the
 * operator actually drives: which level is showing, what a query does, and
 * what happens at a dead end.
 */
import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  runInInjectionContext,
  signal,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { FlowCatalogService } from './flow-catalog.service';
import { FlowPaletteComponent } from './flow-palette.component';
import type { PaletteInsertContext } from './flow-palette.vm';
import { DEFAULT_PALETTE, type PaletteItem, type SkillPaletteSection } from './flow.types';

interface PaletteControls {
  query(): string;
  level(): 'capabilities' | 'advanced';
  activeIndex(): number;
  showUnavailable: { set(value: boolean): void };
  rankedMode(): boolean;
  rankedItems(): PaletteItem[];
  rankedOverflow(): number;
  rankedEmptyMessage(): string;
  unavailableMatches(): PaletteItem[];
  unavailableExplanation(): string;
  capabilityGroups(): Array<{ slug: string; name: string; items: PaletteItem[] }>;
  categorySections(): Array<{ category: SkillPaletteSection; items: PaletteItem[] }>;
  mostUsed(): PaletteItem[];
  openGroup(): { slug: string; items: PaletteItem[] } | null;
  headingLabel(): string;
  headingCount(): string;
  isSectionExpanded(category: SkillPaletteSection): boolean;
  toggleSection(category: SkillPaletteSection): void;
  structureExpanded(): boolean;
  toggleStructure(): void;
  openCapability(slug: string): void;
  closeCapability(): void;
  onQuery(event: Event): void;
  onSearchKey(event: KeyboardEvent): void;
  onPick(item: PaletteItem): void;
  intent(item: PaletteItem): string;
  isInFlow(item: PaletteItem): boolean;
}

function skill(overrides: Partial<PaletteItem> & { label: string }): PaletteItem {
  const slug = `${overrides.label.toLowerCase().replace(/\s+/g, '_')}_v1`;
  return {
    type: 'skill',
    kind: 'task',
    description: `${overrides.label} description`,
    icon: 'box',
    tone: 'cyan',
    runtimeStatus: 'bound',
    usageCalls: 0,
    capabilitySlugs: ['ticket_triage'],
    skillCategory: 'LLM',
    ...overrides,
    config: { skill_slug: slug },
  };
}

/** The unit runner has no TestBed: substitute a signal input with a function
 * of the same read shape. */
function bindInput(component: object, name: string, value: unknown): void {
  Object.defineProperty(component, name, { value: () => value, configurable: true });
}

function setup(options: {
  skills?: PaletteItem[];
  filtered?: PaletteItem[];
  capabilities?: Array<{ slug: string; name: string; description?: string }>;
  filteredReasons?: Record<string, number>;
  context?: PaletteInsertContext | null;
  items?: PaletteItem[];
  nodeCount?: number;
  flowSkillSlugs?: string[];
} = {}): { palette: FlowPaletteComponent; controls: PaletteControls; added: PaletteItem[] } {
  const entries = signal<PaletteItem[]>(options.skills ?? []);
  const filtered = signal<PaletteItem[]>(options.filtered ?? []);
  const catalog = {
    skillItems: entries.asReadonly(),
    filteredItems: filtered.asReadonly(),
    capabilities: signal(options.capabilities ?? []).asReadonly(),
    summary: signal({
      total: (options.skills?.length ?? 0) + (options.filtered?.length ?? 0),
      visible: options.skills?.length ?? 0,
      filtered: options.filtered?.length ?? 0,
      filteredReasons: options.filteredReasons ?? {},
    }).asReadonly(),
    state: signal<'loading' | 'loaded' | 'error'>('loaded'),
    retry: () => undefined,
  };
  const injector = Injector.create({
    providers: [
      { provide: FlowCatalogService, useValue: catalog },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  const palette = runInInjectionContext(injector, () => new FlowPaletteComponent());
  bindInput(palette, 'items', options.items ?? []);
  bindInput(palette, 'context', options.context ?? null);
  bindInput(palette, 'nodeCount', options.nodeCount ?? 4);
  bindInput(palette, 'flowSkillSlugs', options.flowSkillSlugs ?? []);
  const added: PaletteItem[] = [];
  palette.add.subscribe((item) => added.push(item));
  return { palette, controls: palette as unknown as PaletteControls, added };
}

function type(controls: PaletteControls, value: string): void {
  controls.onQuery({ target: { value } } as unknown as Event);
}

function key(controls: PaletteControls, name: string): void {
  controls.onSearchKey({ key: name, preventDefault: () => undefined } as KeyboardEvent);
}

test('the default surface is Capabilities, not the registry', () => {
  const { controls } = setup({
    skills: [
      skill({ label: 'Route ticket' }),
      skill({ label: 'Summarise', capabilitySlugs: ['knowledge_ops'] }),
    ],
    capabilities: [{ slug: 'ticket_triage', name: 'Ticket triage' }],
  });

  assert.equal(controls.rankedMode(), false);
  assert.equal(controls.headingLabel(), 'Add node');
  assert.equal(controls.headingCount(), '2', 'the count is capabilities, not skills');
  assert.deepEqual(controls.capabilityGroups().map((group) => group.name), [
    'Knowledge ops',
    'Ticket triage',
  ]);

  controls.openCapability('ticket_triage');
  assert.equal(controls.headingLabel(), 'Ticket triage');
  assert.deepEqual(controls.openGroup()?.items.map((item) => item.label), ['Route ticket']);
  controls.closeCapability();
  assert.equal(controls.openGroup(), null);
});

test('the advanced level opens with every category collapsed', () => {
  const { controls } = setup({
    skills: [skill({ label: 'Answer' }), skill({ label: 'Search', skillCategory: 'Retrieval' })],
  });
  (controls as unknown as { level: { set(value: string): void } }).level.set('advanced');

  assert.deepEqual(controls.categorySections().map((section) => section.category), [
    'LLM',
    'Retrieval',
  ]);
  assert.equal(controls.isSectionExpanded('LLM'), false);
  controls.toggleSection('LLM');
  assert.equal(controls.isSectionExpanded('LLM'), true);
});

test('the structural primitives open themselves only on an empty graph', () => {
  const populated = setup({ items: DEFAULT_PALETTE, nodeCount: 3 });
  assert.equal(populated.controls.structureExpanded(), false);
  populated.controls.toggleStructure();
  assert.equal(populated.controls.structureExpanded(), true);

  const empty = setup({ items: DEFAULT_PALETTE, nodeCount: 0 });
  assert.equal(empty.controls.structureExpanded(), true);
});

test('a query switches to one ranked list, announces the remainder and adds on Enter', () => {
  const skills = Array.from({ length: 15 }, (_, index) =>
    skill({ label: `Ranker ${String(index).padStart(2, '0')}` }),
  );
  const { controls, added } = setup({ skills });
  type(controls, 'ranker');

  assert.equal(controls.rankedMode(), true);
  assert.equal(controls.headingLabel(), 'Matches');
  assert.equal(controls.rankedItems().length, 12);
  assert.equal(controls.rankedOverflow(), 3);

  key(controls, 'ArrowDown');
  key(controls, 'ArrowDown');
  assert.equal(controls.activeIndex(), 2);
  key(controls, 'ArrowUp');
  key(controls, 'Enter');
  assert.deepEqual(added.map((item) => item.label), ['Ranker 01']);

  key(controls, 'Escape');
  assert.equal(controls.query(), '');
  assert.equal(controls.rankedMode(), false);
});

test('extending a node offers only what connects, and says so when nothing does', () => {
  const stringConsumer = skill({
    label: 'Summarise text',
    inputs: [{ name: 'text', schema: 'string' }],
  });
  const objectConsumer = skill({
    label: 'Score object',
    inputs: [{ name: 'record', schema: 'object' }],
  });
  const context: PaletteInsertContext = {
    side: 'in',
    schema: 'string',
    originLabel: 'Trigger',
    originPort: 'goal',
  };
  const { controls } = setup({ skills: [stringConsumer, objectConsumer], context });

  assert.equal(controls.rankedMode(), true, 'a context is a ranked surface, not a hierarchy');
  assert.equal(controls.headingLabel(), 'Connects here');
  assert.deepEqual(controls.rankedItems().map((item) => item.label), ['Summarise text']);

  const dead = setup({ skills: [objectConsumer], context });
  assert.deepEqual(dead.controls.rankedItems(), []);
  assert.equal(dead.controls.rankedEmptyMessage(), 'No type-compatible node.');
});

test('a dead end names the rule that produced it, and never offers the row', () => {
  const invoice = skill({
    label: 'Invoice extract',
    unavailableReason: 'no_visible_capability',
    capabilitySlugs: [],
  });
  const { controls, added } = setup({
    skills: [skill({ label: 'Answer' })],
    filtered: [invoice],
    filteredReasons: { no_visible_capability: 57 },
  });

  type(controls, 'invoice');
  assert.deepEqual(controls.rankedItems(), [], 'nothing available matches');
  assert.match(controls.rankedEmptyMessage(), /Nothing available matches “invoice”/);
  assert.deepEqual(controls.unavailableMatches().map((item) => item.label), ['Invoice extract']);
  assert.match(controls.intent(invoice), /no capability enabled here carries it/);

  controls.onPick(invoice);
  assert.deepEqual(added, [], 'an unavailable row cannot enter a Flow');

  assert.match(controls.unavailableExplanation(), /^57 because no capability enabled here carries it/);
});

test('the usage signal marks what runs here and what is already in this Flow', () => {
  const used = skill({ label: 'Answer', usageCalls: 12 });
  const cold = skill({ label: 'Guard' });
  const { controls } = setup({
    skills: [used, cold],
    flowSkillSlugs: ['guard_v1'],
  });

  assert.deepEqual(controls.mostUsed().map((item) => item.label), ['Answer']);
  assert.equal(controls.isInFlow(cold), true);
  assert.equal(controls.isInFlow(used), false);
});
