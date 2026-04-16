import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface TokenResponse {
  token: string;
  refresh_token: string | null;
  expires_in: number;
  token_type: string;
}

export interface UserProfile {
  id: string;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  workspaces: { id: string; name: string; slug: string; role: string }[];
}

export interface LoginBody {
  email: string;
  password: string;
  remember_me: boolean;
}

export interface SignupBody {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  phone?: string;
  company?: string;
  job_title?: string;
}

@Injectable({ providedIn: 'root' })
export class AuthApiService {
  private readonly http = inject(HttpClient);

  login(body: LoginBody): Observable<TokenResponse> {
    return this.http.post<TokenResponse>('/api/v1/auth/login', body);
  }

  refresh(refreshToken: string): Observable<TokenResponse> {
    return this.http.post<TokenResponse>('/api/v1/auth/refresh', {
      refresh_token: refreshToken,
    });
  }

  logout(refreshToken?: string): Observable<unknown> {
    return this.http.post('/api/v1/auth/logout', {
      refresh_token: refreshToken ?? null,
    });
  }

  validate(): Observable<{ valid: boolean; user_id: string; email: string; role: string }> {
    return this.http.post<{ valid: boolean; user_id: string; email: string; role: string }>(
      '/api/v1/auth/validate',
      {}
    );
  }

  me(): Observable<UserProfile> {
    return this.http.get<UserProfile>('/api/v1/auth/me');
  }

  signup(body: SignupBody): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      '/api/v1/auth/signup',
      body
    );
  }

  passwordReset(email: string): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>(
      '/api/v1/auth/password-reset',
      { email }
    );
  }
}
