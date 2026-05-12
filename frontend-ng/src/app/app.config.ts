import { APP_INITIALIZER, ApplicationConfig, provideZonelessChangeDetection } from '@angular/core';
import { provideRouter, withPreloading } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { Chart, registerables } from 'chart.js';
import { provideToastr } from 'ngx-toastr';

import { routes } from './app.routes';
import { authInterceptor } from './core/auth.interceptor';
import { provideLucideIcons } from './shared/ui/icon-registry';
import { AuthBootstrapService } from './core/auth-bootstrap.service';
import { IdlePreloadStrategy } from './core/idle-preload.strategy';
import { HelpService } from './core/help.service';

Chart.register(...registerables);

export const appConfig: ApplicationConfig = {
  providers: [
    provideZonelessChangeDetection(),
    provideRouter(routes, withPreloading(IdlePreloadStrategy)),
    provideHttpClient(withInterceptors([authInterceptor])),
    provideAnimationsAsync(),
    {
      provide: APP_INITIALIZER,
      multi: true,
      useFactory: (svc: AuthBootstrapService) => () => svc.bootstrap(),
      deps: [AuthBootstrapService],
    },
    {
      provide: APP_INITIALIZER,
      multi: true,
      useFactory: (svc: HelpService) => () => {
        svc.load().subscribe();
        return Promise.resolve();
      },
      deps: [HelpService],
    },
    provideToastr({
      positionClass: 'toast-top-right',
      timeOut: 4000,
      closeButton: true,
      progressBar: true,
      progressAnimation: 'decreasing',
      newestOnTop: true,
      preventDuplicates: true,
      tapToDismiss: false,
      enableHtml: false,
    }),
    provideLucideIcons(),
  ],
};
