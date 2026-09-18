import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { WorkspaceService } from '@app/core/workspace.service';
import { AssistantObjectContextService } from './assistant-object-context.service';

function harness() {
  const events = new Subject<NavigationEnd>();
  const resets: (() => void)[] = [];
  let url = '/';
  const injector = Injector.create({
    providers: [
      AssistantObjectContextService,
      {
        provide: Router,
        useValue: { get url() { return url; }, events },
      },
      {
        provide: WorkspaceService,
        useValue: { registerContextReset: (reset: () => void) => resets.push(reset) },
      },
    ],
  });
  return {
    context: injector.get(AssistantObjectContextService),
    navigate(next: string) {
      url = next;
      events.next(new NavigationEnd(1, next, next));
    },
    switchWorkspace: () => resets.forEach((reset) => reset()),
  };
}

test('canonical system and run routes become bounded object context', () => {
  const { context, navigate } = harness();
  assert.equal(context.current(), null);
  navigate('/systems/sys-42?focus_node=node-7');
  assert.deepEqual(context.current(), {
    type: 'system',
    id: 'sys-42',
    system_id: 'sys-42',
    node_id: 'node-7',
    facet: undefined,
  });
  navigate('/runs/run-42');
  assert.deepEqual(context.current(), {
    type: 'run',
    id: 'run-42',
    run_id: 'run-42',
    system_id: undefined,
    node_id: undefined,
    facet: undefined,
  });
});

test('pinning preserves an object across navigation and workspace reset clears it', () => {
  const { context, navigate, switchWorkspace } = harness();
  navigate('/systems/sys-42');
  context.pin();
  navigate('/runs/run-42');
  assert.equal(context.effective()?.id, 'sys-42');
  switchWorkspace();
  assert.equal(context.effective()?.id, 'run-42');
});
