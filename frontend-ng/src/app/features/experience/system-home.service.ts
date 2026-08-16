/**
 * Preview handoff + draft creation for a generated System Home.
 * Creating always inserts a new Experience; it never patches an existing one.
 */

import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { parseDocument, type ExperienceDocument } from './runtime/model';
import { remapSystemHomeBinding } from './runtime/system-home';

const PREVIEW_KEY = 'agentium.experience.preview.v2';

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

export interface SystemHomePreviewBinding {
  binding_key: string;
  system_id: string;
  published_flow_version_id: string;
  ingress_id: string;
  confirmation_policy: string;
  on_unavailable: string;
}

export interface SystemHomePreview {
  document: ExperienceDocument;
  binding: SystemHomePreviewBinding | null;
}

interface ExperienceCreated {
  id: string;
  slug: string;
  name?: string;
  pattern?: string;
}

function readSession(): SystemHomePreview | null {
  try {
    const raw = sessionStorage.getItem(PREVIEW_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<SystemHomePreview>;
    const document = parseDocument(value.document);
    if (document.pages.length === 0) return null;
    const binding = value.binding;
    const validBinding =
      binding &&
      typeof binding.binding_key === 'string' &&
      typeof binding.system_id === 'string' &&
      typeof binding.published_flow_version_id === 'string' &&
      typeof binding.ingress_id === 'string'
        ? {
            binding_key: binding.binding_key,
            system_id: binding.system_id,
            published_flow_version_id: binding.published_flow_version_id,
            ingress_id: binding.ingress_id,
            confirmation_policy: binding.confirmation_policy || 'confirm',
            on_unavailable: binding.on_unavailable || 'unavailable',
          }
        : null;
    return { document, binding: validBinding };
  } catch {
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class SystemHomeService {
  private readonly api = inject(ApiService);
  readonly preview = signal<SystemHomePreview | null>(readSession());
  readonly document = computed(() => this.preview()?.document ?? null);

  provide(document: ExperienceDocument, binding: SystemHomePreviewBinding | null): void {
    const preview = { document, binding };
    this.preview.set(preview);
    try {
      sessionStorage.setItem(PREVIEW_KEY, JSON.stringify(preview));
    } catch {
      // Quota / private mode — in-memory signal still holds the preview.
    }
  }

  refreshBinding(binding: SystemHomePreviewBinding): void {
    const preview = this.preview();
    const previous = preview?.binding;
    if (!preview || !previous) return;
    this.provide(
      remapSystemHomeBinding(preview.document, previous.binding_key, binding.binding_key),
      binding,
    );
  }

  createDraft(input: SystemHomeCreateInput): Observable<SystemHomeCreateResult> {
    const accessPolicy = { roles: ['workspace_admin'] };
    return this.api
      .post<ExperienceCreated>('/experiences/finalize', {
        name: input.name,
        slug: input.slug,
        pattern: 'form_result',
        languages: input.languages,
        theme: {},
        access_policy: accessPolicy,
        pages: input.document,
        binding_keys: input.ingressId ? [input.bindingKey] : [],
        bindings: input.ingressId
          ? [{
              binding_key: input.bindingKey,
              system_id: input.systemId,
              published_flow_version_id: input.publishedVersionId,
              ingress_id: input.ingressId,
              confirmation_policy: 'confirm',
              on_unavailable: 'unavailable',
            }]
          : [],
      })
      .pipe(
        catchError((err: unknown) => {
          const detail = err instanceof HttpErrorResponse ? err.error?.detail : null;
          const hasBusinessCode = detail && typeof detail === 'object' && typeof detail.code === 'string';
          if (hasBusinessCode && detail.code === 'EXPERIENCE_SLUG_EXISTS') {
            return this.api.get<{ experiences: ExperienceCreated[] }>('/experiences').pipe(
              map((body) => {
                const existing = (body.experiences ?? []).find(
                  (row) => row.slug === input.slug && row.name === input.name && row.pattern === 'form_result',
                );
                if (!existing) throw err;
                return existing;
              }),
            );
          }
          if (err instanceof HttpErrorResponse && err.status === 404 && !hasBusinessCode) {
            return throwError(() => new ExperienceApiMissingError());
          }
          return throwError(() => err);
        }),
        map((created) => ({ id: created.id, slug: created.slug })),
      );
  }
}
