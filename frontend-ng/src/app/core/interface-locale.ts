import { Injectable, signal } from '@angular/core';

import type { Locale } from './locale';

/**
 * The interface locale, mirrored by `I18nService`.
 *
 * Services loaded with the shell (such as `HelpService`) read the locale here
 * instead of injecting `I18nService`, which carries the dictionaries and must
 * stay out of the initial bundle.
 */
@Injectable({ providedIn: 'root' })
export class InterfaceLocale {
  readonly locale = signal<Locale>('fr');
}
