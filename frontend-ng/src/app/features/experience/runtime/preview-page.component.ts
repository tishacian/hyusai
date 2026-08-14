import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';
import { HelpTooltipComponent, PageFrameComponent } from '@app/shared/cockpit';
import { I18nService } from '@app/core/i18n.service';
import { SystemHomeService } from '../system-home.service';
import type { ExperienceDocument } from './model';
import { ExperienceRuntimeHostComponent } from './runtime-host.component';

@Component({
  selector: 'app-experience-preview-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HelpTooltipComponent, PageFrameComponent, ExperienceRuntimeHostComponent],
  template: `
    <ck-page-frame
      [eyebrow]="i18n.t('experience.runtime.preview.eyebrow')"
      [title]="
        provided()
          ? i18n.t('experience.home.preview.title')
          : i18n.t('experience.runtime.preview.title')
      "
      [description]="
        provided()
          ? i18n.t('experience.home.preview.description')
          : i18n.t('experience.runtime.preview.description')
      "
    >
      <ck-help titleHelp id="concept.business-application" />
      @if (document().pages.length > 1) {
        <div
          role="tablist"
          [attr.aria-label]="i18n.t('experience.runtime.preview.pages')"
          style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap"
        >
          @for (page of document().pages; track page.id) {
            <button
              type="button"
              role="tab"
              class="xp-rt-btn"
              [class.xp-rt-btn-ghost]="pageId() !== page.id"
              [attr.aria-selected]="pageId() === page.id"
              (click)="pageId.set(page.id)"
            >
              {{ page.title }}
            </button>
          }
        </div>
      }
      <app-experience-runtime-host [document]="document()" [pageId]="pageId()" />
    </ck-page-frame>
  `,
  styles: [
    `
      .xp-rt-btn {
        min-height: 32px;
        padding: 0 12px;
        border: 0;
        border-radius: 4px;
        background: var(--ck-signal-cool);
        color: var(--ck-on-signal, #0b1220);
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
      }
      .xp-rt-btn-ghost {
        background: transparent;
        color: var(--ck-fg-2);
        border: 1px solid var(--ck-stroke-3);
      }
    `,
  ],
})
export class ExperiencePreviewPageComponent {
  readonly i18n = inject(I18nService);
  private readonly home = inject(SystemHomeService);
  private readonly source = toSignal(
    inject(ActivatedRoute).queryParamMap.pipe(map((params) => params.get('source'))),
    { initialValue: null as string | null },
  );
  readonly pageId = signal('form_result');
  readonly provided = computed(() =>
    this.source() === 'home' ? this.home.document() : null,
  );

  readonly document = computed(
    () => this.provided() ?? sampleDocument(this.i18n),
  );

  constructor() {
    effect(() => {
      const pages = this.document().pages;
      const current = this.pageId();
      if (pages.some((page) => page.id === current)) return;
      const first = pages[0]?.id;
      if (first) this.pageId.set(first);
    });
  }
}

function sampleDocument(i18n: I18nService): ExperienceDocument {
  const t = i18n.t;
  return {
    pages: [
      {
        id: 'form_result',
        title: t('experience.runtime.sample.form.title'),
        components: [
          {
            type: 'header',
            id: 'form-head',
            props: {
              title: t('experience.runtime.sample.form.title'),
              subtitle: t('experience.runtime.sample.form.subtitle'),
            },
          },
          {
            type: 'form',
            id: 'expense-form',
            props: {
              bindingKey: 'preview.sample.submit',
              schema: {
                type: 'object',
                required: ['amount', 'category'],
                properties: {
                  amount: { type: 'number', title: t('experience.runtime.sample.form.amount') },
                  category: {
                    type: 'string',
                    title: t('experience.runtime.sample.form.category'),
                    enum: ['travel', 'meals'],
                  },
                  when: { type: 'string', format: 'date', title: t('experience.runtime.sample.form.when') },
                  urgent: { type: 'boolean', title: t('experience.runtime.sample.form.urgent') },
                  receipt: {
                    type: 'string',
                    format: 'binary',
                    title: t('experience.runtime.sample.form.receipt'),
                  },
                  reason: { type: 'string', title: t('experience.runtime.sample.form.reason') },
                },
              },
            },
          },
          { type: 'runtime_status', id: 'run-status' },
          { type: 'result', id: 'run-result' },
          { type: 'evidence', id: 'run-evidence' },
          {
            type: 'callout',
            id: 'unknown-note',
            props: { body: t('experience.runtime.sample.callout') },
          },
          { type: 'magic_widget', id: 'unknown-demo' },
        ],
      },
      {
        id: 'approval',
        title: t('experience.runtime.sample.approval.title'),
        components: [
          {
            type: 'header',
            id: 'appr-head',
            props: {
              title: t('experience.runtime.sample.approval.title'),
              subtitle: t('experience.runtime.sample.approval.subtitle'),
            },
          },
          { type: 'page', id: 'nested-ignored' },
          {
            type: 'section',
            id: 'appr-section',
            props: { title: t('experience.runtime.queue.title') },
          },
          {
            type: 'kpi',
            id: 'appr-kpi',
            props: { label: t('experience.runtime.sample.kpi.pending'), value: 3 },
          },
          {
            type: 'table',
            id: 'appr-table',
            props: {
              caption: t('experience.runtime.queue.title'),
              columns: [
                { key: 'who', label: t('experience.runtime.sample.table.requester') },
                { key: 'amount', label: t('experience.runtime.sample.table.amount') },
                { key: 'status', label: t('experience.runtime.sample.table.status') },
              ],
              rows: [
                { who: 'Ada', amount: '186', status: t('experience.runtime.status.pending_validation') },
              ],
            },
          },
          {
            type: 'queue',
            id: 'appr-queue',
            props: { items: [{ title: t('experience.runtime.sample.queue.item') }] },
          },
          {
            type: 'approval_card',
            id: 'appr-card',
            props: {
              title: t('experience.runtime.approval.title'),
              body: t('experience.runtime.sample.approval.body'),
              status: t('experience.runtime.status.pending_validation'),
            },
          },
          {
            type: 'history',
            id: 'appr-history',
            props: { items: [{ title: t('experience.runtime.sample.history.item'), at: '09:40' }] },
          },
          {
            type: 'result',
            id: 'appr-result',
            props: { value: { decision: 'pending', amount: 186 } },
          },
          {
            type: 'evidence',
            id: 'appr-evidence',
            props: { citations: [{ title: 'Travel policy', source: 'kb://travel' }] },
          },
          {
            type: 'action_button',
            id: 'appr-action',
            props: { bindingKey: 'preview.sample.approve', label: t('experience.runtime.form.submit') },
          },
        ],
      },
    ],
  };
}
