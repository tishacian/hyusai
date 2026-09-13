/**
 * Behaviour of the Knowledge activation points: an indexed batch is knowledge
 * added, and a batch that follows a failed upload is a recovery.
 */

import '@angular/compiler';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Injector } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subject, of } from 'rxjs';
import { ToastrService } from 'ngx-toastr';
import { I18nService } from '@app/core/i18n.service';
import {
  ProductTelemetryService,
  type ProductActivationMilestone,
  type ProductActivationOptions,
} from '@app/core/product-telemetry.service';
import { KnowledgeBaseComponent } from './knowledge-base.component';

interface UploadResult {
  total: number;
  successful: number;
  failed: number;
}

class ActivationTelemetryStub {
  readonly calls: Array<{
    milestone: ProductActivationMilestone;
    options: ProductActivationOptions;
  }> = [];
  private readonly seen = new Set<string>();

  recordOnce(milestone: ProductActivationMilestone, options: ProductActivationOptions = {}): void {
    if (this.seen.has(milestone)) return;
    this.seen.add(milestone);
    this.calls.push({ milestone, options });
  }

  recordOccurrence(
    milestone: ProductActivationMilestone,
    options: ProductActivationOptions & { dedupeKey: string },
  ): void {
    const key = `${milestone}:${options.dedupeKey}`;
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.calls.push({ milestone, options });
  }

  milestones(): ProductActivationMilestone[] {
    return this.calls.map((call) => call.milestone);
  }
}

class HttpStub {
  readonly uploads: Array<Subject<UploadResult>> = [];

  get() {
    return of({ collections: [], items: [], vector_db_type: 'qdrant' });
  }

  post(_url: string, _body: unknown) {
    const request = new Subject<UploadResult>();
    this.uploads.push(request);
    return request.asObservable();
  }
}

function makeHarness() {
  const http = new HttpStub();
  const activation = new ActivationTelemetryStub();
  const injector = Injector.create({
    providers: [
      KnowledgeBaseComponent,
      { provide: HttpClient, useValue: http },
      { provide: I18nService, useValue: { locale: () => 'fr', t: (key: string) => key } },
      {
        provide: ToastrService,
        useValue: { success: () => undefined, warning: () => undefined, error: () => undefined },
      },
      { provide: ProductTelemetryService, useValue: activation },
    ],
  });
  const component = injector.get(KnowledgeBaseComponent);
  return { injector, component, http, activation };
}

function upload(component: KnowledgeBaseComponent): void {
  (component as unknown as { uploadFiles(files: FileList): void }).uploadFiles({
    length: 1,
    0: new File(['contenu'], 'notice-technique-confidentielle.pdf'),
    item: () => null,
    [Symbol.iterator]: function* () {
      yield new File(['contenu'], 'notice-technique-confidentielle.pdf');
    },
  } as unknown as FileList);
}

test('an indexed batch records knowledge added exactly once', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component);
    http.uploads[0].next({ total: 1, successful: 1, failed: 0 });
    assert.deepEqual(activation.milestones(), ['knowledge_added']);

    upload(component);
    http.uploads[1].next({ total: 1, successful: 1, failed: 0 });
    assert.deepEqual(activation.milestones(), ['knowledge_added']);
  } finally {
    injector.destroy();
  }
});

test('a batch that indexed nothing is not knowledge added', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component);
    http.uploads[0].next({ total: 2, successful: 0, failed: 2 });

    assert.deepEqual(activation.milestones(), []);
    assert.equal(component.uploadState(), 'partial');
  } finally {
    injector.destroy();
  }
});

test('a clean batch after a failed upload records the recovery', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component);
    http.uploads[0].error(new Error('upload endpoint unreachable'));
    assert.equal(component.uploadState(), 'error');

    upload(component);
    // The retry has already moved uploadState back to `uploading`; the
    // recovery must survive that.
    assert.equal(component.uploadState(), 'uploading');
    http.uploads[1].next({ total: 1, successful: 1, failed: 0 });

    assert.deepEqual(activation.milestones(), ['knowledge_added', 'failure_recovered']);
    const recovery = activation.calls[1];
    assert.equal(recovery.options.recoveryKind, 'knowledge_upload');
    assert.equal(JSON.stringify(recovery.options).includes('notice-technique'), false);
  } finally {
    injector.destroy();
  }
});

test('a batch that still leaves documents failing keeps the recovery armed', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component);
    http.uploads[0].error(new Error('upload endpoint unreachable'));

    upload(component);
    http.uploads[1].next({ total: 3, successful: 1, failed: 2 });
    assert.deepEqual(activation.milestones(), ['knowledge_added']);

    upload(component);
    http.uploads[2].next({ total: 1, successful: 1, failed: 0 });

    assert.deepEqual(activation.milestones(), ['knowledge_added', 'failure_recovered']);
  } finally {
    injector.destroy();
  }
});

test('a first successful upload is not reported as a recovery', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component);
    http.uploads[0].next({ total: 1, successful: 1, failed: 0 });

    assert.deepEqual(activation.milestones(), ['knowledge_added']);
  } finally {
    injector.destroy();
  }
});

test('the recovery is consumed once, not repeated on every later upload', () => {
  const { injector, component, http, activation } = makeHarness();
  try {
    upload(component);
    http.uploads[0].error(new Error('upload endpoint unreachable'));
    upload(component);
    http.uploads[1].next({ total: 1, successful: 1, failed: 0 });
    upload(component);
    http.uploads[2].next({ total: 1, successful: 1, failed: 0 });

    assert.equal(
      activation.milestones().filter((milestone) => milestone === 'failure_recovered').length,
      1,
    );
  } finally {
    injector.destroy();
  }
});
