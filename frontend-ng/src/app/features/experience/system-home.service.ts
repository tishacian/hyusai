/**
 * Preview handoff + draft creation for a generated System Home.
 * Creating always inserts a new Experience; it never patches an existing one.
 */

import { Injectable, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { parseDocument, type ExperienceDocument } from './runtime/model';

const PREVIEW_KEY = 'agentium.experience.preview.document';

export class ExperienceApiMissingError extends Error {
  override name = 'ExperienceApiMissingError';
}

export interface SystemHomeCreateInput {
  name: string;
  slug: string;
  languages: string[];
  document: ExperienceDocument;
  bindingKey: string;
  systemId: string;
  publishedVersionId: string;
  ingressId: string | null;
}

export interface SystemHomeCreateResult {
  id: string;
  slug: string;
}

interface ExperienceCreated {
  id: string;
  slug: string;
  draft?: { revision?: number } | null;
}

function readSession(): ExperienceDocument | null {
  try {
    const raw = sessionStorage.getItem(PREVIEW_KEY);
    if (!raw) return null;
    const parsed = parseDocument(JSON.parse(raw));
    return parsed.pages.length > 0 ? parsed : null;
  } catch {
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class SystemHomeService {
  private readonly api = inject(ApiService);
  readonly document = signal<ExperienceDocument | null>(readSession());

  provide(doc: ExperienceDocument): void {
    this.document.set(doc);
    try {
      sessionStorage.setItem(PREVIEW_KEY, JSON.stringify(doc));
    } catch {
      // Quota / private mode — in-memory signal still holds the preview.
    }
  }

  createDraft(input: SystemHomeCreateInput): Observable<SystemHomeCreateResult> {
    const binding$ = input.ingressId
      ? this.api
          .post<{ binding_key?: string }>('/system-bindings', {
            binding_key: input.bindingKey,
            system_id: input.systemId,
            published_flow_version_id: input.publishedVersionId,
            ingress_id: input.ingressId,
          })
          .pipe(
            map((row) => row.binding_key || input.bindingKey),
            catchError((err: unknown) => {
              if (err instanceof HttpErrorResponse && err.status === 404) {
                throw new ExperienceApiMissingError();
              }
              return of(input.bindingKey);
            }),
          )
      : of(null as string | null);

    return binding$.pipe(
      switchMap((bindingKey) =>
        this.api
          .post<ExperienceCreated>('/experiences', {
            name: input.name,
            slug: input.slug,
            pattern: 'form_result',
            languages: input.languages,
            theme: {},
          })
          .pipe(
            catchError((err: unknown) => {
              if (err instanceof HttpErrorResponse && err.status === 404) {
                throw new ExperienceApiMissingError();
              }
              throw err;
            }),
            switchMap((created) => {
              const keys = bindingKey ? [bindingKey] : [];
              return this.api
                .put(`/experiences/${encodeURIComponent(created.id)}/draft`, {
                  pages: input.document,
                  binding_keys: keys,
                  expected_revision: created.draft?.revision ?? 1,
                })
                .pipe(map(() => ({ id: created.id, slug: created.slug })));
            }),
          ),
      ),
    );
  }
}
