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
import { I18nService } from '@app/core/i18n.service';
import { TokenStorageService } from '@app/core/token-storage.service';
import { AuthStore } from '@app/store/auth.store';
import { AuthBootstrapService } from '@app/core/auth-bootstrap.service';
import { WorkspaceService } from '@app/core/workspace.service';
import {
  resolveSigninExperience,
  type SigninExperiencePresentation,
} from './signin-experience';

function isMfa(r: LoginResponse): r is MfaChallengeResponse {
  return (r as MfaChallengeResponse).mfa_required === true;
}

@Component({
  selector: 'app-signin',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    @if (!mfaChallenge()) {
      @if (signinExperience().securityBand; as securityBand) {
        <div class="ck-auth-security-band" role="note">
          {{ securityBand }}
        </div>
      }
      <header class="ck-auth-head">
        <span class="ck-auth-eyebrow">{{ signinExperience().eyebrow }}</span>
        <h2 class="ck-auth-title">{{ signinExperience().title }}</h2>
        <p class="ck-auth-sub">{{ signinExperience().subtitle }}</p>
        @if (signinExperience().sovereignTag; as sovereignTag) {
          <p class="ck-auth-sovereign-tag" [attr.aria-label]="i18n.t('auth.signin.sovereign_aria')">
            {{ sovereignTag }}
          </p>
        }
      </header>

      <form (ngSubmit)="onSubmit()" class="ck-auth-form">
        <div class="ck-field">
          <label class="ck-label" for="signin-email">{{ i18n.t('auth.signin.email') }}</label>
          <input
            id="signin-email"
            type="email"
            [(ngModel)]="email"
            name="email"
            required
            autocomplete="username"
            class="ck-input"
            [placeholder]="i18n.t('auth.signin.email_placeholder')"
          />
        </div>

        <div class="ck-field">
          <label class="ck-label" for="signin-password">{{ i18n.t('auth.signin.password') }}</label>
          <div class="ck-input-wrap">
            <input
              id="signin-password"
              [type]="showPassword() ? 'text' : 'password'"
              [(ngModel)]="password"
              name="password"
              required
              autocomplete="current-password"
              class="ck-input ck-input-with-suffix"
              placeholder="••••••••"
            />
            <button
              type="button"
              (click)="showPassword.set(!showPassword())"
              class="ck-input-suffix"
              [attr.aria-label]="i18n.t(showPassword() ? 'auth.signin.hide_password' : 'auth.signin.show_password')"
            >
              <app-icon [name]="showPassword() ? 'eye-off' : 'eye'" [size]="16" />
            </button>
          </div>
        </div>

        <label class="ck-check">
          <input
            type="checkbox"
            [(ngModel)]="rememberMe"
            name="rememberMe"
          />
          <span class="ck-check-box" aria-hidden="true"></span>
          <span class="ck-check-label">{{ i18n.t('auth.signin.remember') }}</span>
        </label>

        @if (error()) {
          <p class="ck-auth-error" role="alert">{{ error() }}</p>
        }

        <button
          type="submit"
          [disabled]="loading()"
          class="ck-btn-primary"
        >
          @if (loading()) {
            <span class="ck-btn-spinner" aria-hidden="true"></span>
            <span>{{ i18n.t('auth.signin.submitting') }}</span>
          } @else {
            <span>{{ signinExperience().submitLabel }}</span>
            <span class="ck-btn-chevron" aria-hidden="true">→</span>
          }
        </button>
      </form>

      <nav class="ck-auth-links" [attr.aria-label]="i18n.t('auth.signin.links_aria')">
        <a routerLink="/auth/password-reset" class="ck-auth-link">{{ i18n.t('auth.signin.forgot') }}</a>
        <span class="ck-auth-links-sep" aria-hidden="true"></span>
        <span class="ck-auth-links-meta">
          {{ i18n.t('auth.signin.new_to') }}
          <a routerLink="/auth/signup" class="ck-auth-link ck-auth-link-strong">{{ i18n.t('auth.signin.request_access') }}</a>
        </span>
      </nav>
    } @else {
      <header class="ck-auth-head ck-auth-head-mfa">
        <div class="ck-auth-mfa-icon" aria-hidden="true">
          <app-icon name="shield-check" [size]="22" />
        </div>
        <span class="ck-auth-eyebrow">{{ i18n.t('auth.mfa.eyebrow') }}</span>
        <h2 class="ck-auth-title">{{ i18n.t('auth.mfa.title') }}</h2>
        <p class="ck-auth-sub">
          {{ i18n.t('auth.mfa.sent_prefix') }}
          <span class="ck-auth-sub-strong">{{ mfaChallenge()!.email_hint }}</span>.
        </p>
      </header>

      <form (ngSubmit)="onSubmitMfa()" class="ck-auth-form">
        <div class="ck-otp-grid" (paste)="onPaste($event)">
          @for (i of [0,1,2,3,4,5]; track i) {
            <input
              #otpInput
              type="text"
              inputmode="numeric"
              maxlength="1"
              [value]="otpDigits()[i]"
              (input)="onDigitInput(i, $event)"
              (keydown)="onDigitKeydown(i, $event)"
              class="ck-otp-cell"
              [attr.aria-label]="i18n.t('auth.mfa.digit_of', { n: i + 1 })"
            />
          }
        </div>

        <div class="ck-otp-meta">
          @if (secondsLeft() > 0) {
            <span class="ck-otp-meta-dot ck-otp-meta-dot-live" aria-hidden="true"></span>
            <span class="ck-otp-meta-text">{{ i18n.t('auth.mfa.code_valid') }} · {{ formatCountdown() }}</span>
          } @else {
            <span class="ck-otp-meta-dot ck-otp-meta-dot-neg" aria-hidden="true"></span>
            <span class="ck-otp-meta-text ck-otp-meta-text-neg">{{ i18n.t('auth.mfa.code_expired') }}</span>
          }
        </div>

        @if (error()) {
          <p class="ck-auth-error" role="alert">{{ error() }}</p>
        }

        <button
          type="submit"
          [disabled]="loading() || otpDigits().join('').length !== 6 || secondsLeft() <= 0"
          class="ck-btn-primary"
        >
          @if (loading()) {
            <span class="ck-btn-spinner" aria-hidden="true"></span>
            <span>{{ i18n.t('auth.mfa.verifying') }}</span>
          } @else {
            <span>{{ i18n.t('auth.mfa.verify') }}</span>
            <span class="ck-btn-chevron" aria-hidden="true">→</span>
          }
        </button>

        <button
          type="button"
          (click)="resetToLogin()"
          class="ck-btn-ghost"
        >
          ← {{ i18n.t('auth.mfa.back') }}
        </button>
      </form>
    }
  `,
  styles: [
    `
      :host { display: block; color: var(--ck-fg-1); font-family: var(--ck-font-sans); }

      .ck-auth-security-band {
        margin-bottom: 14px;
        padding: 10px 12px;
        border: 1px solid rgba(101, 214, 110, 0.24);
        border-radius: var(--ck-radius-md);
        background: rgba(101, 214, 110, 0.08);
        color: rgba(207, 239, 255, 0.88);
        font-size: 12px;
        line-height: 1.45;
      }

      .ck-auth-head { margin-bottom: 20px; }
      .ck-auth-head-mfa { text-align: center; }
      .ck-auth-mfa-icon {
        width: 44px;
        height: 44px;
        margin: 0 auto 12px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: rgba(125, 211, 252, 0.08);
        border: 1px solid var(--ck-stroke-hot);
        color: var(--ck-signal-cool);
        box-shadow: var(--ck-glow-cool);
      }
      .ck-auth-eyebrow {
        display: block;
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.24em;
        text-transform: uppercase;
        color: var(--ck-signal-cool);
        margin-bottom: 6px;
      }
      .ck-auth-title {
        font-family: var(--ck-font-sans);
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: var(--ck-fg-1);
        margin: 0 0 6px;
      }
      .ck-auth-sub {
        font-size: 12.5px;
        color: var(--ck-fg-3);
        line-height: 1.55;
        margin: 0;
      }
      .ck-auth-sub-strong { color: var(--ck-fg-1); font-weight: 500; }
      .ck-auth-sovereign-tag {
        margin: 12px 0 0;
        padding: 6px 10px;
        display: inline-block;
        border: 1px solid rgba(101, 214, 110, 0.32);
        border-radius: var(--ck-radius-sm);
        background: rgba(101, 214, 110, 0.08);
        color: var(--sentinel-accent, #65d66e);
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }

      .ck-auth-form {
        display: flex;
        flex-direction: column;
        gap: 14px;
      }

      /* ---- Fields ---- */
      .ck-field { display: flex; flex-direction: column; gap: 6px; }
      .ck-label {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
      }
      .ck-input-wrap { position: relative; }
      .ck-input {
        width: 100%;
        padding: 11px 12px;
        background: var(--ck-bg-inset);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-md);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-sans);
        font-size: 13.5px;
        line-height: 1.2;
        outline: none;
        transition:
          border-color var(--ck-dur-fast) var(--ck-ease-out),
          box-shadow var(--ck-dur-fast) var(--ck-ease-out),
          background var(--ck-dur-fast) var(--ck-ease-out);
      }
      .ck-input::placeholder { color: var(--ck-fg-5); }
      .ck-input:hover { border-color: var(--ck-stroke-3); }
      .ck-input:focus,
      .ck-input:focus-visible {
        border-color: var(--ck-stroke-hot);
        background: var(--ck-bg-panel-hi);
        box-shadow: 0 0 0 1px var(--ck-signal-cool), 0 0 18px rgba(125, 211, 252, 0.18);
      }
      .ck-input-with-suffix { padding-right: 38px; }
      .ck-input-suffix {
        position: absolute;
        right: 6px;
        top: 50%;
        transform: translateY(-50%);
        width: 28px;
        height: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 0;
        background: transparent;
        color: var(--ck-fg-4);
        cursor: pointer;
        border-radius: var(--ck-radius-sm);
        transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-input-suffix:hover { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }

      /* ---- Checkbox ---- */
      .ck-check {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        user-select: none;
        -webkit-tap-highlight-color: transparent;
      }
      .ck-check input {
        position: absolute;
        opacity: 0;
        pointer-events: none;
        width: 0;
        height: 0;
      }
      .ck-check-box {
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid var(--ck-stroke-3);
        background: var(--ck-bg-inset);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: border-color var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-check input:focus-visible + .ck-check-box {
        box-shadow: 0 0 0 2px rgba(125, 211, 252, 0.25);
      }
      .ck-check input:checked + .ck-check-box {
        background: var(--ck-signal-cool);
        border-color: var(--ck-signal-cool);
      }
      .ck-check input:checked + .ck-check-box::after {
        content: "";
        width: 7px;
        height: 4px;
        border-left: 1.5px solid var(--ck-bg-void);
        border-bottom: 1.5px solid var(--ck-bg-void);
        transform: translateY(-1px) rotate(-45deg);
      }
      .ck-check-label {
        font-size: 12px;
        color: var(--ck-fg-3);
      }

      /* ---- Buttons ---- */
      .ck-btn-primary {
        position: relative;
        width: 100%;
        padding: 11px 14px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        background: linear-gradient(180deg, rgba(125, 211, 252, 0.22), rgba(125, 211, 252, 0.12));
        border: 1px solid var(--ck-stroke-hot);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-mono);
        font-size: 11px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        border-radius: var(--ck-radius-md);
        cursor: pointer;
        box-shadow:
          0 1px 0 rgba(255, 255, 255, 0.06) inset,
          0 0 24px rgba(125, 211, 252, 0.18);
        transition:
          background var(--ck-dur-fast) var(--ck-ease-out),
          border-color var(--ck-dur-fast) var(--ck-ease-out),
          box-shadow var(--ck-dur-fast) var(--ck-ease-out),
          transform var(--ck-dur-fast) var(--ck-ease-out);
      }
      .ck-btn-primary:hover:not(:disabled) {
        background: linear-gradient(180deg, rgba(125, 211, 252, 0.30), rgba(125, 211, 252, 0.18));
        border-color: rgba(125, 211, 252, 0.55);
        box-shadow:
          0 1px 0 rgba(255, 255, 255, 0.08) inset,
          0 0 32px rgba(125, 211, 252, 0.28);
      }
      .ck-btn-primary:active:not(:disabled) { transform: translateY(1px); }
      .ck-btn-primary:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
      .ck-btn-chevron {
        font-family: var(--ck-font-mono);
        font-size: 12px;
        color: var(--ck-signal-cool);
      }
      .ck-btn-spinner {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        border: 1.5px solid var(--ck-stroke-3);
        border-top-color: var(--ck-signal-cool);
        animation: ck-btn-spin 0.7s linear infinite;
      }
      @keyframes ck-btn-spin { to { transform: rotate(360deg); } }

      .ck-btn-ghost {
        width: 100%;
        padding: 8px 10px;
        background: transparent;
        border: 0;
        color: var(--ck-fg-3);
        font-family: var(--ck-font-mono);
        font-size: 11px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        cursor: pointer;
        border-radius: var(--ck-radius-sm);
        transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-btn-ghost:hover { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }

      /* ---- Error ---- */
      .ck-auth-error {
        display: flex;
        padding: 9px 11px;
        background: rgba(239, 90, 111, 0.08);
        border: 1px solid rgba(239, 90, 111, 0.35);
        border-radius: var(--ck-radius-sm);
        color: var(--ck-signal-neg);
        font-family: var(--ck-font-mono);
        font-size: 11.5px;
        letter-spacing: 0.02em;
        margin: 0;
      }

      /* ---- Links row ---- */
      .ck-auth-links {
        margin-top: 18px;
        padding-top: 14px;
        border-top: 1px dashed var(--ck-stroke-2);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        flex-wrap: wrap;
      }
      .ck-auth-links-sep {
        flex: 1;
        height: 1px;
        background: transparent;
      }
      .ck-auth-links-meta {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
      }
      .ck-auth-link {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
        text-decoration: none;
        border-bottom: 1px solid transparent;
        transition: color var(--ck-dur-fast), border-color var(--ck-dur-fast);
      }
      .ck-auth-link:hover { color: var(--ck-fg-1); border-bottom-color: var(--ck-signal-cool); }
      .ck-auth-link-strong { color: var(--ck-signal-cool); }
      .ck-auth-link-strong:hover { color: var(--ck-signal-ice); }

      /* ---- OTP ---- */
      .ck-otp-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 8px;
      }
      .ck-otp-cell {
        height: 52px;
        width: 100%;
        background: var(--ck-bg-inset);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-md);
        color: var(--ck-fg-1);
        text-align: center;
        font-family: var(--ck-font-mono);
        font-size: 22px;
        font-weight: 600;
        outline: none;
        transition: border-color var(--ck-dur-fast), background var(--ck-dur-fast), box-shadow var(--ck-dur-fast);
      }
      .ck-otp-cell:focus,
      .ck-otp-cell:focus-visible {
        border-color: var(--ck-stroke-hot);
        background: var(--ck-bg-panel-hi);
        box-shadow: 0 0 0 1px var(--ck-signal-cool);
      }
      .ck-otp-meta {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        margin: 2px auto 0;
      }
      .ck-otp-meta-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--ck-fg-4);
      }
      .ck-otp-meta-dot-live {
        background: var(--ck-signal-cool);
        box-shadow: 0 0 8px var(--ck-signal-cool);
      }
      .ck-otp-meta-dot-neg {
        background: var(--ck-signal-neg);
        box-shadow: 0 0 8px var(--ck-signal-neg);
      }
      .ck-otp-meta-text {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
      }
      .ck-otp-meta-text-neg { color: var(--ck-signal-neg); }
    `,
  ],
})
export class SigninComponent implements OnDestroy {
  protected readonly i18n = inject(I18nService);
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

  readonly signinExperience = signal<SigninExperiencePresentation>(
    resolveSigninExperience({ get: () => null }),
  );

  constructor() {
    const experience = resolveSigninExperience(this.route.snapshot.queryParamMap);
    this.signinExperience.set(experience);
    if (experience.prefillEmail) this.email = experience.prefillEmail;
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
          this.error.set(err.error?.detail || this.i18n.t('auth.signin.error.credentials'));
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
          this.error.set(err.error?.detail || this.i18n.t('auth.mfa.error.code'));
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
    this.workspaceService.loadWorkspaces().subscribe({
      next: () => {
        const redirect = this.normalizeRedirect(this.route.snapshot.queryParams['redirectURL']);
        this.router.navigateByUrl(redirect).then(
          () => this.loading.set(false),
          () => {
            this.loading.set(false);
            this.error.set(this.i18n.t('auth.signin.error.nav'));
          },
        );
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err.error?.detail || this.i18n.t('auth.signin.error.workspaces'));
      },
    });
  }

  private normalizeRedirect(value: unknown): string {
    const redirect = typeof value === 'string' && value.startsWith('/') ? value : '/';
    return redirect.startsWith('/auth') ? '/' : redirect;
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
