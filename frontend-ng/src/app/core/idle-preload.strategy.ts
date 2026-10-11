import { Injectable } from '@angular/core';
import { PreloadingStrategy, Route } from '@angular/router';
import { Observable, EMPTY, of, timer, switchMap } from 'rxjs';

/**
 * Preload lazy routes only after the main thread has gone idle — typically
 * a few seconds after the shell is interactive. This keeps the boot path
 * lean while still making subsequent route changes feel instant (the chunk
 * is already in cache by the time the user clicks).
 *
 * Routes with `data: { preload: false }` are never preloaded.
 */
@Injectable({ providedIn: 'root' })
export class IdlePreloadStrategy implements PreloadingStrategy {
  preload(route: Route, load: () => Observable<unknown>): Observable<unknown> {
    if (route.data?.['preload'] === false) return EMPTY;

    return timer(2000).pipe(
      switchMap(() => runInIdle().pipe(switchMap(() => load()))),
    );
  }
}

function runInIdle(): Observable<void> {
  return new Observable<void>((subscriber) => {
    const ric = (window as any).requestIdleCallback as
      | ((cb: () => void, opts?: { timeout: number }) => number)
      | undefined;
    const cic = (window as any).cancelIdleCallback as
      | ((handle: number) => void)
      | undefined;

    if (typeof ric === 'function') {
      const handle = ric(
        () => {
          subscriber.next();
          subscriber.complete();
        },
        { timeout: 4000 },
      );
      return () => cic?.(handle);
    }

    const handle = window.setTimeout(() => {
      subscriber.next();
      subscriber.complete();
    }, 0);
    return () => clearTimeout(handle);
  });
}
