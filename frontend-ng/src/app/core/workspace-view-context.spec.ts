import assert from 'node:assert/strict';
import { test } from 'node:test';
import type {
  WorkspaceContextTransition,
  WorkspaceRequestScope,
} from './workspace.service';
import { WorkspaceViewContext } from './workspace-view-context';

class WorkspaceStub {
  private slug = 'workspace-a';
  private epoch = 4;
  private readonly resetters = new Set<(transition: WorkspaceContextTransition) => void>();

  readonly contextEpoch = () => this.epoch;

  captureRequestScope(): WorkspaceRequestScope {
    return Object.freeze({ workspaceSlug: this.slug, workspaceId: `workspace-${this.slug}`, epoch: this.epoch });
  }

  isRequestScopeCurrent(scope: WorkspaceRequestScope): boolean {
    return scope.workspaceSlug === this.slug && scope.epoch === this.epoch;
  }

  registerContextReset(resetter: (transition: WorkspaceContextTransition) => void): () => void {
    this.resetters.add(resetter);
    return () => this.resetters.delete(resetter);
  }

  switchWorkspace(nextSlug: string): void {
    const transition: WorkspaceContextTransition = {
      previousSlug: this.slug,
      nextSlug,
      previousEpoch: this.epoch,
      nextEpoch: this.epoch + 1,
    };
    for (const resetter of [...this.resetters]) resetter(transition);
    this.slug = nextSlug;
    this.epoch = transition.nextEpoch;
  }

  resetterCount(): number {
    return this.resetters.size;
  }
}

test('WorkspaceViewContext clears A synchronously and reloads only after B is published', async () => {
  const workspace = new WorkspaceStub();
  const events: string[] = [];
  const context = new WorkspaceViewContext(
    workspace as never,
    () => events.push(`reset:${workspace.captureRequestScope().workspaceSlug}`),
    () => events.push(`reload:${workspace.captureRequestScope().workspaceSlug}`),
  );
  const requestA = context.beginRequest();

  workspace.switchWorkspace('workspace-b');

  assert.deepEqual(events, ['reset:workspace-a']);
  assert.equal(context.isCurrent(requestA), false, 'A is invalid before B can render');

  await Promise.resolve();
  assert.deepEqual(events, ['reset:workspace-a', 'reload:workspace-b']);

  const requestB = context.beginRequest();
  assert.equal(context.isCurrent(requestB), true);
  context.destroy();
  assert.equal(context.isCurrent(requestB), false);
  assert.equal(workspace.resetterCount(), 0);
});

test('WorkspaceViewContext rejects a late route id and skips superseded reload epochs', async () => {
  const workspace = new WorkspaceStub();
  let reloads = 0;
  const context = new WorkspaceViewContext(
    workspace as never,
    () => undefined,
    () => { reloads += 1; },
  );

  const firstId = context.beginRequest();
  const secondId = context.beginRequest();
  assert.equal(context.isCurrent(firstId), false);
  assert.equal(context.isCurrent(secondId), true);

  workspace.switchWorkspace('workspace-b');
  workspace.switchWorkspace('workspace-c');
  await Promise.resolve();

  assert.equal(reloads, 1, 'only the latest committed epoch reloads');
  context.destroy();
});
