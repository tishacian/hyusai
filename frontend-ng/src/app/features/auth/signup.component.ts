import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { I18nService } from '@app/core/i18n.service';
import { IconComponent } from '@app/shared/ui/icon.component';
import { settleWrite, type WriteOutcome } from '@app/shared/ui/load-state';
import {
  passwordErrors,
  resendState,
  signupResult,
  type PasswordErrorKey,
  type ResendResponse,
  type SignupErrorKey,
  type SignupResponse,
  type SignupView,
} from './signup.vm';

@Component({
  selector: 'app-signup',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    @switch (view()) {
      @case ('form') {
        <header class="ck-auth-head">
          <span class="ck-auth-eyebrow">{{ i18n.t('auth.signup.eyebrow') }}</span>
          <h2 class="ck-auth-title">{{ i18n.t('auth.signup.heading') }}</h2>
          <p class="ck-auth-sub">{{ i18n.t('auth.signup.lead') }}</p>
        </header>

        <form (ngSubmit)="onSubmit()" class="ck-auth-form" novalidate data-testid="signup-form">
          <div class="ck-field-row">
            <div class="ck-field">
              <label class="ck-label" for="signup-first">{{ i18n.t('auth.signup.first_name') }}</label>
              <input id="signup-first" [(ngModel)]="firstName" name="firstName" required autocomplete="given-name" class="ck-input" />
            </div>
            <div class="ck-field">
              <label class="ck-label" for="signup-last">{{ i18n.t('auth.signup.last_name') }}</label>
              <input id="signup-last" [(ngModel)]="lastName" name="lastName" required autocomplete="family-name" class="ck-input" />
            </div>
          </div>

          <div class="ck-field">
            <label class="ck-label" for="signup-email">{{ i18n.t('auth.signin.email') }}</label>
            <input
              id="signup-email"
              [(ngModel)]="email"
              name="email"
              type="email"
              required
              autocomplete="email"
              [placeholder]="i18n.t('auth.signin.email_placeholder')"
              class="ck-input"
            />
          </div>

          <div class="ck-field">
            <label class="ck-label" for="signup-password">{{ i18n.t('auth.signin.password') }}</label>
            <input
              id="signup-password"
              [(ngModel)]="password"
              name="password"
              type="password"
              required
              autocomplete="new-password"
              aria-describedby="signup-password-rule"
              [attr.aria-invalid]="passwordError() ? 'true' : null"
              class="ck-input"
              (ngModelChange)="passwordError.set(null)"
            />
            <p id="signup-password-rule" class="ck-field-hint">{{ i18n.t('auth.signup.password_rule') }}</p>
            @if (passwordError(); as key) {
              <p class="ck-field-error" role="alert" data-testid="signup-password-error">{{ i18n.t(key) }}</p>
            }
          </div>

          <div class="ck-field">
            <label class="ck-label" for="signup-confirm">{{ i18n.t('auth.signup.confirm_password') }}</label>
            <input
              id="signup-confirm"
              [(ngModel)]="confirmPassword"
              name="confirmPassword"
              type="password"
              required
              autocomplete="new-password"
              [attr.aria-invalid]="confirmError() ? 'true' : null"
              class="ck-input"
              (ngModelChange)="confirmError.set(null)"
            />
            @if (confirmError(); as key) {
              <p class="ck-field-error" role="alert" data-testid="signup-confirm-error">{{ i18n.t(key) }}</p>
            }
          </div>

          <div class="ck-field">
            <label class="ck-label" for="signup-company">
              {{ i18n.t('auth.signup.company') }} <span class="ck-label-hint">{{ i18n.t('auth.signup.optional') }}</span>
            </label>
            <input id="signup-company" [(ngModel)]="company" name="company" autocomplete="organization" class="ck-input" />
          </div>

          @if (error(); as key) {
            <div class="ck-auth-error" role="alert" data-testid="signup-error">
              <p>{{ i18n.t(key) }}</p>
              @if (key === 'auth.signup.error.exists') {
                <p class="ck-auth-error-links">
                  <a routerLink="/auth/signin" class="ck-auth-link ck-auth-link-strong">{{ i18n.t('auth.signin.submit') }}</a>
                  <a routerLink="/auth/password-reset" class="ck-auth-link">{{ i18n.t('auth.signin.forgot') }}</a>
                </p>
              }
            </div>
          }

          <button type="submit" [disabled]="submitting()" class="ck-btn-primary" data-testid="signup-submit">
            @if (submitting()) {
              <span class="ck-btn-spinner" aria-hidden="true"></span>
              <span>{{ i18n.t('auth.signup.submitting') }}</span>
            } @else {
              <span>{{ i18n.t('auth.signup.submit') }}</span>
              <span class="ck-btn-chevron" aria-hidden="true">→</span>
            }
          </button>
        </form>

        <nav class="ck-auth-links" [attr.aria-label]="i18n.t('auth.signin.links_aria')">
          <span class="ck-auth-links-meta">{{ i18n.t('auth.signup.have_account') }}</span>
          <a routerLink="/auth/signin" class="ck-auth-link ck-auth-link-strong">{{ i18n.t('auth.signin.submit') }}</a>
        </nav>
      }
      @default {
        <div class="ck-auth-success" [attr.data-testid]="'signup-' + view()" role="status">
          <div class="ck-auth-success-icon" [class.ck-auth-success-icon--warn]="view() !== 'sent'" aria-hidden="true">
            <app-icon [name]="view() === 'sent' ? 'mail' : 'alert-triangle'" [size]="22" />
          </div>
          <span class="ck-auth-eyebrow">{{ i18n.t('auth.signup.result.' + view() + '.eyebrow') }}</span>
          <h2 class="ck-auth-title">{{ i18n.t('auth.signup.result.' + view() + '.title') }}</h2>
          <p class="ck-auth-sub">{{ i18n.t('auth.signup.result.' + view() + '.body', { email: email }) }}</p>

          @if (view() === 'sent') {
            <ol class="ck-auth-steps" [attr.aria-label]="i18n.t('auth.signup.next.label')">
              <li>{{ i18n.t('auth.signup.next.open_link') }}</li>
              <li>{{ i18n.t('auth.signup.next.sign_in') }}</li>
              <li>{{ i18n.t('auth.signup.next.empty_workspace') }}</li>
            </ol>
          } @else if (view() === 'unknown') {
            <a routerLink="/auth/signin" class="ck-btn-primary ck-auth-action" data-testid="signup-unknown-signin">
              {{ i18n.t('auth.signup.unknown.try_sign_in') }}
            </a>
          } @else {
            <div class="ck-auth-ways" [attr.aria-label]="i18n.t('auth.signup.way_out.label')" role="group">
              <button
                type="button"
                class="ck-btn-primary ck-auth-action"
                data-testid="signup-resend"
                [disabled]="resend() === 'sending'"
                (click)="resendEmail()"
              >
                {{ i18n.t(resend() === 'sending' ? 'auth.signup.way_out.resending' : 'auth.signup.way_out.resend') }}
              </button>
              <p class="ck-auth-sub">{{ i18n.t('auth.signup.way_out.admin') }}</p>
            </div>
            @if (resend() !== 'idle' && resend() !== 'sending') {
              <p
                class="ck-auth-resend"
                [class.ck-auth-resend--warn]="resend() !== 'sent'"
                [attr.role]="resend() === 'sent' ? 'status' : 'alert'"
                [attr.data-testid]="'signup-resend-' + resend()"
              >
                {{ i18n.t('auth.signup.resend.' + resend(), { email: email }) }}
              </p>
            }
          }
          <a routerLink="/auth/signin" class="ck-btn-ghost ck-btn-ghost-wide">← {{ i18n.t('auth.mfa.back') }}</a>
        </div>
      }
    }
  `,
  styles: [
    `
      :host { display: block; color: var(--ck-fg-1); font-family: var(--ck-font-sans); }

      .ck-auth-head { margin-bottom: 18px; }
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

      .ck-auth-form { display: flex; flex-direction: column; gap: 12px; }
      .ck-field-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
      }
      .ck-field { display: flex; flex-direction: column; gap: 6px; }
      .ck-label {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
      }
      .ck-label-hint {
        text-transform: none;
        letter-spacing: 0;
        color: var(--ck-fg-4);
        font-size: 10px;
      }
      .ck-input {
        width: 100%;
        padding: 10px 12px;
        background: var(--ck-bg-inset);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-md);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-sans);
        font-size: 13px;
        line-height: 1.2;
        outline: none;
        transition: border-color var(--ck-dur-fast), box-shadow var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-input::placeholder { color: var(--ck-fg-5); }
      .ck-input:hover { border-color: var(--ck-stroke-3); }
      .ck-input:focus,
      .ck-input:focus-visible {
        border-color: var(--ck-stroke-hot);
        background: var(--ck-bg-panel-hi);
        box-shadow: 0 0 0 1px var(--ck-signal-cool), 0 0 18px rgba(125, 211, 252, 0.18);
      }

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
        box-shadow: 0 1px 0 rgba(255, 255, 255, 0.06) inset, 0 0 24px rgba(125, 211, 252, 0.18);
        transition: background var(--ck-dur-fast), border-color var(--ck-dur-fast), box-shadow var(--ck-dur-fast), transform var(--ck-dur-fast);
      }
      .ck-btn-primary:hover:not(:disabled) {
        background: linear-gradient(180deg, rgba(125, 211, 252, 0.30), rgba(125, 211, 252, 0.18));
        border-color: rgba(125, 211, 252, 0.55);
        box-shadow: 0 1px 0 rgba(255, 255, 255, 0.08) inset, 0 0 32px rgba(125, 211, 252, 0.28);
      }
      .ck-btn-primary:active:not(:disabled) { transform: translateY(1px); }
      .ck-btn-primary:disabled { opacity: 0.55; cursor: not-allowed; box-shadow: none; }
      .ck-btn-chevron { font-family: var(--ck-font-mono); font-size: 12px; color: var(--ck-signal-cool); }
      .ck-btn-spinner {
        width: 12px; height: 12px;
        border-radius: 50%;
        border: 1.5px solid var(--ck-stroke-3);
        border-top-color: var(--ck-signal-cool);
        animation: ck-btn-spin 0.7s linear infinite;
      }
      @keyframes ck-btn-spin { to { transform: rotate(360deg); } }

      .ck-btn-ghost {
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
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        transition: color var(--ck-dur-fast), background var(--ck-dur-fast);
      }
      .ck-btn-ghost:hover { color: var(--ck-fg-1); background: var(--ck-bg-panel-hi); }
      .ck-btn-ghost-wide { width: 100%; margin-top: 14px; }

      .ck-auth-error {
        padding: 9px 11px;
        background: rgba(239, 90, 111, 0.08);
        border: 1px solid rgba(239, 90, 111, 0.35);
        border-radius: var(--ck-radius-sm);
        color: var(--ck-signal-neg);
        font-family: var(--ck-font-mono);
        font-size: 11.5px;
        margin: 0;
      }

      .ck-auth-links {
        margin-top: 16px;
        padding-top: 12px;
        border-top: 1px dashed var(--ck-stroke-2);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        flex-wrap: wrap;
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

      .ck-auth-success {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: 6px;
      }
      .ck-auth-success-icon {
        width: 48px; height: 48px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: rgba(125, 211, 252, 0.08);
        border: 1px solid var(--ck-stroke-hot);
        color: var(--ck-signal-cool);
        box-shadow: var(--ck-glow-cool);
        margin-bottom: 6px;
      }

      .ck-auth-error p { margin: 0; }
      .ck-auth-error-links { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 8px !important; }
      .ck-field-hint { margin: 0; font-size: 12px; line-height: 1.45; color: var(--ck-fg-3); }
      .ck-field-error { margin: 0; font-size: 12px; line-height: 1.45; color: var(--ck-signal-neg); }
      .ck-auth-success-icon--warn {
        border-color: var(--ck-signal-warn);
        color: var(--ck-signal-warn);
        background: transparent;
        box-shadow: none;
      }
      .ck-auth-steps {
        margin: 10px 0 0;
        padding-left: 1.25rem;
        text-align: left;
        font-size: 13px;
        line-height: 1.55;
        color: var(--ck-fg-2);
      }
      .ck-auth-ways { display: flex; flex-direction: column; gap: 10px; width: 100%; margin-top: 12px; }
      .ck-auth-action { text-decoration: none; margin-top: 12px; }
      .ck-auth-ways .ck-auth-action { margin-top: 0; }
      .ck-auth-resend { margin: 10px 0 0; font-size: 13px; line-height: 1.5; color: var(--ck-signal-pos); }
      .ck-auth-resend--warn { color: var(--ck-signal-warn); }

      @media (max-width: 420px) {
        .ck-field-row { grid-template-columns: 1fr; }
      }
    `,
  ],
})
export class SignupComponent {
  private readonly authApi = inject(AuthApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly i18n = inject(I18nService);

  firstName = '';
  lastName = '';
  email = '';
  password = '';
  confirmPassword = '';
  company = '';

  readonly view = signal<SignupView>('form');
  readonly submitting = signal(false);
  readonly error = signal<SignupErrorKey | null>(null);
  readonly passwordError = signal<PasswordErrorKey | null>(null);
  readonly confirmError = signal<PasswordErrorKey | null>(null);
  private readonly resendOutcome = signal<WriteOutcome<ResendResponse | null> | null>(null);
  readonly resend = computed(() => resendState(this.resendOutcome()));

  onSubmit(): void {
    if (this.submitting()) return;
    const fields = passwordErrors(this.password, this.confirmPassword);
    this.passwordError.set(fields.password);
    this.confirmError.set(fields.confirm);
    if (fields.password || fields.confirm) {
      focusField(fields.password ? 'signup-password' : 'signup-confirm');
      return;
    }

    this.error.set(null);
    this.submitting.set(true);
    settleWrite<SignupResponse | null>(
      this.authApi.signup({
        first_name: this.firstName,
        last_name: this.lastName,
        email: this.email,
        password: this.password,
        company: this.company || undefined,
      }),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((outcome) => {
        if (outcome.s === 'sent') return;
        this.submitting.set(false);
        const result = signupResult(outcome);
        this.error.set(result.error);
        this.view.set(result.view);
      });
  }

  resendEmail(): void {
    if (this.resend() === 'sending') return;
    settleWrite<ResendResponse | null>(this.authApi.resendSignupVerification(this.email))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((outcome) => {
        this.resendOutcome.set(outcome);
        if (resendState(outcome) === 'sent') this.view.set('sent');
      });
  }
}

function focusField(id: string): void {
  if (typeof document === 'undefined') return;
  document.getElementById(id)?.focus();
}
