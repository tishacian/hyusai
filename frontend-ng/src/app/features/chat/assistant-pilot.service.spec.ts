import "@angular/compiler";
import assert from "node:assert/strict";
import { test } from "node:test";
import { Injector } from "@angular/core";
import { Subject } from "rxjs";
import { ApiService } from "@app/core/api.service";
import { WorkspaceService } from "@app/core/workspace.service";
import {
  AssistantPilotService,
  type PilotTurn,
} from "./assistant-pilot.service";

function harness() {
  let generation = 0;
  const resets: (() => void)[] = [];
  const posts: {
    path: string;
    body: any;
    response: Subject<any>;
    options: any;
  }[] = [];
  const injector = Injector.create({
    providers: [
      AssistantPilotService,
      {
        provide: ApiService,
        useValue: {
          post: (path: string, body: any, options: any) => {
            const response = new Subject();
            posts.push({ path, body, response, options });
            return response;
          },
        },
      },
      {
        provide: WorkspaceService,
        useValue: {
          registerContextReset: (reset: () => void) => resets.push(reset),
          captureRequestScope: () => ({
            workspaceSlug: `ws-${generation}`,
            generation,
          }),
          isRequestScopeCurrent: (scope: any) =>
            scope.generation === generation,
        },
      },
    ],
  });
  return {
    pilot: injector.get(AssistantPilotService),
    posts,
    switchWorkspace: () => {
      generation++;
      resets.forEach((reset) => reset());
    },
  };
}
const answer: PilotTurn = {
  session_id: "session-one",
  answer: "The result has attached evidence.",
  tool_calls: [],
};

test("network recovery retains the exact idempotency request and session", () => {
  const { pilot, posts } = harness();
  pilot.select(["system-one"]);
  pilot.send("Run this example");
  pilot.send("double click");
  assert.equal(posts.length, 1);
  posts[0].response.error({ status: 0 });
  pilot.retry();
  assert.deepEqual(posts[1].body, posts[0].body);
  posts[1].response.next(answer);
  posts[1].response.complete();
  pilot.send("Explain this result");
  assert.equal(posts[2].body.session_id, "session-one");
  assert.deepEqual(posts[2].body.system_ids, ["system-one"]);
});

test("workspace changes discard late responses and scope changes do not share memory", () => {
  const { pilot, posts, switchWorkspace } = harness();
  pilot.select(["system-one"]);
  pilot.send("Read");
  switchWorkspace();
  posts[0].response.next(answer);
  assert.deepEqual(pilot.turns(), []);
  assert.deepEqual(pilot.systemIds(), []);
  pilot.select(["system-two"]);
  pilot.send("Read B");
  assert.equal(posts[1].body.session_id, undefined);
  assert.equal(posts[1].options.workspaceSlug, "ws-1");
  posts[1].response.next(answer);
  pilot.select(["system-three"]);
  pilot.send("Read C");
  assert.equal(posts[2].body.session_id, undefined);
});
