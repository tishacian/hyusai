import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/** Server view of Work and Studio for one workspace, read by an administrator. */
export interface ExperienceActivationState {
  enabled: boolean;
  studio_enabled: boolean;
  members: { total: number; studio_editors: number; studio_reviewers: number };
}

/**
 * Flag-only activation of Work and Studio. The write is a compare-and-set: the
 * server refuses it with 409 WORKSPACE_FEATURE_CONFLICT when `expected` is no
 * longer the stored value. Errors are never swallowed here; the caller decides
 * what a failure, a refusal or an unknown outcome looks like.
 */
@Injectable({ providedIn: 'root' })
export class ExperienceActivationService {
  private readonly http = inject(HttpClient);

  read(slug: string): Observable<ExperienceActivationState> {
    return this.http.get<ExperienceActivationState>(this.url(slug));
  }

  write(slug: string, enabled: boolean, expected: boolean): Observable<ExperienceActivationState> {
    return this.http.put<ExperienceActivationState>(this.url(slug), {
      enabled,
      expected_enabled: expected,
    });
  }

  private url(slug: string): string {
    return `/api/v1/auth/workspaces/${encodeURIComponent(slug)}/features/experience`;
  }
}
