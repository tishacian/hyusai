import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { IconComponent } from '@app/shared/ui/icon.component';
import { StatusPulseComponent } from '@app/shared/ui/status-pulse.component';

@Component({
  selector: 'app-auth-shell',
  standalone: true,
  imports: [RouterOutlet, IconComponent, StatusPulseComponent],
  template: `
    <div class="min-h-screen flex items-center justify-center relative overflow-hidden">
      <!-- Aurora blooms -->
      <div class="absolute inset-0 pointer-events-none">
        <div
          class="absolute -top-24 -left-24 w-[520px] h-[520px] rounded-full bg-brand-500/25 blur-[130px] animate-pulse"
        ></div>
        <div
          class="absolute bottom-0 -right-24 w-[560px] h-[560px] rounded-full bg-violet-500/25 blur-[130px] animate-pulse"
          style="animation-delay: 2s"
        ></div>
        <div
          class="absolute top-1/3 left-1/2 -translate-x-1/2 w-[360px] h-[360px] rounded-full bg-indigo-500/20 blur-[120px] animate-pulse"
          style="animation-delay: 4s"
        ></div>
      </div>

      <div class="relative z-10 w-full max-w-md mx-4">
        <!-- Brand -->
        <div class="text-center mb-8">
          <div class="inline-flex items-center gap-3 mb-3">
            <div
              class="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold bg-gradient-to-br from-brand-400 via-brand-500 to-violet-500 shadow-glow"
            >
              A
            </div>
            <h1 class="gradient-title text-3xl font-bold tracking-tight">Agentium</h1>
          </div>
          <div class="inline-flex items-center gap-2 text-xs text-gray-400">
            <app-status-pulse tone="accent" />
            <span>AI Orchestration Platform</span>
          </div>
        </div>

        <!-- Glass card -->
        <div class="glass rounded-xl shadow-elevated p-8 border border-white/10">
          <router-outlet />
        </div>

        <p class="text-center text-[11px] text-gray-500 mt-6">
          Protected by end-to-end encryption · SOC 2 ready
        </p>
      </div>
    </div>
  `,
})
export class AuthShellComponent {}
