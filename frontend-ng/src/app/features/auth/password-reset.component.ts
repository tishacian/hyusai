import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthApiService } from '@app/core/auth-api.service';
import { IconComponent } from '@app/shared/ui/icon.component';

@Component({
  selector: 'app-password-reset',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  template: `
    <header class="ck-auth-head">
      <span class="ck-auth-eyebrow">RECOVERY</span>
      <h2 class="ck-auth-title">Reset your password</h2>
      <p class="ck-auth-sub">We'll email a time-limited link to regain cockpit access.</p>
    </header>

    @if (sent()) {
      <div class="ck-auth-success">
        <div class="ck-auth-success-icon" aria-hidden="true">
          <app-icon name="mail" [size]="22" />
        </div>
        <p class="ck-auth-sub">
          If that email exists, a reset link is on its way.
          <br />
          Check your inbox and spam folder.
        </p>
        <a routerLink="/auth/signin" class="ck-btn-ghost ck-btn-ghost-wide">← Back to sign in</a>
      </div>
    } @else {
      <form (ngSubmit)="onSubmit()" class="ck-auth-form">
        <div class="ck-field">
          <label class="ck-label" for="reset-email">Email</label>
          <input
            id="reset-email"
            type="email"
            [(ngModel)]="email"
            name="email"
            required
            placeholder="you&#64;company.com"
            class="ck-input"
          />
        </div>

        <button type="submit" [disabled]="loading()" class="ck-btn-primary">
          @if (loading()) {
            <span class="ck-btn-spinner" aria-hidden="true"></span>
            <span>SENDING…</span>
          } @else {
            <span>SEND RESET LINK</span>
            <span class="ck-btn-chevron" aria-hidden="true">→</span>
          }
        </button>
      </form>

      <nav class="ck-auth-links" aria-label="Account actions">
        <a routerLink="/auth/signin" class="ck-auth-link">← Back to sign in</a>
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

      .ck-auth-form { display: flex; flex-direction: column; gap: 14px; }
      .ck-field { display: flex; flex-direction: column; gap: 6px; }
      .ck-label {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
      }
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
      .ck-btn-ghost-wide { width: 100%; margin-top: 16px; }

      .ck-auth-links {
        margin-top: 16px;
        padding-top: 12px;
        border-top: 1px dashed var(--ck-stroke-2);
        display: flex;
        align-items: center;
        justify-content: center;
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

      .ck-auth-success {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: 10px;
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
      }
    `,
  ],
})
export class PasswordResetComponent {
  private readonly authApi = inject(AuthApiService);

  email = '';
  loading = signal(false);
  sent = signal(false);

  onSubmit(): void {
    this.loading.set(true);
    this.authApi.passwordReset(this.email).subscribe({
      next: () => {
        this.loading.set(false);
        this.sent.set(true);
      },
      error: () => {
        this.loading.set(false);
        this.sent.set(true);
      },
    });
  }
}
