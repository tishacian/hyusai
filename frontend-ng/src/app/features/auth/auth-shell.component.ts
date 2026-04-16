import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-auth-shell',
  standalone: true,
  imports: [RouterOutlet],
  template: `
    <div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-900 via-brand-800 to-brand-700 relative overflow-hidden">
      <!-- Animated aurora background -->
      <div class="absolute inset-0 opacity-30">
        <div class="absolute top-0 -left-1/4 w-1/2 h-1/2 bg-brand-400 rounded-full mix-blend-multiply filter blur-3xl animate-pulse"></div>
        <div class="absolute bottom-0 -right-1/4 w-1/2 h-1/2 bg-purple-400 rounded-full mix-blend-multiply filter blur-3xl animate-pulse" style="animation-delay: 2s"></div>
        <div class="absolute top-1/2 left-1/2 w-1/3 h-1/3 bg-cyan-400 rounded-full mix-blend-multiply filter blur-3xl animate-pulse" style="animation-delay: 4s"></div>
      </div>

      <div class="relative z-10 w-full max-w-md mx-4">
        <!-- Logo -->
        <div class="text-center mb-8">
          <h1 class="text-3xl font-bold text-white tracking-tight">Agentium</h1>
          <p class="text-brand-200 mt-1 text-sm">AI Orchestration Platform</p>
        </div>

        <!-- Glass card -->
        <div class="backdrop-blur-xl bg-white/10 border border-white/20 rounded-2xl shadow-2xl p-8">
          <router-outlet />
        </div>
      </div>
    </div>
  `,
})
export class AuthShellComponent {}
