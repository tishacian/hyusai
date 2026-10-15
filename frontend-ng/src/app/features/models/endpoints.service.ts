import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Endpoint, EndpointScope, EndpointsFeatures, MLAlert, MLChannel } from './endpoints.vm';

@Injectable({ providedIn: 'root' })
export class EndpointsService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/v1/ml-operations';
  features(): Promise<EndpointsFeatures> { return firstValueFrom(this.http.get<EndpointsFeatures>(`${this.base}/features`)); }
  endpoints(scope: EndpointScope, systemId: string, offset = 0): Promise<{items: Endpoint[]; total: number}> {
    return firstValueFrom(this.http.get<{items: Endpoint[]; total: number}>(`${this.base}/endpoints`, {
      params: {scope, ...(systemId ? {system_id: systemId} : {}), limit: 50, offset},
    }));
  }
  alerts(scope: EndpointScope, systemId: string): Promise<{items: MLAlert[]; total: number}> {
    return firstValueFrom(this.http.get<{items: MLAlert[]; total: number}>(`${this.base}/alerts`, {
      params: {scope, ...(systemId ? {system_id: systemId} : {}), limit: 50},
    }));
  }
  channels(): Promise<{items: MLChannel[]}> { return firstValueFrom(this.http.get<{items: MLChannel[]}>(`${this.base}/channels`)); }
  saveChannel(body: Omit<MLChannel, 'id'>, id?: string): Promise<MLChannel> {
    return firstValueFrom(id ? this.http.put<MLChannel>(`${this.base}/channels/${encodeURIComponent(id)}`, body)
      : this.http.post<MLChannel>(`${this.base}/channels`, body));
  }
  acknowledge(id: string): Promise<MLAlert> {
    return firstValueFrom(this.http.post<MLAlert>(`${this.base}/alerts/${encodeURIComponent(id)}/acknowledge`, {}));
  }
}
