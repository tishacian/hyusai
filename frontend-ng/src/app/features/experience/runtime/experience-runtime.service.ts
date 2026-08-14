import { Injectable, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, of, timer } from 'rxjs';
import { catchError, switchMap, takeWhile, tap } from 'rxjs/operators';
import { ApiService } from '@app/core/api.service';
import { CanonicalApiService, type Run } from '@app/core/canonical-api.service';
import { runIsSettled } from './model';

export interface BindingSnapshot {
  binding_key?: string;
  confirmation_policy?: string;
  on_unavailable?: string;
  system_id?: string;
}

export interface BindingResolve {
  status: 'ok' | 'unavailable' | 'drift' | string;
  reasons: string[];
  binding: BindingSnapshot;
}

export interface BindingInvokeResult {
  id: string;
  status: Run['status'] | string;
  binding_key?: string;
}

const POLL_MS = 1500;
const MAX_POLLS = 80;

@Injectable({ providedIn: 'root' })
export class ExperienceRuntimeService {
  private readonly api = inject(ApiService);
  private readonly canonical = inject(CanonicalApiService);

  readonly run = signal<Run | null>(null);
  readonly phase = signal<'idle' | 'loading' | 'running' | 'error'>('idle');
  readonly lastError = signal<string | null>(null);

  private lastInvoke: { key: string; payload: Record<string, unknown>; confirmed?: boolean } | null =
    null;

  resolve(bindingKey: string): Observable<BindingResolve | null> {
    return this.api
      .get<BindingResolve>(`/system-bindings/${encodeURIComponent(bindingKey)}/resolve`)
      .pipe(catchError(() => of(null)));
  }

  invoke(
    bindingKey: string,
    payload: Record<string, unknown>,
    confirmed?: boolean,
  ): Observable<BindingInvokeResult | null> {
    this.lastInvoke = { key: bindingKey, payload, confirmed };
    this.phase.set('loading');
    this.lastError.set(null);
    const body: { payload: Record<string, unknown>; confirmed?: boolean } = { payload };
    if (confirmed !== undefined) body.confirmed = confirmed;
    return this.api
      .post<BindingInvokeResult>(`/system-bindings/${encodeURIComponent(bindingKey)}/runs`, body)
      .pipe(
        tap((started) => {
          this.phase.set('running');
          this.run.set({
            id: started.id,
            system_id: '',
            status: (started.status as Run['status']) || 'pending',
          });
        }),
        catchError((err: unknown) => {
          this.phase.set('error');
          this.lastError.set(invokeErrorMessage(err));
          return of(null);
        }),
      );
  }

  poll(runId: string): Observable<Run | null> {
    let polls = 0;
    return timer(0, POLL_MS).pipe(
      switchMap(() => this.canonical.getRun(runId)),
      tap((run) => {
        if (run) this.run.set(run);
        if (run && runIsSettled(run.status)) {
          this.phase.set(run.status === 'failed' ? 'error' : 'idle');
          if (run.status === 'failed') this.lastError.set(run.error ?? 'failed');
        }
      }),
      takeWhile((run) => {
        polls += 1;
        return polls < MAX_POLLS && !runIsSettled(run?.status);
      }, true),
      catchError(() => {
        this.phase.set('error');
        this.lastError.set('network');
        return of(null);
      }),
    );
  }

  retry(): Observable<BindingInvokeResult | null> {
    if (!this.lastInvoke) return of(null);
    return this.invoke(this.lastInvoke.key, this.lastInvoke.payload, true);
  }

  reset(): void {
    this.run.set(null);
    this.phase.set('idle');
    this.lastError.set(null);
  }
}

function invokeErrorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail = err.error;
    if (detail && typeof detail === 'object') {
      const rec = detail as Record<string, unknown>;
      if (typeof rec['message'] === 'string') return rec['message'];
      const nested = rec['detail'];
      if (nested && typeof nested === 'object' && typeof (nested as { message?: unknown }).message === 'string') {
        return (nested as { message: string }).message;
      }
    }
    return err.status === 0 ? 'network' : `http_${err.status}`;
  }
  return 'failed';
}
