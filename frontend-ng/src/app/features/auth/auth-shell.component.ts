import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

/**
 * Cockpit-grade authentication shell.
 *
 * Replaces the legacy glass-morphism screen (soft purple aurora, large
 * radii, white/10 inputs) with the same visual DNA used across the rest
 * of the app: dark `--ck-bg-*` surfaces, hairline strokes, mono labels,
 * cool-cyan signal accents and a telemetry-style status strip. The goal
 * is that someone landing on /auth/signin immediately feels they are
 * *inside* Agentium, not on a generic marketing page.
 */
@Component({
  selector: 'app-auth-shell',
  standalone: true,
  imports: [RouterOutlet, StatusPulseComponent],
  template: `
    <div class="ck-auth-shell">
      <!-- Layered ambient backdrop (grid + subtle blooms) -->
      <div class="ck-auth-bg" aria-hidden="true">
        <div class="ck-auth-grid"></div>
        <div class="ck-auth-bloom ck-auth-bloom-cool"></div>
        <div class="ck-auth-bloom ck-auth-bloom-violet"></div>
        <div class="ck-auth-scanline"></div>
      </div>

      <!-- Top frame: brand + build badge -->
      <header class="ck-auth-frame">
        <div class="ck-auth-brand">
          <span class="ck-auth-mark" aria-hidden="true">
            <img src="/assets/brand/agentium-mark.svg" alt="" width="34" height="34" />
          </span>
          <span class="ck-auth-wordmark">Agentium</span>
          <span class="ck-auth-wordmark-dot" aria-hidden="true"></span>
          <span class="ck-auth-tagline">AI Orchestration Cockpit</span>
        </div>
        <div class="ck-auth-telemetry" role="status" aria-label="Service status">
          <app-status-pulse tone="success" />
          <span class="ck-auth-telemetry-label">COCKPIT · OPERATIONAL</span>
          <span class="ck-auth-telemetry-sep" aria-hidden="true"></span>
          <span class="ck-auth-telemetry-label ck-auth-telemetry-build">BUILD 2026.04.21</span>
        </div>
      </header>

      <!-- Centered card -->
      <main class="ck-auth-main">
        <div class="ck-auth-card">
          <div class="ck-auth-card-rail" aria-hidden="true"></div>
          <router-outlet />
        </div>

        <footer class="ck-auth-footer">
          <span class="ck-auth-footer-chip">
            <span class="ck-live-dot cool" aria-hidden="true"></span>
            END-TO-END ENCRYPTED
          </span>
          <span class="ck-auth-footer-sep" aria-hidden="true"></span>
          <span class="ck-auth-footer-chip">SOC 2 · READY</span>
          <span class="ck-auth-footer-sep" aria-hidden="true"></span>
          <span class="ck-auth-footer-chip">SSO · SAML READY</span>
        </footer>
      </main>
    </div>
  `,
  styles: [
    `
      :host { display: block; }

      .ck-auth-shell {
        position: relative;
        min-height: 100vh;
        min-height: 100dvh;
        background: var(--ck-bg-void);
        color: var(--ck-fg-1);
        font-family: var(--ck-font-sans);
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }

      /* ---- Backdrop layers ---- */
      .ck-auth-bg {
        position: absolute;
        inset: 0;
        pointer-events: none;
        overflow: hidden;
      }
      .ck-auth-grid {
        position: absolute;
        inset: 0;
        background-image:
          linear-gradient(var(--ck-stroke-1) 1px, transparent 1px),
          linear-gradient(90deg, var(--ck-stroke-1) 1px, transparent 1px);
        background-size: 48px 48px;
        mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, rgba(0, 0, 0, 0.9), transparent 75%);
        -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, rgba(0, 0, 0, 0.9), transparent 75%);
        opacity: 0.7;
      }
      .ck-auth-bloom {
        position: absolute;
        width: 720px;
        height: 720px;
        border-radius: 50%;
        filter: blur(150px);
        opacity: 0.28;
      }
      .ck-auth-bloom-cool {
        top: -260px;
        left: -240px;
        background: var(--ck-signal-cool);
      }
      .ck-auth-bloom-violet {
        bottom: -280px;
        right: -260px;
        background: var(--ck-signal-violet);
        opacity: 0.22;
      }
      .ck-auth-scanline {
        position: absolute;
        inset: 0;
        background: repeating-linear-gradient(
          to bottom,
          transparent 0px,
          transparent 3px,
          rgba(255, 255, 255, 0.015) 3px,
          rgba(255, 255, 255, 0.015) 4px
        );
        mix-blend-mode: overlay;
        opacity: 0.35;
      }

      /* ---- Top frame ---- */
      .ck-auth-frame {
        position: relative;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 28px;
        border-bottom: 1px solid var(--ck-stroke-1);
        min-height: var(--ck-titlebar-h, 48px);
        flex-wrap: wrap;
      }
      .ck-auth-brand {
        display: inline-flex;
        align-items: center;
        gap: 10px;
      }
      .ck-auth-mark {
        position: relative;
        width: 34px;
        height: 34px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        box-shadow: 0 0 0 1px var(--ck-stroke-hot), var(--ck-glow-cool);
        overflow: hidden;
      }
      .ck-auth-wordmark {
        font-family: var(--ck-font-mono);
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.04em;
        color: var(--ck-fg-1);
      }
      .ck-auth-wordmark-dot {
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: var(--ck-signal-cool);
        box-shadow: 0 0 8px var(--ck-signal-cool);
      }
      .ck-auth-tagline {
        font-family: var(--ck-font-mono);
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
      }
      .ck-auth-telemetry {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border: 1px solid var(--ck-stroke-2);
        background: var(--ck-bg-panel);
        border-radius: var(--ck-radius-sm);
      }
      .ck-auth-telemetry-label {
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-3);
      }
      .ck-auth-telemetry-build {
        color: var(--ck-fg-4);
      }
      .ck-auth-telemetry-sep {
        width: 1px;
        height: 10px;
        background: var(--ck-stroke-2);
      }

      /* ---- Main / card ---- */
      .ck-auth-main {
        position: relative;
        z-index: 2;
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 32px 20px 48px;
      }
      .ck-auth-card {
        position: relative;
        width: 100%;
        max-width: 420px;
        background: var(--ck-bg-panel);
        border: 1px solid var(--ck-stroke-2);
        border-radius: var(--ck-radius-lg);
        padding: 28px 28px 24px;
        box-shadow: var(--ck-shadow-panel);
      }
      .ck-auth-card-rail {
        position: absolute;
        left: 0;
        top: 16px;
        bottom: 16px;
        width: 2px;
        border-radius: 2px;
        background: linear-gradient(180deg, var(--ck-signal-cool), transparent 70%);
        opacity: 0.55;
      }

      /* ---- Footer chips ---- */
      .ck-auth-footer {
        margin-top: 22px;
        display: inline-flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
        justify-content: center;
      }
      .ck-auth-footer-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-family: var(--ck-font-mono);
        font-size: 9px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--ck-fg-4);
      }
      .ck-auth-footer-sep {
        width: 2px;
        height: 2px;
        border-radius: 50%;
        background: var(--ck-fg-5);
      }

      @media (max-width: 640px) {
        .ck-auth-frame {
          padding: 14px 16px;
        }
        .ck-auth-tagline {
          display: none;
        }
        .ck-auth-card {
          padding: 22px 20px 20px;
        }
      }
    `,
  ],
})
export class AuthShellComponent {}
