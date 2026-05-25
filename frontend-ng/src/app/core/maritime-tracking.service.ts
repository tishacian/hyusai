import { Injectable, inject, signal } from '@angular/core';
import { Observable, ReplaySubject, of } from 'rxjs';
import { catchError, shareReplay, tap } from 'rxjs/operators';
import { ApiService } from './api.service';

export interface VesselPosition {
  mmsi: string;
  imo?: string;
  name: string;
  lat: number;
  lon: number;
  sog?: number;
  cog?: number;
  heading?: number;
  vessel_type?: string;
  nav_status?: string;
  destination?: string;
  eta?: string;
  last_seen?: string;
  source?: string;
  linked_cargo_id?: string;
  linked_project_ref?: string;
  highlight?: string;
  demo_role?: string;
  recommended_webcam_source_id?: string;
}

export interface MaritimeVesselsSnapshot {
  vessels: VesselPosition[];
  bbox?: { west: number; south: number; east: number; north: number } | null;
  source?: string;
  provider?: string;
  fetched_at?: string;
  embed_url?: string | null;
  attribution?: string | null;
  count?: number;
}

/**
 * Default bbox covers the Abidjan / Vridi window used by the SENTINEL-CI demo.
 * Matches the backend baseline (`abidjan-vessels-baseline.json`) so the snapshot
 * always returns the full 16-vessel demo set.
 */
const DEFAULT_BBOX = '-4.25,5.05,-3.75,5.40';

/**
 * Provides a single, cached view of the live AIS vessel snapshot to any
 * component that needs to render vessels (cockpit preview, strategic map,
 * mission control monitor). The HTTP call is performed at most once per
 * bbox+limit combination and shared via `shareReplay`.
 */
@Injectable({ providedIn: 'root' })
export class MaritimeTrackingService {
  private readonly api = inject(ApiService);
  private readonly cache = new Map<string, Observable<MaritimeVesselsSnapshot>>();
  private readonly latestSubject = new ReplaySubject<MaritimeVesselsSnapshot>(1);
  private readonly selectedVesselSignal = signal<VesselPosition | null>(null);

  /** Last vessel picked on any map (cockpit preview, Mission Control, strategie). */
  readonly selectedVessel = this.selectedVesselSignal.asReadonly();

  /**
   * Returns the cached snapshot for the given bbox + limit. Subsequent
   * subscribers receive the replayed value without re-fetching.
   */
  getSnapshot(bbox: string = DEFAULT_BBOX, limit = 50): Observable<MaritimeVesselsSnapshot> {
    const key = `${bbox}|${limit}`;
    const cached = this.cache.get(key);
    if (cached) return cached;
    const stream$ = this.api
      .get<MaritimeVesselsSnapshot>('/mission-room/maritime/vessels', {
        bbox,
        limit: String(limit),
      })
      .pipe(
        catchError(() =>
          of<MaritimeVesselsSnapshot>({
            vessels: [],
            source: 'baseline',
            provider: 'baseline',
            attribution: null,
          }),
        ),
        tap((snapshot) => this.latestSubject.next(snapshot)),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    this.cache.set(key, stream$);
    return stream$;
  }

  /** Observable of the most recently fetched snapshot, useful for downstream UIs. */
  readonly latest$ = this.latestSubject.asObservable();

  selectVessel(vessel: VesselPosition | null): void {
    this.selectedVesselSignal.set(vessel);
  }

  clearSelection(): void {
    this.selectedVesselSignal.set(null);
  }
}
