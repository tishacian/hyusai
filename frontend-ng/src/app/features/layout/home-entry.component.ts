import { Component, inject } from "@angular/core";
import { I18nService } from "@app/core/i18n.service";
@Component({
  standalone: true,
  template: `<p role="status">{{ i18n.t("common.loading") }}</p>`,
})
export class HomeEntryComponent {
  readonly i18n = inject(I18nService);
}
