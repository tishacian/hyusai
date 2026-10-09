import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@app/core/i18n.service';
import { workReleasePageLinks, type HostedWorkPage } from './work-release-pages-nav';

@Component({
  selector: 'app-work-release-pages-nav',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  styleUrl: './work-release-pages-nav.scss',
  template: `
    @if (links().length > 1) {
      <nav class="xp-work-nav" [attr.aria-label]="i18n.t('experience.work.pages')">
        @for (page of links(); track page.id) {
          <a [routerLink]="page.href" [attr.aria-current]="page.active ? 'page' : null">{{ page.title }}</a>
        }
      </nav>
    }
  `,
})
export class WorkReleasePagesNavComponent {
  readonly i18n = inject(I18nService);
  readonly document = input<unknown>(null);
  readonly slug = input.required<string>();
  readonly activePage = input<string | null>(null);
  readonly hostedPage = input<HostedWorkPage | null>(null);
  readonly links = computed(() => workReleasePageLinks(
    this.document(), this.slug(), this.i18n.locale(), this.activePage(), this.hostedPage(),
  ));
}
