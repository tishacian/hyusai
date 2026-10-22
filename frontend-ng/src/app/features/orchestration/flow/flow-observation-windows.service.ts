/** Ephemeral consultative windows; never part of the executable Flow. */
import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { FlowObservationService } from './flow-observation.service';
import {
  appendObservationPin, moveObservationPin, removeObservationPin, snapshotObservationPin, selectObservationPinSeries,
  type FlowObservationPin,
} from './flow-observation-windows.vm';

@Injectable()
export class FlowObservationWindowsService {
  private readonly observation = inject(FlowObservationService);
  readonly pins = signal<FlowObservationPin[]>([]);
  readonly modalPin = signal<FlowObservationPin | null>(null);
  readonly pinNotice = signal<'limit' | 'unavailable' | null>(null);
  private lastRevocationEpoch = 0;

  constructor() {
    effect(() => {
      this.observation.scopeEpoch();
      untracked(() => { this.clear(); this.lastRevocationEpoch = 0; });
    });
    effect(() => {
      const revoked = this.observation.revocation();
      if (revoked) untracked(() => {
        this.revokeRuns(Object.entries(revoked.events).filter(([,epoch])=>epoch>this.lastRevocationEpoch).map(([id])=>id));
        this.lastRevocationEpoch = revoked.epoch;
      });
    });
  }

  pin(input: Omit<FlowObservationPin, 'id'>): FlowObservationPin | null {
    const pin = snapshotObservationPin(input);
    if (!pin) { this.pinNotice.set('unavailable'); return null; }
    const result = appendObservationPin(this.pins(), pin);
    this.pinNotice.set(result.outcome === 'limit' ? 'limit' : null);
    this.pins.set(result.pins);
    return result.outcome === 'limit' ? null : result.pins.find(item => item.id === pin.id) ?? null;
  }

  move(id: string, position: { x: number; y: number }): void {
    this.pins.update(pins => moveObservationPin(pins, id, position));
  }

  selectSeries(id: string, name: string | null): void {
    this.pins.update(pins => pins.map(pin => pin.id === id ? selectObservationPinSeries(pin, name) : pin));
    const modal = this.modalPin();
    if (modal?.id === id) this.modalPin.set(selectObservationPinSeries(modal, name));
  }

  unpin(id: string): void {
    this.pins.update(pins => removeObservationPin(pins, id));
    if (this.modalPin()?.id === id) this.closeModal();
    this.pinNotice.set(null);
  }

  show(pin: FlowObservationPin): void { this.modalPin.set(pin); }

  showCurrent(input: Omit<FlowObservationPin, 'id'>): void {
    const pin = snapshotObservationPin(input);
    if (pin) this.modalPin.set(pin);
  }

  closeModal(): void { this.modalPin.set(null); }

  /** A later denied read invalidates already opened evidence for that Run. */
  revokeRuns(runIds: readonly string[]): void {
    const revoked = new Set(runIds);
    this.pins.update(pins => pins.filter(pin => !revoked.has(pin.run.id)));
    const modal = this.modalPin();
    if (modal && revoked.has(modal.run.id)) this.closeModal();
  }

  /** Dataset ACLs are independent from the Run's own read permission. */
  revokeDataset(datasetId: string): void {
    this.pins.update(pins => pins.filter(pin => pin.datasetPreview?.dataset_id !== datasetId));
    if (this.modalPin()?.datasetPreview?.dataset_id === datasetId) this.closeModal();
  }

  clear(): void {
    this.pins.set([]);
    this.modalPin.set(null);
    this.pinNotice.set(null);
  }
}
