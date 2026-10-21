import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { HttpErrorResponse } from '@angular/common/http';
import { NEVER, Observable, Subject, of, throwError } from 'rxjs';
import { ExperienceActivationController, activationWriteOutcome } from './experience-activation.controller';
import type { ExperienceActivationState } from './experience-activation.service';

function state(enabled: boolean): ExperienceActivationState {
  return { enabled, studio_enabled: enabled, members: { total: 5, studio_editors: 2, studio_reviewers: 1 } };
}

class ApiStub {
  reads: string[] = [];
  writes: Array<{ slug: string; enabled: boolean; expected: boolean }> = [];
  readResult: () => Observable<ExperienceActivationState> = () => of(state(false));
  writeResult: () => Observable<ExperienceActivationState> = () => of(state(true));
  read(slug: string) { this.reads.push(slug); return this.readResult(); }
  write(slug: string, enabled: boolean, expected: boolean) {
    this.writes.push({ slug, enabled, expected });
    return this.writeResult();
  }
}

function harness(timeoutMs = 50) {
  const api = new ApiStub();
  let slug = 'alpha';
  let refreshed = 0;
  const controller = new ExperienceActivationController(api, () => slug, () => { refreshed += 1; }, timeoutMs);
  return {
    api, controller,
    setSlug: (next: string) => { slug = next; },
    refreshed: () => refreshed,
  };
}

const http = (status: number) => new HttpErrorResponse({ status });

test('a failed read is an error with no state and no possible write', () => {
  const { api, controller } = harness();
  api.readResult = () => throwError(() => http(500));
  controller.open('alpha');
  assert.equal(controller.readState(), 'error');
  assert.equal(controller.state(), null);
  controller.apply();
  assert.equal(api.writes.length, 0);
});

test('enabling sends the value read as expected and shows the server answer', () => {
  const { api, controller, refreshed } = harness();
  controller.open('alpha');
  assert.equal(controller.readState(), 'loaded');
  controller.apply();
  assert.deepEqual(api.writes, [{ slug: 'alpha', enabled: true, expected: false }]);
  assert.equal(controller.outcome(), 'saved');
  assert.equal(controller.state()?.enabled, true);
  assert.equal(refreshed(), 1);
});

test('a conflict is never a success: nothing shown as saved and the state is read again', () => {
  const { api, controller } = harness();
  controller.open('alpha');
  api.writeResult = () => throwError(() => http(409));
  api.readResult = () => of(state(true));
  controller.apply();
  assert.equal(controller.outcome(), 'conflict');
  assert.equal(controller.state()?.enabled, true);
  assert.equal(api.reads.length, 2);
});

test('a timeout gives an unknown outcome that locks writes until the state is read again', async () => {
  const { api, controller } = harness(10);
  controller.open('alpha');
  api.writeResult = () => NEVER;
  controller.apply();
  assert.equal(controller.outcome(), 'saving');
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(controller.outcome(), 'unknown');
  assert.equal(controller.locked(), true);
  assert.equal(controller.state()?.enabled, false);
  controller.apply();
  assert.equal(api.writes.length, 1);
  controller.load();
  assert.equal(controller.outcome(), null);
  assert.equal(controller.locked(), false);
});

test('outcomes by error kind', () => {
  assert.equal(activationWriteOutcome(http(0)), 'unknown');
  assert.equal(activationWriteOutcome(http(504)), 'unknown');
  assert.equal(activationWriteOutcome(http(403)), 'refused');
  assert.equal(activationWriteOutcome(http(500)), 'failed');
  assert.equal(activationWriteOutcome(new Error('x')), 'failed');
});

test('a response for the previous workspace is dropped', () => {
  const { api, controller, setSlug } = harness();
  const pending = new Subject<ExperienceActivationState>();
  api.readResult = () => pending;
  controller.open('alpha');
  setSlug('beta');
  pending.next(state(true));
  assert.equal(controller.state(), null);
  assert.equal(controller.readState(), 'loading');
});
