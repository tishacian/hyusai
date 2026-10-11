import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';

const PASSWORD_REGEX = /^(?=.*[0-9])(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9])(?=\S+$).{8,}$/;

@Component({
  selector: 'app-signup',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    @if (success()) {
      <div class="ck-auth-success">
        <div class="ck-auth-success-icon" aria-hidden="true">
          <app-icon name="mail" [size]="22" />
        </div>
        <span class="ck-auth-eyebrow">REQUEST RECEIVED</span>
        <h2 class="ck-auth-title">{{ verificationEmailSent() ? 'Check your email' : 'Account created' }}</h2>
        <p class="ck-auth-sub">
          {{ successMessage() }}
        </p>
        <a routerLink="/auth/signin" class="ck-btn-ghost ck-btn-ghost-wide">← Back to sign in</a>
      </div>
    } @else {
      <header class="ck-auth-head">
        <span class="ck-auth-eyebrow">REQUEST ACCESS</span>
        <h2 class="ck-auth-title">Create your cockpit</h2>
        <p class="ck-auth-sub">Personal workspace · provisioned after email verification.</p>
      </header>

      <form (ngSubmit)="onSubmit()" class="ck-auth-form">
        <div class="ck-field-row">
          <div class="ck-field">
            <label class="ck-label" for="signup-first">First name</label>
            <input
              id="signup-first"
              [(ngModel)]="firstName"
              name="firstName"
              required
              placeholder="Ada"
              class="ck-input"
            />
          </div>
          <div class="ck-field">
            <label class="ck-label" for="signup-last">Last name</label>
            <input
              id="signup-last"
              [(ngModel)]="lastName"
              name="lastName"
              required
              placeholder="Lovelace"
              class="ck-input"
            />
          </div>
        </div>

        <div class="ck-field">
          <label class="ck-label" for="signup-email">Email</label>
          <input
            id="signup-email"
            [(ngModel)]="email"
            name="email"
            type="email"
            required
            placeholder="you&#64;company.com"
            class="ck-input"
          />
        </div>

        <div class="ck-field">
          <label class="ck-label" for="signup-password">Password</label>
          <input
            id="signup-password"
            [(ngModel)]="password"
            name="password"
            type="password"
            required
            placeholder="8+ chars · upper · lower · digit · symbol"
            class="ck-input"
          />
        </div>

        <div class="ck-field">
          <label class="ck-label" for="signup-confirm">Confirm password</label>
          <input
            id="signup-confirm"
            [(ngModel)]="confirmPassword"
            name="confirmPassword"
            type="password"
            required
            placeholder="Repeat the same password"
            class="ck-input"
          />
        </div>

        <div class="ck-field">
          <label class="ck-label" for="signup-company">Company <span class="ck-label-hint">(optional)</span></label>
          <input
            id="signup-company"
            [(ngModel)]="company"
            name="company"
            placeholder="ACME Corp"
            class="ck-input"
          />
        </div>

        @if (error()) {
          <p class="ck-auth-error" role="alert">{{ error() }}</p>
        }

        <button type="submit" [disabled]="loading()" class="ck-btn-primary">
          @if (loading()) {
            <span class="ck-btn-spinner" aria-hidden="true"></span>
            <span>PROVISIONING…</span>
          } @else {
            <span>CREATE ACCOUNT</span>
            <span class="ck-btn-chevron" aria-hidden="true">→</span>
          }
        </button>
      </form>

      <nav class="ck-auth-links" aria-label="Account actions">
        <span class="ck-auth-links-meta">Already have an account?</span>
        <a routerLink="/auth/signin" class="ck-auth-link ck-auth-link-strong">Sign in</a>
      </nav>
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

      @media (max-width: 420px) {
        .ck-field-row { grid-template-columns: 1fr; }
      }
    `,
  ],
})
export class SignupComponent {
  private readonly authApi = inject(AuthApiService);
  private readonly router = inject(Router);

  firstName = '';
  lastName = '';
  email = '';
  password = '';
  confirmPassword = '';
  company = '';
  loading = signal(false);
  error = signal<string | null>(null);
  success = signal(false);
  successMessage = signal('We sent a confirmation link. Verify your email to finish provisioning your workspace.');
  verificationEmailSent = signal(true);

  onSubmit(): void {
    if (this.password !== this.confirmPassword) {
      this.error.set('Passwords do not match');
      return;
    }
    if (!PASSWORD_REGEX.test(this.password)) {
      this.error.set('Password must be 8+ characters with uppercase, lowercase, digit, and special character');
      return;
    }

    this.loading.set(true);
    this.error.set(null);

    this.authApi
      .signup({
        first_name: this.firstName,
        last_name: this.lastName,
        email: this.email,
        password: this.password,
        company: this.company || undefined,
      })
      .subscribe({
        next: (res) => {
          this.loading.set(false);
          this.verificationEmailSent.set(res.verification_email_sent !== false);
          this.successMessage.set(
            res.message ||
              'We sent a confirmation link. Verify your email to finish provisioning your workspace.',
          );
          this.success.set(true);
        },
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Registration failed');
        },
      });
  }
}
