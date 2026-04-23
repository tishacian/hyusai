import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  readonly base = '/api/v1';

  get<T>(path: string, params?: Record<string, string>): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => (httpParams = httpParams.set(k, v)));
    }
    return this.http.get<T>(`${this.base}${path}`, { params: httpParams });
  }

  post<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.post<T>(`${this.base}${path}`, body);
  }

  patch<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.patch<T>(`${this.base}${path}`, body);
  }

  put<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.put<T>(`${this.base}${path}`, body);
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(`${this.base}${path}`);
  }

  /** Upload an audio blob and receive a transcription. */
  transcribeAudio(blob: Blob, filename = 'recording.webm'): Observable<{ text: string }> {
    const form = new FormData();
    form.append('file', blob, filename);
    return this.http.post<{ text: string }>(`${this.base}/voice/transcribe`, form);
  }

  /** Synthesize speech (returns a playable audio Blob). */
  synthesizeSpeech(text: string, voice = 'nova'): Observable<Blob> {
    return this.http.post(
      `${this.base}/voice/synthesize`,
      { text, voice },
      { responseType: 'blob' },
    );
  }
}
