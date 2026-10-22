import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { I18nService } from '@app/core/i18n.service';
import { NavLinkDirective } from '@app/shared/cockpit';
import { FlowObservationWindowsService } from './flow-observation-windows.service';
import { FlowObservationCardComponent } from './flow-observation-card.component';

@Component({
  selector:'app-flow-observation-modal',
  standalone:true,
  imports:[A11yModule,FlowObservationCardComponent,NavLinkDirective],
  changeDetection:ChangeDetectionStrategy.OnPush,
  styleUrl:'./flow-observation-ui.scss',
  template:`
    @if(windows.modalPin();as pin){
      <div class="fo-modal-backdrop" (click)="windows.closeModal()">
        <section data-testid="flow-observation-modal" class="fo-modal" role="dialog" aria-modal="true" [attr.aria-label]="pin.title" cdkTrapFocus [cdkTrapFocusAutoCapture]="true" (click)="$event.stopPropagation()" (keydown.escape)="$event.preventDefault();$event.stopPropagation();windows.closeModal()">
          <app-flow-observation-card [pin]="pin" [expanded]="true" (closed)="windows.closeModal()" />
          <footer><span>{{i18n.t('flow.observation.snapshot_note')}}</span><a [navLink]="{type:'run',ref:pin.run.id}">{{i18n.t('flow.observation.open_run')}}</a></footer>
        </section>
      </div>
    }
  `,
})
export class FlowObservationModalComponent {
  readonly windows=inject(FlowObservationWindowsService);
  readonly i18n=inject(I18nService);
}
