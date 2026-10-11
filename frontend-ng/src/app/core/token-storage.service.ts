import { Injectable } from '@angular/core';

const TOKEN_KEY = 'agentium_token';
const REFRESH_KEY = 'agentium_refresh_token';

@Injectable({ providedIn: 'root' })
export class TokenStorageService {
  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  saveToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, `Bearer ${token}`);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  }

  saveRefreshToken(token: string): void {
    localStorage.setItem(REFRESH_KEY, token);
  }

  clear(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }

  get isAuthenticated(): boolean {
    return !!this.getToken();
  }
}
