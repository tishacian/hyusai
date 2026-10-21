import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpParams, type HttpResponse } from '@angular/common/http';
import { firstValueFrom, type Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { WorkspaceService } from '@app/core/workspace.service';
import type { CandidateEvidence, DeliveryReceipt, Page, ReviewDecision, ReviewRequest, ServiceAssetMetadata, ServiceContract, ServiceDefinition, ServiceIncident, ServiceWindow } from './service-delivery.models';
@Injectable({ providedIn: 'root' })
export class ServiceDeliveryApi {
  private readonly workspace = inject(WorkspaceService);
  private async request<T>(request: Observable<T>): Promise<T> {
    const scope = this.workspace.captureRequestScope();
    const result = await firstValueFrom(request);
    if (!this.workspace.isRequestScopeCurrent(scope)) throw new Error('dataops.error.workspace_changed');
    return result;
  }
  private readonly http = inject(HttpClient); private readonly base = '/api/v1/service-contracts';
  list<T>(path: '' | '/windows' | '/incidents' | '/receipts' | '/assets', offset = 0): Promise<Page<T>> { return this.request(this.http.get<Page<T>>(`${this.base}${path}`, { params: new HttpParams().set('offset', offset).set('limit', 25) })); }
  assets(offset = 0): Promise<Page<ServiceAssetMetadata>> { return this.list('/assets', offset); }
  qualificationPolicies(): Promise<{items: Array<{digest:string; name:string}>}> { return this.request(this.http.get<{items:Array<{digest:string;name:string}>}>(`${this.base}/qualification-policies`)); }
  contracts(offset = 0): Promise<Page<ServiceContract>> { return this.list('', offset); }
  windows(offset = 0): Promise<Page<ServiceWindow>> { return this.list('/windows', offset); }
  incidents(offset = 0): Promise<Page<ServiceIncident>> { return this.list('/incidents', offset); }
  receipts(offset = 0): Promise<Page<DeliveryReceipt>> { return this.list('/receipts', offset); }
  receipt(id: string): Promise<DeliveryReceipt> { return this.request(this.http.get<DeliveryReceipt>(`${this.base}/receipts/${encodeURIComponent(id)}`)); }
  candidate(id: string): Promise<CandidateEvidence> { return this.request(this.http.get<CandidateEvidence>(`${this.base}/windows/${encodeURIComponent(id)}/candidate`)); }
  candidateObject(id: string, index: number, digest: string, fence: number): Promise<HttpResponse<Blob>> {
    if (!Number.isInteger(index) || index < 0) return Promise.reject(new Error('dataops.error.request'));
    return this.request(this.http.get(`${this.base}/windows/${encodeURIComponent(id)}/objects/${index}`, {
      responseType: 'blob', observe: 'response', params: new HttpParams().set('expected_asset_digest', digest).set('expected_fence', fence),
    }));
  }
  downloadReceipt(id: string): Promise<HttpResponse<Blob>> { return this.request(this.http.get(`${this.base}/receipts/${encodeURIComponent(id)}/download`, {responseType: 'blob', observe: 'response'})); }
  review(id: string, body: ReviewRequest): Promise<ReviewDecision> { return this.request(this.http.post<ReviewDecision>(`${this.base}/windows/${encodeURIComponent(id)}/review`, body)); }
  publish(id: string, body: { decision_id: string; fence: number }): Promise<DeliveryReceipt> { return this.request(this.http.post<DeliveryReceipt>(`${this.base}/windows/${encodeURIComponent(id)}/publish`, body)); }
  create(body: { system_id: string; logical_key: string; owner_user_id: string; definition: ServiceDefinition }): Promise<ServiceContract> { return this.request(this.http.post<ServiceContract>(this.base, body)); }
  activate(id: string): Promise<ServiceContract> { return this.request(this.http.post<ServiceContract>(`${this.base}/${encodeURIComponent(id)}/publish`, {})); }
  /** The writes as streams, for `settleWrite`: errors pass through, a changed workspace is an error too. */
  activate$(id: string): Observable<ServiceContract> { return this.scoped(this.http.post<ServiceContract>(`${this.base}/${encodeURIComponent(id)}/publish`, {})); }
  publish$(id: string, body: { decision_id: string; fence: number }): Observable<DeliveryReceipt> { return this.scoped(this.http.post<DeliveryReceipt>(`${this.base}/windows/${encodeURIComponent(id)}/publish`, body)); }
  private scoped<T>(request: Observable<T>): Observable<T> {
    const scope = this.workspace.captureRequestScope();
    return request.pipe(map((value) => { if (!this.workspace.isRequestScopeCurrent(scope)) throw new Error('dataops.error.workspace_changed'); return value; }));
  }
}
