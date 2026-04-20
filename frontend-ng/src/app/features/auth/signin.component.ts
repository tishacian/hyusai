import {
  Component,
  ElementRef,
  effect,
  inject,
  signal,
  viewChildren,
  OnDestroy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, ActivatedRoute } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import {
  AuthApiService,
  LoginResponse,
  TokenResponse,
  MfaChallengeResponse,
} from '@app/core/auth-api.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { WorkspaceService } from '@app/core/workspace.service';

function isMfa(r: LoginResponse): r is MfaChallengeResponse {
  return (r as MfaChallengeResponse).mfa_required === true;
}

@Component({
  selector: 'app-signin',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    @if (!mfaChallenge()) {
      <h2 class="text-xl font-semibold text-white mb-6">Sign in</h2>

      <form (ngSubmit)="onSubmit()" class="space-y-4">
        <div>
          <label class="block text-sm text-brand-200 mb-1">Email</label>
          <input
            type="email"
            [(ngModel)]="email"
            name="email"
            required
            autocomplete="username"
            class="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400"
            placeholder="you&#64;company.com"
          />
        </div>

        <div>
          <label class="block text-sm text-brand-200 mb-1">Password</label>
          <div class="relative">
            <input
              [type]="showPassword() ? 'text' : 'password'"
              [(ngModel)]="password"
              name="password"
              required
              autocomplete="current-password"
              class="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-brand-400 pr-10"
              placeholder="••••••••"
            />
            <button
              type="button"
              (click)="showPassword.set(!showPassword())"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-white/50 hover:text-white"
            >
              <app-icon [name]="showPassword() ? 'eye-off' : 'eye'" [size]="16" />
            </button>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            [(ngModel)]="rememberMe"
            name="rememberMe"
            id="rememberMe"
            class="rounded border-white/30"
          />
          <label for="rememberMe" class="text-sm text-brand-200">Remember me</label>
        </div>

        @if (error()) {
          <p class="text-red-300 text-sm">{{ error() }}</p>
        }

        <button
          type="submit"
          [disabled]="loading()"
          class="w-full py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition"
        >
          @if (loading()) { Signing in... } @else { Sign in }
        </button>
      </form>

      <div class="mt-6 text-center text-sm text-brand-200 space-y-1">
        <p>
          <a routerLink="/auth/password-reset" class="hover:text-white underline">Forgot password?</a>
        </p>
        <p>
          Don't have an account?
          <a routerLink="/auth/signup" class="hover:text-white underline">Sign up</a>
        </p>
      </div>
    } @else {
      <div class="text-center mb-2">
        <div class="mx-auto w-12 h-12 rounded-full bg-brand-500/15 ring-1 ring-brand-500/30 flex items-center justify-center text-brand-400">
          <app-icon name="shield-check" [size]="22" />
        </div>
        <h2 class="text-xl font-semibold text-white mt-4">Two-factor authentication</h2>
        <p class="text-sm text-brand-200 mt-2">
          We sent a 6-digit code to <span class="text-white font-medium">{{ mfaChallenge()!.email_hint }}</span>
        </p>
      </div>

      <form (ngSubmit)="onSubmitMfa()" class="mt-6 space-y-4">
        <div class="flex justify-center gap-2" (paste)="onPaste($event)">
          @for (i of [0,1,2,3,4,5]; track i) {
            <input
              #otpInput
              type="text"
              inputmode="numeric"
              maxlength="1"
              [value]="otpDigits()[i]"
              (input)="onDigitInput(i, $event)"
              (keydown)="onDigitKeydown(i, $event)"
              class="w-12 h-14 text-center text-2xl font-bold bg-white/10 border border-white/20 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-brand-400"
            />
          }
        </div>

        <p class="text-center text-sm text-brand-200">
          @if (secondsLeft() > 0) {
            Code valid for {{ formatCountdown() }}
          } @else {
            <span class="text-red-300">Code expired. Please sign in again.</span>
          }
        </p>

        @if (error()) {
          <p class="text-red-300 text-sm text-center">{{ error() }}</p>
        }

        <button
          type="submit"
          [disabled]="loading() || otpDigits().join('').length !== 6 || secondsLeft() <= 0"
          class="w-full py-2.5 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium rounded-lg transition"
        >
          @if (loading()) { Verifying... } @else { Verify }
        </button>

        <button
          type="button"
          (click)="resetToLogin()"
          class="w-full text-sm text-brand-200 hover:text-white underline"
        >
          Back to sign in
        </button>
      </form>
    }
  `,
})
export class SigninComponent implements OnDestroy {
  private readonly authApi = inject(AuthApiService);
  private readonly tokenStorage = inject(TokenStorageService);
  private readonly authStore = inject(AuthStore);
  private readonly authBootstrap = inject(AuthBootstrapService);
  private readonly workspaceService = inject(WorkspaceService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  email = '';
  password = '';
  rememberMe = false;
  showPassword = signal(false);
  loading = signal(false);
  error = signal<string | null>(null);

  mfaChallenge = signal<MfaChallengeResponse | null>(null);
  otpDigits = signal<string[]>(['', '', '', '', '', '']);
  secondsLeft = signal(0);
  private countdownTimer: ReturnType<typeof setInterval> | null = null;

  otpInputs = viewChildren<ElementRef<HTMLInputElement>>('otpInput');

  constructor() {
    effect(() => {
      const digits = this.otpDigits();
      if (digits.join('').length === 6 && this.mfaChallenge() && !this.loading() && this.secondsLeft() > 0) {
        queueMicrotask(() => this.onSubmitMfa());
      }
    });
  }

  ngOnDestroy(): void {
    this.clearTimer();
  }

  private clearTimer(): void {
    if (this.countdownTimer) {
      clearInterval(this.countdownTimer);
      this.countdownTimer = null;
    }
  }

  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);

    this.authApi
      .login({ email: this.email, password: this.password, remember_me: this.rememberMe })
      .subscribe({
        next: (res) => {
          if (isMfa(res)) {
            this.mfaChallenge.set(res);
            this.secondsLeft.set(res.ttl_seconds);
            this.startCountdown();
            this.loading.set(false);
            queueMicrotask(() => this.otpInputs()[0]?.nativeElement.focus());
          } else {
            this.completeLogin(res);
          }
        },
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Invalid credentials');
        },
      });
  }

  private startCountdown(): void {
    this.clearTimer();
    this.countdownTimer = setInterval(() => {
      const n = this.secondsLeft() - 1;
      this.secondsLeft.set(Math.max(0, n));
      if (n <= 0) this.clearTimer();
    }, 1000);
  }

  formatCountdown(): string {
    const s = this.secondsLeft();
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${r.toString().padStart(2, '0')}`;
  }

  onDigitInput(index: number, event: Event): void {
    const input = event.target as HTMLInputElement;
    const val = input.value.replace(/\D/g, '').slice(-1);
    const next = [...this.otpDigits()];
    next[index] = val;
    this.otpDigits.set(next);

    if (val && index < 5) {
      this.otpInputs()[index + 1]?.nativeElement.focus();
    }
  }

  onDigitKeydown(index: number, event: KeyboardEvent): void {
    if (event.key === 'Backspace' && !this.otpDigits()[index] && index > 0) {
      this.otpInputs()[index - 1]?.nativeElement.focus();
    } else if (event.key === 'ArrowLeft' && index > 0) {
      this.otpInputs()[index - 1]?.nativeElement.focus();
    } else if (event.key === 'ArrowRight' && index < 5) {
      this.otpInputs()[index + 1]?.nativeElement.focus();
    }
  }

  onPaste(event: ClipboardEvent): void {
    const text = event.clipboardData?.getData('text') ?? '';
    const digits = text.replace(/\D/g, '').slice(0, 6);
    if (!digits) return;
    event.preventDefault();
    const next = ['', '', '', '', '', ''];
    for (let i = 0; i < digits.length; i++) next[i] = digits[i];
    this.otpDigits.set(next);
    const focusIndex = Math.min(digits.length, 5);
    this.otpInputs()[focusIndex]?.nativeElement.focus();
  }

  onSubmitMfa(): void {
    const challenge = this.mfaChallenge();
    if (!challenge) return;
    const code = this.otpDigits().join('');
    if (code.length !== 6) return;

    this.loading.set(true);
    this.error.set(null);

    this.authApi
      .verifyMfa({ mfa_token: challenge.mfa_token, code, remember_me: this.rememberMe })
      .subscribe({
        next: (tokens) => this.completeLogin(tokens),
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Invalid code');
          this.otpDigits.set(['', '', '', '', '', '']);
          queueMicrotask(() => this.otpInputs()[0]?.nativeElement.focus());
        },
      });
  }

  private completeLogin(tokens: TokenResponse): void {
    this.tokenStorage.saveToken(tokens.token);
    if (tokens.refresh_token) {
      this.tokenStorage.saveRefreshToken(tokens.refresh_token);
    }
    this.authStore.setAuthenticated({
      userId: '',
      email: this.email,
      role: 'user',
    });
    this.authBootstrap.markValid();
    this.workspaceService.loadWorkspaces().subscribe();
    const redirect = this.route.snapshot.queryParams['redirectURL'] || '/';
    this.router.navigateByUrl(redirect);
  }

  resetToLogin(): void {
    this.mfaChallenge.set(null);
    this.otpDigits.set(['', '', '', '', '', '']);
    this.secondsLeft.set(0);
    this.clearTimer();
    this.error.set(null);
    this.loading.set(false);
  }
}
