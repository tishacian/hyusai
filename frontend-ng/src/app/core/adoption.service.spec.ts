import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  Injector,
  ɵChangeDetectionScheduler as ChangeDetectionScheduler,
  ɵEffectScheduler as EffectScheduler,
} from '@angular/core';
import { Subject, of, type Observable } from 'rxjs';
import { AdoptionService, type AdoptionProgress } from './adoption.service';
import { ApiService } from './api.service';
import { HelpService } from './help.service';
import { WorkspaceService } from './workspace.service';

const DAY = 24 * 60 * 60 * 1000;

function progress(overrides: Partial<AdoptionProgress> = {}): AdoptionProgress {
  return {
    version: 1,
    persona: 'operator',
    journey: 'northforge_sources',
    completed_steps: [],
    dismissed: false,
    rail_labels: 'auto',
    first_seen_at: new Date(Date.now() - 2 * DAY).toISOString(),
    ...overrides,
  };
}

function setup(options: { adoption?: boolean } = {}) {
  const patches: Array<{ body: unknown; reply: Subject<AdoptionProgress> }> = [];
  const scope = Object.freeze({ workspaceSlug: 'chrome-v2', workspaceId: 'workspace-chrome-v2', epoch: 1 });
  const injector = Injector.create({
    providers: [
      AdoptionService,
      {
        provide: ApiService,
        useValue: {
          get: () => of(progress()),
          patch: (_path: string, body: unknown): Observable<AdoptionProgress> => {
            const reply = new Subject<AdoptionProgress>();
            patches.push({ body, reply });
            return reply.asObservable();
          },
        },
      },
      {
        provide: WorkspaceService,
        useValue: {
          current: () => ({
            settings: options.adoption === false ? { features: { adoption_experience_v1: false } } : {},
          }),
          captureRequestScope: () => scope,
          isRequestScopeCurrent: () => true,
          registerContextReset: () => () => undefined,
        },
      },
      { provide: HelpService, useValue: { setPersona: () => undefined } },
      { provide: ChangeDetectionScheduler, useValue: { notify() {}, runningTick: false } },
      { provide: EffectScheduler, useValue: { add() {}, schedule() {}, flush() {}, remove() {} } },
    ],
  });
  return { adoption: injector.get(AdoptionService), patches };
}

test('the rail stays icons-only until the experience record is known', () => {
  const { adoption } = setup();
  assert.equal(adoption.railLabelsVisible(), null, 'unknown, so no labels flash in');
  adoption.load();
  assert.equal(adoption.railLabelsVisible(), true, 'a member seen two days ago gets labels');
  adoption.progress.set(progress({ first_seen_at: new Date(Date.now() - 20 * DAY).toISOString() }));
  assert.equal(adoption.railLabelsVisible(), false, 'after two weeks the rail is icons-only');
  adoption.progress.set(progress({ rail_labels: 'shown', first_seen_at: '2025-01-01T00:00:00Z' }));
  assert.equal(adoption.railLabelsVisible(), true, 'an explicit choice wins');
});

test('without adoption_experience_v1 the rail keeps its L6 icon column', () => {
  const { adoption } = setup({ adoption: false });
  adoption.progress.set(progress({ rail_labels: 'shown' }));
  assert.equal(adoption.railLabelsVisible(), false);
  adoption.setRailLabels('hidden');
  assert.equal(adoption.progress()?.rail_labels, 'shown', 'no write when the experience is off');
});

test('hiding the labels is optimistic and saved with a rail_labels patch only', () => {
  const { adoption, patches } = setup();
  adoption.load();
  adoption.setRailLabels('hidden');
  assert.equal(adoption.railLabelsVisible(), false, 'the rail follows at once');
  assert.deepEqual(patches.map((p) => p.body), [{ rail_labels: 'hidden' }]);
  patches[0].reply.next(progress({ rail_labels: 'hidden' }));
  patches[0].reply.complete();
  assert.equal(adoption.railLabelsVisible(), false);
  assert.equal(adoption.railLabelsError(), false);
  assert.equal(adoption.error(), false);
});

test('a failed write brings the previous preference back and says so politely', () => {
  const { adoption, patches } = setup();
  adoption.load();
  adoption.setRailLabels('hidden');
  assert.equal(adoption.railLabelsVisible(), false);
  patches[0].reply.error(new Error('offline'));
  assert.equal(adoption.progress()?.rail_labels, 'auto', 'reverted');
  assert.equal(adoption.railLabelsVisible(), true);
  assert.equal(adoption.railLabelsError(), true, 'the rail announces the failure');
  assert.equal(adoption.error(), false, 'the journey alert stays out of it');

  adoption.setRailLabels('hidden');
  assert.equal(adoption.railLabelsError(), false, 'a new attempt clears the message');
});
