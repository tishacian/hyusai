import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface TokenResponse {
  token: string;
  refresh_token: string | null;
  expires_in: number;
  token_type: string;
}

export interface MfaChallengeResponse {
  mfa_required: true;
  mfa_token: string;
  email_hint: string;
  ttl_seconds: number;
}

export type LoginResponse = TokenResponse | MfaChallengeResponse;

export interface UserProfile {
  id: string;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  mfa_enabled: boolean;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  company: string | null;
  job_title: string | null;
  workspaces: { id: string; name: string; slug: string; role: string }[];
}

export interface LoginBody {
  email: string;
  password: string;
  remember_me: boolean;
}

export interface VerifyMfaBody {
  mfa_token: string;
  code: string;
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

export interface ProfileUpdateBody {
  first_name?: string;
  last_name?: string;
  phone?: string;
  company?: string;
  job_title?: string;
}

export interface ChangePasswordBody {
  current_password: string;
  new_password: string;
}

export interface KcSession {
  id: string;
  ip_address: string;
  start: number;
  last_access: number;
  clients: string[];
}

@Injectable({ providedIn: 'root' })
export class AuthApiService {
  private readonly http = inject(HttpClient);

  login(body: LoginBody): Observable<LoginResponse> {
    return this.http.post<LoginResponse>('/api/v1/auth/login', body);
  }

  verifyMfa(body: VerifyMfaBody): Observable<TokenResponse> {
    return this.http.post<TokenResponse>('/api/v1/auth/verify-mfa', body);
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

  updateProfile(body: ProfileUpdateBody): Observable<{ status: string }> {
    return this.http.patch<{ status: string }>('/api/v1/auth/me', body);
  }

  changePassword(body: ChangePasswordBody): Observable<{ status: string }> {
    return this.http.post<{ status: string }>('/api/v1/auth/change-password', body);
  }

  logoutAll(): Observable<{ status: string }> {
    return this.http.post<{ status: string }>('/api/v1/auth/logout-all', {});
  }

  listSessions(): Observable<KcSession[]> {
    return this.http.get<KcSession[]>('/api/v1/auth/sessions');
  }

  deleteAccount(): Observable<{ status: string }> {
    return this.http.delete<{ status: string }>('/api/v1/auth/me');
  }

  toggleMfa(enabled: boolean): Observable<{ status: string; mfa_enabled: boolean }> {
    return this.http.post<{ status: string; mfa_enabled: boolean }>(
      '/api/v1/auth/mfa/toggle',
      { enabled }
    );
  }

  signup(body: SignupBody): Observable<{ status: string; message: string; verification_email_sent?: boolean }> {
    return this.http.post<{ status: string; message: string; verification_email_sent?: boolean }>(
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
